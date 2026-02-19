# Invest Analyzer

yfinance 기반 주식 종합 분석 도구. 재무, 기술적, 뉴스 분석을 통합하여 JSON으로 출력합니다.

## 설치

```bash
pip install -r requirements.txt
```

## 사용법

```bash
python src/main.py <TICKER>
```

```bash
# 미국 주식
python src/main.py AAPL

# 한국 주식
python src/main.py 005930.KS
```

## 분석 항목

| 모듈 | 파일 | 내용 |
|------|------|------|
| 재무 분석 | `src/fundamental.py` | 수익성, 성장성, 재무 건전성, 현금흐름, 밸류에이션 |
| 기술적 분석 | `src/technical.py` | RSI, MACD, 볼린저 밴드, 이동평균선 |
| 뉴스 분석 | `src/news.py` | 최근 14일간 관련 뉴스 수집 |

## Claude Code 연동

`/invest:analyze <TICKER>` 명령어로 한국어 종합 분석 보고서를 생성할 수 있습니다.
