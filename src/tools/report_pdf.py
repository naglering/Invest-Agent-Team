"""증권사 스타일 투자 보고서 PDF 생성기.

data/histories/YYYY-MM-DD_TICKER/ 의 report.md(또는 summary.md) 본문을 그대로
이식하고, 1페이지 표지(헤더 + Key-Data 사이드바 + Key Takeaways + Risk-Reward
세로축 차트)를 메타 JSON으로 정밀 렌더한 뒤, Headless Chromium(Playwright)으로
A4 PDF를 출력한다. (하이브리드 스타일: 한국 증권사 헤더/사이드바 + 글로벌 IB의
Risk-Reward·Exhibit 규칙)

파이프라인:  report.md ──pandoc(gfm→html)──▶ 본문 HTML
             meta JSON  ──────────────────▶ 표지/사이드바/시나리오 차트
             둘을 Jinja2 템플릿으로 결합 ──▶ HTML ──Playwright──▶ PDF

메타 JSON 스키마(모든 필드 선택적, 없으면 우아하게 생략):
{
  "company": "Tesla, Inc.", "exchange": "NASDAQ",
  "report_type": "Company In-depth", "analyst": "AI Investment Committee",
  "headline": "한 줄 핵심 메시지",
  "rating": {"action": "관망", "action_en": "NEUTRAL", "stance": "유지",
             "target_price": "$569", "current_price": "$396.38",
             "upside_pct": "+43.6%", "conviction_stars": 2,
             "conviction_label": "중하", "position_pct": "3.0%"},
  "key_data": [{"label": "현재가", "value": "$396.38"}, ...],
  "price_return": [{"period": "1M", "abs": "-3.3%", "rel": "vs SPY ..."}, ...],
  "takeaways": ["불릿1", "불릿2", ...],
  "scenarios": [{"name": "Bull", "price": "$1,100", "ret": "+178%",
                 "prob": "30%", "assumption": "..."}, ... Base, Bear],
  "weighted": {"price": "$569", "ret": "+43.6%"},
  "disclaimer": "맨뒤 면책 문구(선택, 미지정 시 기본 문구)"
}
"""

import os
import re
import sys
import json
import subprocess
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
MEMOS_DIR = os.path.join(DATA_DIR, "histories")
_DATE_TICKER = re.compile(r"^(\d{4}-\d{2}-\d{2})_([A-Za-z0-9.\-]+)$")


# ──────────────────────────────────────────────────────────────────────────
# 디렉토리/파일 해석
# ──────────────────────────────────────────────────────────────────────────
def _resolve_dir(ticker: str, date: str = None) -> str:
    """ticker(+date)에 해당하는 histories 디렉토리 경로. date 미지정 시 최신."""
    ticker = ticker.upper()
    if not os.path.isdir(MEMOS_DIR):
        raise FileNotFoundError(f"histories 디렉토리 없음: {MEMOS_DIR}")
    if date:
        dirpath = os.path.join(MEMOS_DIR, f"{date}_{ticker}")
        if not os.path.isdir(dirpath):
            raise FileNotFoundError(f"메모 디렉토리 없음: {dirpath}")
        return dirpath
    # date 미지정 → 해당 티커의 최신 디렉토리
    matches = []
    for name in os.listdir(MEMOS_DIR):
        m = _DATE_TICKER.match(name)
        if m and m.group(2).upper() == ticker and os.path.isdir(os.path.join(MEMOS_DIR, name)):
            matches.append((m.group(1), name))
    if not matches:
        raise FileNotFoundError(f"{ticker} 메모 디렉토리를 찾을 수 없습니다 (data/histories/)")
    matches.sort(reverse=True)
    return os.path.join(MEMOS_DIR, matches[0][1])


