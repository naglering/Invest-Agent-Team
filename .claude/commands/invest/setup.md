초기 세팅 — mandate 설정과 개인 데이터 파일을 생성합니다.

요청: $ARGUMENTS

---

## 역할

이 시스템의 **개인 투자 데이터는 GitHub에 올라가지 않습니다**(`.gitignore`). 레포에는 골격(구조 + `data/mandates` + `data/histories/EXAMPLE.md`)만 포함됩니다. 이 커맨드는 클론 직후 또는 리셋이 필요할 때 개인 설정·데이터 파일을 생성합니다.

## 실행 절차

### 1단계: mandate 정본 생성

```bash
python3 src/tools/cli.py setup
```

- `data/mandates/default.json`(보수)·`megatrend.json`(공격)을 생성합니다.
- 이미 있으면 `skip` — 기존 설정을 보존합니다.

### 2단계: 개인 데이터 템플릿 생성

```bash
python3 src/tools/cli.py portfolio init
```

- `data/portfolio.md`(보유 종목)·`theses.md`(투자 Thesis)·`positions.md`(포지션 비중) 템플릿을 생성합니다.
- 이미 있으면 `skip`.

### 3단계: 결과 보고 + 다음 단계 안내

- 각 파일이 `create`/`skip` 되었는지 요약합니다.
- 다음 안내:
  - 포트폴리오 구성/매수/매도는 **`/invest:portfolio`** 로 진행하세요.
  - `data/theses.md`(보유 논거)는 직접 편집하거나 종목 분석 후 채웁니다.
  - mandate 값(최대 비중·PER 게이트 등)을 본인 전략에 맞게 수정할 수 있습니다.

## 옵션

- `$ARGUMENTS` 에 `--force` / `재설정` / `리셋` 이 포함되면 기존 파일을 **덮어쓰기**합니다. 이 경우 두 명령에 `--force`를 붙여 실행하되, **실행 전 사용자에게 기존 파일을 덮어쓴다고 경고하고 확인**을 받습니다.

```bash
python3 src/tools/cli.py setup --force
python3 src/tools/cli.py portfolio init --force
```

> ※ 모든 설정은 참고용이며 투자 권유가 아닙니다.