# ──────────────────────────────────────────────────────────────────────────
# 이모지 처리 — 이모지 폰트 의존 제거
#   ① 의미(판정) 이모지 → PUA 센티넬 → (HTML 변환 후) 색상 기하기호 span
#   ② 그 외 장식 이모지 → 제거 (증권사 리포트 톤에 맞춰 정돈)
# PUA 센티넬(U+E0xx)은 평문이라 ②의 광역 제거 정규식을 통과하고, 변환 후 치환된다.
# ──────────────────────────────────────────────────────────────────────────
# 남은(장식) 이모지 광역 제거 — 픽토그램/기호/깃발/변이선택자. (센티넬 PUA·기하기호는 보존)
# 이모지 뒤 공백 1칸까지 함께 제거해, "**🌡️ 지표**" → "**지표**" 처럼 강조(**) 안쪽에
# 공백이 남아 마크다운 bold가 깨지는 것을 방지한다.
_EMOJI_STRIP = re.compile(
    "(?:[\U0001F000-\U0001FAFF\U00002600-\U000026FF\U00002700-\U000027BF"
    "\U0001F1E6-\U0001F1FF\U00002B00-\U00002BFF\U0000FE00-\U0000FE0F\U0000200D])+[ \t]?"
)


def _emoji_maps():
    """PUA 센티넬(U+E000+n) 기반 변환 테이블을 코드포인트로 안전하게 구성."""
    S = lambda n: chr(0xE000 + n)
    pre = {
        "🟢": S(1), "🟡": S(2), "🔴": S(3),
        "✅": S(4), "❌": S(5), "⚠️": S(6), "⚠": S(6),
        "⬆️": S(7), "⬆": S(7), "⬇️": S(8), "⬇": S(8),
        "➖": S(9), "⭐": S(10), "☆": S(11),
        "➡️": S(12), "➡": S(12), "🔼": S(7), "🔽": S(8),
    }
    post = {
        S(1): '<span class="sig g">●</span>', S(2): '<span class="sig a">●</span>',
        S(3): '<span class="sig r">●</span>',
        S(4): '<span class="sig g">✓</span>', S(5): '<span class="sig r">✗</span>',
        S(6): '<span class="sig a">⚠</span>',
        S(7): '<span class="sig g">▲</span>', S(8): '<span class="sig r">▼</span>',
        S(9): "—", S(10): '<span class="star">★</span>', S(11): '<span class="star">☆</span>',
        S(12): "→",
    }
    return pre, post


def _emoji_pre(md_text: str) -> str:
    pre, _ = _emoji_maps()
    for emo, sen in pre.items():
        md_text = md_text.replace(emo, sen)
    md_text = _EMOJI_STRIP.sub("", md_text)
    # 헤딩 기호 제거로 생긴 군더더기 공백 정리
    md_text = re.sub(r"(^|\n)(#{1,6})\s+", r"\1\2 ", md_text)
    return md_text


def _emoji_post(html: str) -> str:
    _, post = _emoji_maps()
    for sen, rep in post.items():
        html = html.replace(sen, rep)
    return html


# ──────────────────────────────────────────────────────────────────────────
# 마크다운 → HTML (pandoc)
# ──────────────────────────────────────────────────────────────────────────
def _md_to_html(md_text: str) -> str:
    """GFM 마크다운을 HTML 조각으로 변환(pandoc). 표·취소선·코드블록 지원.

    변환 전 의미 이모지를 센티넬로 치환하고 장식 이모지를 제거한 뒤, 변환 후
    센티넬을 색상 기하기호 span으로 되돌린다(이모지 폰트 불필요)."""
    md_text = _emoji_pre(md_text)
    try:
        out = subprocess.run(
            ["pandoc", "-f", "gfm", "-t", "html", "--wrap=none"],
            input=md_text, capture_output=True, text=True, check=True,
        )
    except FileNotFoundError:
        raise RuntimeError("pandoc 미설치 — 본문 변환 불가 (apt-get install pandoc)")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"pandoc 변환 실패: {e.stderr[:300]}")
    return _emoji_post(out.stdout)


def _strip_title_h1(html: str) -> str:
    """본문 첫 H1(보고서 제목)은 표지로 대체되므로 제거."""
    return re.sub(r"^\s*<h1[^>]*>.*?</h1>", "", html, count=1, flags=re.S)


def _wrap_exhibits(html: str) -> str:
    """본문의 각 <table>을 Exhibit 번호 + Source 푸터를 단 figure로 감싼다(IB 관습)."""
    counter = {"n": 0}

    def repl(m):
        counter["n"] += 1
        n = counter["n"]
        return (
            f'<figure class="exhibit">'
            f'<figcaption class="exhibit-cap">Exhibit {n}</figcaption>'
            f'{m.group(0)}'
            f'<div class="exhibit-src">자료: AI Investment Committee — invest 분석 도구</div>'
            f'</figure>'
        )

    return re.sub(r"<table>.*?</table>", repl, html, flags=re.S)


# ──────────────────────────────────────────────────────────────────────────
# Risk-Reward 세로축 차트 (인라인 SVG)
# ──────────────────────────────────────────────────────────────────────────
def _num(s) -> float:
    """'$1,100', '+44%', '$900–1,400' 등에서 첫 숫자를 추출."""
    if s is None:
        return None
    m = re.search(r"-?\d[\d,]*\.?\d*", str(s).replace(",", ""))
    return float(m.group(0)) if m else None


def _risk_reward_svg(scenarios: list, current_price) -> str:
    """Bull/Base/Bear 세로 가격축 차트 SVG. MS Risk-Reward 프레임워크 스타일."""
    if not scenarios:
        return ""
    by = {str(s.get("name", "")).lower(): s for s in scenarios}
    bull, base, bear = by.get("bull"), by.get("base"), by.get("bear")
    if not (bull and base and bear):
        return ""

    p_bull, p_base, p_bear = _num(bull.get("price")), _num(base.get("price")), _num(bear.get("price"))
    cur = _num(current_price)
    vals = [v for v in (p_bull, p_base, p_bear, cur) if v is not None]
    if len(vals) < 3:
        return ""
    hi, lo = max(vals), min(vals)
    span = (hi - lo) or 1.0
    pad = span * 0.12
    hi += pad
    lo -= pad
    span = hi - lo

    W, H = 360, 200
    top, bot = 16, 18
    axis_x = 116
    plot_h = H - top - bot

    def y_of(price):
        return top + (hi - price) / span * plot_h

    def fmt(p):
        return f"${p:,.0f}" if p is not None else "—"

    parts = [f'<svg viewBox="0 0 {W} {H}" class="rr-svg" xmlns="http://www.w3.org/2000/svg">']
    # 세로 축
    parts.append(f'<line x1="{axis_x}" y1="{top}" x2="{axis_x}" y2="{H-bot}" class="rr-axis"/>')

    rows = [
        ("Bull", p_bull, bull, "rr-bull"),
        ("Base", p_base, base, "rr-base"),
        ("Bear", p_bear, bear, "rr-bear"),
    ]
    for label, price, sc, cls in rows:
        if price is None:
            continue
        y = y_of(price)
        prob = sc.get("prob", "")
        ret = sc.get("ret", "")
        # 마커 + 가격축 눈금
        parts.append(f'<circle cx="{axis_x}" cy="{y:.1f}" r="5" class="{cls} rr-dot"/>')
        parts.append(f'<line x1="{axis_x}" y1="{y:.1f}" x2="{axis_x+18}" y2="{y:.1f}" class="{cls} rr-tick"/>')
        # 우측: 시나리오명 · 가격 · 수익률 · 확률
        parts.append(
            f'<text x="{axis_x+24}" y="{y-3:.1f}" class="rr-name {cls}">{label} '
            f'<tspan class="rr-price">{fmt(price)}</tspan></text>'
        )
        parts.append(
            f'<text x="{axis_x+24}" y="{y+11:.1f}" class="rr-meta">{ret}  ·  P {prob}</text>'
        )

    # 현재가 기준선
    if cur is not None:
        yc = y_of(cur)
        parts.append(f'<line x1="{axis_x-70}" y1="{yc:.1f}" x2="{W-6}" y2="{yc:.1f}" class="rr-current"/>')
        parts.append(f'<text x="6" y="{yc-4:.1f}" class="rr-cur-lbl">현재가</text>')
        parts.append(f'<text x="6" y="{yc+11:.1f}" class="rr-cur-val">{fmt(cur)}</text>')

    parts.append("</svg>")
    return "".join(parts)


# ──────────────────────────────────────────────────────────────────────────
# HTML 템플릿 (Jinja2) — 하이브리드 증권사 테마
# ──────────────────────────────────────────────────────────────────────────
_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><title>{{ company }} ({{ ticker }})</title>
<style>
  :root{
    --navy:#16324f; --navy2:#21466b; --ink:#1a1a1a; --gray:#5b6573; --line:#d7dde3;
    --bg-soft:#f4f6f8; --pos:#137333; --neg:#c5221f; --amber:#b06000; --chip:#eef2f6;
  }
  *{box-sizing:border-box;}
  @page{ size:A4; margin:14mm 12mm 16mm 12mm; }
  html,body{ margin:0; padding:0; }
  body{ font-family:'Noto Sans CJK KR','Noto Sans',sans-serif; color:var(--ink);
        font-size:9.4pt; line-height:1.5; -webkit-print-color-adjust:exact; }
  h1,h2,h3,h4{ font-family:'Noto Sans CJK KR',sans-serif; color:var(--navy); line-height:1.25; }
  h2{ font-size:13pt; border-bottom:2px solid var(--navy); padding-bottom:3px; margin:18px 0 9px; }
  h3{ font-size:11pt; margin:13px 0 6px; color:var(--navy2); }
  h4{ font-size:9.8pt; margin:10px 0 4px; color:var(--ink); }
  h5,h6{ font-size:9.4pt; color:var(--navy2); margin:9px 0 4px; }
  /* 소제목이 페이지 마지막 줄에 고아로 남지 않도록 — 다음 내용과 함께 다음 페이지로 */
  h2,h3,h4,h5,h6{ break-after:avoid; page-break-after:avoid; break-inside:avoid; page-break-inside:avoid; }
  /* 헤딩 직후 첫 블록도 함께 묶기(일부 케이스 보강) */
  h2+*,h3+*,h4+*,h5+*,h6+*{ break-before:avoid; page-break-before:avoid; }
  /* 헤딩+도입 문장(예 "리스크 지표:")이 본문 표보다 먼저 끊겨 페이지 끝에 고아로 남는 것 방지 —
     소제목→도입문→첫 표/코드블록을 한 덩어리로 묶어 함께 다음 페이지로 이동 */
  :is(h2,h3,h4,h5,h6)+p{ break-after:avoid; page-break-after:avoid; }
  :is(p,ul,ol,blockquote,h2,h3,h4,h5,h6)+figure.exhibit,
  :is(p,ul,ol,blockquote,h2,h3,h4,h5,h6)+pre{ break-before:avoid; page-break-before:avoid; }
  p{ margin:5px 0; }
  a{ color:var(--navy2); text-decoration:none; }
  hr{ border:0; border-top:1px solid var(--line); margin:12px 0; }
  strong{ color:#0c1d2e; }
  blockquote{ margin:7px 0; padding:6px 11px; background:var(--bg-soft);
              border-left:3px solid var(--navy); color:#33414f; font-size:9pt; }
  ul,ol{ margin:5px 0 5px 0; padding-left:18px; }
  li{ margin:2px 0; }
  code{ font-family:'Noto Sans Mono CJK KR',monospace; font-size:8.6pt; }
  pre{ font-family:'Noto Sans Mono CJK KR',monospace; font-size:7.7pt; line-height:1.32;
       background:#0f2233; color:#e6edf3; padding:9px 11px; border-radius:4px;
       overflow:hidden; white-space:pre-wrap; word-break:break-word; }
  pre code{ color:inherit; font-size:inherit; }

  /* 표 / Exhibit */
  figure.exhibit{ margin:11px 0; page-break-inside:avoid; }
  figcaption.exhibit-cap{ font-size:8pt; font-weight:700; color:var(--navy);
       letter-spacing:.3px; margin-bottom:3px; text-transform:uppercase; }
  .exhibit-src{ font-size:7pt; color:var(--gray); margin-top:2px; text-align:right; }
  table{ width:100%; border-collapse:collapse; font-size:8.5pt; }
  thead th{ background:var(--navy); color:#fff; font-weight:600; text-align:left;
            padding:4px 7px; border:1px solid var(--navy); }
  tbody td{ padding:3.5px 7px; border:1px solid var(--line); vertical-align:top; }
  tbody tr:nth-child(even){ background:var(--bg-soft); }

  /* 판정/방향 기호(이모지 치환 결과) */
  .sig{ font-weight:700; }
  .sig.g{ color:var(--pos); } .sig.a{ color:var(--amber); } .sig.r{ color:var(--neg); }
  .star{ color:#e8a200; }
  pre .sig.g{ color:#3fb950; } pre .sig.a{ color:#e3b341; } pre .sig.r{ color:#ff7b72; }

  /* ── 표지(1페이지) ── */
  .cover{ page-break-after:always; }
  .masthead{ font-size:7.5pt; color:var(--gray); display:flex; justify-content:space-between;
             border-bottom:1px solid var(--line); padding-bottom:4px; margin-bottom:9px; }
  .head-band{ display:flex; justify-content:space-between; align-items:flex-start; gap:14px;
              border-left:5px solid var(--navy); padding:2px 0 2px 11px; }
  .head-l .company{ font-size:20pt; font-weight:800; color:var(--navy); line-height:1.1; }
  .head-l .ticker{ font-size:11pt; color:var(--gray); font-weight:600; margin-left:4px; }
  .head-l .headline{ font-size:12.5pt; font-weight:700; color:var(--ink); margin-top:7px;
                     font-style:italic; }
  .head-l .rtype{ display:inline-block; margin-top:8px; font-size:7.6pt; font-weight:700;
                  background:var(--chip); color:var(--navy2); padding:2px 8px; border-radius:10px; }
  .rating-chip{ flex:0 0 auto; min-width:150px; border:1px solid var(--line); border-radius:6px;
                overflow:hidden; }
  .rating-chip .rc-act{ background:var(--navy); color:#fff; text-align:center;
        font-size:14pt; font-weight:800; padding:7px 6px; }
  .rating-chip .rc-act small{ display:block; font-size:7.5pt; font-weight:500; opacity:.85; }
  .rating-chip .rc-row{ display:flex; justify-content:space-between; padding:3px 9px;
        font-size:8.6pt; border-top:1px solid var(--line); }
  .rating-chip .rc-row b{ color:var(--navy); }
  .rc-up-pos{ color:var(--pos)!important; font-weight:700; }
  .rc-up-neg{ color:var(--neg)!important; font-weight:700; }

  .cover-body{ display:flex; gap:14px; margin-top:13px; }
  .cover-main{ flex:1 1 0; min-width:0; }
  .cover-side{ flex:0 0 200px; }

  .panel{ border:1px solid var(--line); border-radius:5px; margin-bottom:11px; overflow:hidden; }
  .panel-h{ background:var(--navy); color:#fff; font-size:8.4pt; font-weight:700;
            padding:4px 9px; letter-spacing:.3px; }
  .panel-b{ padding:8px 10px; }

  .takeaways{ margin:0; padding-left:17px; }
  .takeaways li{ margin:4px 0; font-size:9pt; }

  .kv{ width:100%; font-size:8.2pt; }
  .kv td{ padding:3px 4px; border-bottom:1px solid var(--line); }
  .kv td:first-child{ color:var(--gray); }
  .kv td:last-child{ text-align:right; font-weight:600; }
  .kv tr:last-child td{ border-bottom:0; }

  .conv-stars{ color:#e8a200; font-size:11pt; letter-spacing:1px; }
  .conv-wrap{ text-align:center; padding:3px 0; }
  .conv-wrap .cl{ font-size:8pt; color:var(--gray); }

  .rr-wrap{ display:flex; gap:8px; align-items:center; }
  .rr-svg{ width:100%; height:auto; }
  .rr-axis{ stroke:var(--gray); stroke-width:1.2; }
  .rr-dot.rr-bull{ fill:var(--pos); } .rr-tick.rr-bull{ stroke:var(--pos); stroke-width:2; }
  .rr-dot.rr-base{ fill:var(--navy2); } .rr-tick.rr-base{ stroke:var(--navy2); stroke-width:2; }
  .rr-dot.rr-bear{ fill:var(--neg); } .rr-tick.rr-bear{ stroke:var(--neg); stroke-width:2; }
  .rr-name{ font-size:8.4pt; font-weight:700; }
  .rr-name.rr-bull{ fill:var(--pos); } .rr-name.rr-base{ fill:var(--navy2); } .rr-name.rr-bear{ fill:var(--neg); }
  .rr-name .rr-price{ font-weight:800; }
  .rr-meta{ font-size:7.2pt; fill:var(--gray); }
  .rr-current{ stroke:#444; stroke-width:1; stroke-dasharray:3 2; }
  .rr-cur-lbl{ font-size:7pt; fill:#444; }
  .rr-cur-val{ font-size:8pt; fill:#444; font-weight:700; }
  .rr-foot{ font-size:7.6pt; color:var(--gray); margin-top:5px; }
  .wt{ font-weight:700; color:var(--navy); }

  .pr-table{ width:100%; font-size:7.8pt; border-collapse:collapse; }
  .pr-table th,.pr-table td{ padding:2.5px 4px; border-bottom:1px solid var(--line); text-align:right; }
  .pr-table th:first-child,.pr-table td:first-child{ text-align:left; color:var(--gray); }
  .pr-table thead th{ color:var(--navy); }

  /* 본문 */
  .body-wrap h2:first-child{ margin-top:4px; }
  .body-wrap{ font-size:9.2pt; }

  /* 면책 */
  .disclosures{ margin-top:20px; border:1px solid var(--line); border-radius:5px;
                background:var(--bg-soft); padding:11px 13px; page-break-inside:avoid; }
  .disclosures h3{ margin-top:0; font-size:9.5pt; }
  .disclosures p, .disclosures li{ font-size:7.8pt; color:#44505c; line-height:1.45; }
</style></head>
<body>

<!-- ───────── 표지 ───────── -->
<section class="cover">
  <div class="masthead">
    <span>{{ report_type }}{% if mode_label %} · {{ mode_label }}{% endif %}</span>
    <span>{{ date }} · AI Investment Committee</span>
  </div>

  <div class="head-band">
    <div class="head-l">
      <div><span class="company">{{ company }}</span><span class="ticker">({{ ticker }}{% if exchange %}, {{ exchange }}{% endif %})</span></div>
      {% if headline %}<div class="headline">“{{ headline }}”</div>{% endif %}
      <span class="rtype">{{ report_type }}</span>
    </div>
    {% if rating %}
    <div class="rating-chip">
      <div class="rc-act">{{ rating.action or "—" }}{% if rating.action_en %}<small>{{ rating.action_en }}{% if rating.stance %} · {{ rating.stance }}{% endif %}</small>{% endif %}</div>
      {% if rating.target_price %}<div class="rc-row"><span>목표주가</span><b>{{ rating.target_price }}</b></div>{% endif %}
      {% if rating.current_price %}<div class="rc-row"><span>현재가</span><b>{{ rating.current_price }}</b></div>{% endif %}
      {% if rating.upside_pct %}<div class="rc-row"><span>상승여력</span><span class="{{ 'rc-up-neg' if '-' in rating.upside_pct else 'rc-up-pos' }}">{{ rating.upside_pct }}</span></div>{% endif %}
      {% if rating.position_pct %}<div class="rc-row"><span>권고비중</span><b>{{ rating.position_pct }}</b></div>{% endif %}
    </div>
    {% endif %}
  </div>

  <div class="cover-body">
    <div class="cover-main">
      {% if takeaways %}
      <div class="panel">
        <div class="panel-h">KEY TAKEAWAYS — 핵심 요약</div>
        <div class="panel-b"><ul class="takeaways">
          {% for t in takeaways %}<li>{{ t }}</li>{% endfor %}
        </ul></div>
      </div>
      {% endif %}

      {% if rr_svg %}
      <div class="panel">
        <div class="panel-h">RISK-REWARD — 시나리오 가격 분포</div>
        <div class="panel-b">
          {{ rr_svg|safe }}
          {% if weighted %}<div class="rr-foot">확률가중 적정가 <span class="wt">{{ weighted.price }}</span>{% if weighted.ret %} (<span class="wt">{{ weighted.ret }}</span>){% endif %}</div>{% endif %}
        </div>
      </div>
      {% if scenarios %}
      <table class="scn"><thead><tr><th>시나리오</th><th>목표가</th><th>수익률</th><th>확률</th><th>핵심 가정</th></tr></thead><tbody>
        {% for s in scenarios %}<tr><td><b>{{ s.name }}</b></td><td>{{ s.price }}</td><td>{{ s.ret }}</td><td>{{ s.prob }}</td><td style="font-size:7.8pt">{{ s.assumption }}</td></tr>{% endfor %}
      </tbody></table>
      {% endif %}
      {% endif %}
    </div>

    <div class="cover-side">
      {% if rating and rating.conviction_stars is not none %}
      <div class="panel">
        <div class="panel-h">확신도 (CONVICTION)</div>
        <div class="panel-b conv-wrap">
          <div class="conv-stars">{{ "★" * rating.conviction_stars }}{{ "☆" * (5 - rating.conviction_stars) }}</div>
          <div class="cl">{{ rating.conviction_label or "" }}</div>
        </div>
      </div>
      {% endif %}

      {% if key_data %}
      <div class="panel">
        <div class="panel-h">KEY DATA</div>
        <div class="panel-b"><table class="kv"><tbody>
          {% for kd in key_data %}<tr><td>{{ kd.label }}</td><td>{{ kd.value }}</td></tr>{% endfor %}
        </tbody></table></div>
      </div>
      {% endif %}

      {% if price_return %}
      <div class="panel">
        <div class="panel-h">주가 수익률</div>
        <div class="panel-b"><table class="pr-table"><thead><tr><th>기간</th><th>절대</th><th>상대</th></tr></thead><tbody>
          {% for r in price_return %}<tr><td>{{ r.period }}</td><td>{{ r.abs }}</td><td>{{ r.rel }}</td></tr>{% endfor %}
        </tbody></table></div>
      </div>
      {% endif %}
    </div>
  </div>
</section>

<!-- ───────── 본문 ───────── -->
<section class="body-wrap">
{{ body|safe }}
</section>

<!-- ───────── 면책 ───────── -->
<section class="disclosures">
  <h3>Disclosures &amp; Disclaimer — 투자등급·면책</h3>
  <p><b>[투자의견 분류]</b> 본 보고서의 투자의견은 <b>매수 / 관망 / 매도</b> 3단계와 별도의 <b>확신도(<span class="star">★</span> 1–5)</b>·<b>권고비중(%)</b>으로 구성됩니다. 보유자에게는 비중 유지/확대(피라미딩)/축소를, 신규 투자자에게는 진입가 2-Case(현재가·눌림목)를 함께 제시합니다. mandate 프로파일(default 보수 / megatrend 공격)에 따라 포지션 한도가 달라집니다.</p>
  <p><b>[Compliance Notice]</b> {{ disclaimer }}</p>
</section>

</body></html>
"""


def _default_disclaimer() -> str:
    return ("본 보고서는 AI 에이전트 팀(8+1인 투자위원회)의 분석에 기반한 투자 참고 자료이며, "
            "투자 권유가 아닙니다. 수치는 yfinance 등 공개 데이터에 근거한 추정치로서 오차가 있을 수 "
            "있으며 정확성·완전성을 보장하지 않습니다. 최종 투자 결정과 그 책임은 투자자 본인에게 "
            "있습니다. 무단 전재·복사·배포를 금합니다.")


# ──────────────────────────────────────────────────────────────────────────
# 렌더링
# ──────────────────────────────────────────────────────────────────────────
def _render_html(ticker: str, meta: dict, body_md: str, mode: str) -> str:
    from jinja2 import Environment

    rating = meta.get("rating") or {}
    scenarios = meta.get("scenarios") or []
    body_html = _wrap_exhibits(_strip_title_h1(_md_to_html(body_md)))
    rr_svg = _risk_reward_svg(scenarios, rating.get("current_price"))

    env = Environment(autoescape=False)
    tmpl = env.from_string(_TEMPLATE)
    return tmpl.render(
        ticker=ticker.upper(),
        company=meta.get("company") or ticker.upper(),
        exchange=meta.get("exchange") or "",
        report_type=meta.get("report_type") or ("Company In-depth" if mode == "deep" else "Company Brief"),
        mode_label={"deep": "심층", "brief": "요약"}.get(mode, ""),
        date=meta.get("date") or datetime.now().strftime("%Y-%m-%d"),
        headline=meta.get("headline") or "",
        rating=rating,
        key_data=meta.get("key_data") or [],
        price_return=meta.get("price_return") or [],
        takeaways=meta.get("takeaways") or [],
        scenarios=scenarios,
        weighted=meta.get("weighted") or {},
        rr_svg=rr_svg,
        body=body_html,
        disclaimer=meta.get("disclaimer") or _default_disclaimer(),
    )


def _html_to_pdf(html_path: str, pdf_path: str):
    from playwright.sync_api import sync_playwright

    footer = (
        '<div style="width:100%;font-size:7px;color:#888;padding:0 12mm;'
        'font-family:sans-serif;display:flex;justify-content:space-between;">'
        '<span>AI Investment Committee · 투자 참고 자료 (투자 권유 아님)</span>'
        '<span class="pageNumber"></span>/<span class="totalPages"></span></div>'
    )
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page()
        page.goto("file://" + os.path.abspath(html_path), wait_until="networkidle")
        page.pdf(
            path=pdf_path, format="A4", print_background=True,
            display_header_footer=True,
            header_template="<div></div>",
            footer_template=footer,
            margin={"top": "14mm", "bottom": "16mm", "left": "12mm", "right": "12mm"},
        )
        browser.close()


def build(ticker: str, meta: dict = None, mode: str = "deep", date: str = None) -> dict:
    """histories 디렉토리의 report.md(deep)/summary.md(brief)를 PDF로 렌더한다.

    meta: 표지·사이드바·시나리오용 메타 JSON(dict). None이면 표지가 최소 정보로만 렌더.
    """
    ticker = ticker.upper()
    meta = dict(meta or {})
    dirpath = _resolve_dir(ticker, date)
    if not meta.get("date"):
        m = _DATE_TICKER.match(os.path.basename(dirpath))
        meta["date"] = m.group(1) if m else datetime.now().strftime("%Y-%m-%d")

    src_name = "report.md" if mode == "deep" else "summary.md"
    src_path = os.path.join(dirpath, src_name)
    if not os.path.exists(src_path):
        # report.md 없으면 summary로 폴백
        alt = os.path.join(dirpath, "summary.md")
        if mode == "deep" and os.path.exists(alt):
            src_path, mode = alt, "brief"
        else:
            raise FileNotFoundError(f"{src_name} 없음: {src_path}")

    with open(src_path, encoding="utf-8") as f:
        body_md = f.read()

    html = _render_html(ticker, meta, body_md, mode)
    out_base = "report" if mode == "deep" else "summary"
    html_path = os.path.join(dirpath, f"{out_base}.html")
    pdf_path = os.path.join(dirpath, f"{out_base}.pdf")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    _html_to_pdf(html_path, pdf_path)

    size = os.path.getsize(pdf_path) if os.path.exists(pdf_path) else 0
    return {
        "status": "success",
        "ticker": ticker,
        "mode": mode,
        "source": src_path,
        "html_path": html_path,
        "pdf_path": pdf_path,
        "pdf_bytes": size,
        "dir": dirpath,
    }


def build_from_args(ticker: str, args: list) -> dict:
    """CLI 진입점. --meta <path>|stdin, --mode deep|brief, --date YYYY-MM-DD."""
    def opt(flag):
        if flag in args:
            i = args.index(flag)
            if i + 1 < len(args):
                return args[i + 1]
        return None

    mode = (opt("--mode") or "deep").lower()
    date = opt("--date")
    meta = {}
    meta_path = opt("--meta")
    if meta_path == "-" or ("--meta-stdin" in args):
        meta = json.load(sys.stdin)
    elif meta_path:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    return build(ticker, meta=meta, mode=mode, date=date)
