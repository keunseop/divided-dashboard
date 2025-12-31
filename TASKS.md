# TASK.md — KIS OpenAPI 국내/해외 시세: open-trading-api/examples_llm 참고하여 구현

## 목표
- Streamlit 종목 검색 화면에서 국내/해외 “현재가” 및 “5년 가격 차트(일/주/월)” 표시
- 데이터 소스: 한국투자증권(KIS) OpenAPI
- 구현 시 반드시 한국투자증권 공식 GitHub 샘플을 기준으로 TR_ID/파라미터/도메인(실전/모의)을 맞춘다.

공식 참고자료:
- koreainvestment/open-trading-api 저장소의 examples_llm 폴더(기능별 chk_*.py 샘플) :contentReference[oaicite:1]{index=1}

---

## P0. 샘플 레포 받아서 “정답 스펙” 확인

### Task P0-1: 레포 클론 및 샘플 동작 확인
1) 로컬에서:
   - `git clone https://github.com/koreainvestment/open-trading-api.git`
2) 아래 폴더를 우선 확인한다:
   - `open-trading-api/examples_llm/domestic_stock/inquire_price/chk_inquire_price.py` (국내 현재가 예제) :contentReference[oaicite:2]{index=2}
   - 해외 현재가/기간별 시세에 해당하는 examples_llm 하위 폴더(해외 stock 관련) — 동일한 chk_*.py 구조를 따른다. :contentReference[oaicite:3]{index=3}
3) 샘플 코드에서 다음을 확인하여 우리 프로젝트에 그대로 반영한다:
   - 실전/모의 도메인
   - access_token 발급 URL 및 payload
   - API 호출 시 필요한 헤더(appkey/appsecret/Authorization/tr_id 등)
   - 해외의 경우 시장 코드(EXCD 등)와 티커 파라미터명

Acceptance:
- 샘플 코드(국내 현재가 chk_*.py)는 단독 실행 시 응답이 정상.
- 해외도 샘플 중 1개는 단독 실행 확인.

---

## P1. 우리 프로젝트용 KIS 모듈 설계

### Task P1-1: secrets 설정 키 정의
`.streamlit/secrets.toml`에 아래 키 사용:
- KIS_APP_KEY
- KIS_APP_SECRET
- KIS_ENV ("prod" or "paper")

Acceptance:
- 앱에서 st.secrets로 로드 가능.

### Task P1-2: KIS 인증 모듈
파일: `core/kis/auth.py`

구현:
- `get_access_token()`:
  - 샘플 레포의 인증 로직을 참고하여 구현
  - 토큰을 로컬 파일(예: `var/kis_token.json`)에 저장해 재사용
  - 만료 시 재발급

Acceptance:
- Streamlit rerun에도 토큰 재발급 없이 재사용(만료 전).

### Task P1-3: KIS REST 클라이언트
파일: `core/kis/client.py`

구현:
- `request(method, path, *, params=None, json=None, headers=None)`:
  - base_url은 env(prod/paper)에 따라 샘플 기준 도메인 사용
  - 필수 헤더(appkey/appsecret/Authorization) 공통 처리
  - tr_id는 호출 함수별로 주입(샘플 그대로)

Acceptance:
- 국내 현재가 1회 호출 성공.

---

## P2. 국내/해외 “현재가” 함수 구현(샘플 우선)

### Task P2-1: 국내 현재가
파일: `core/kis/domestic_quotes.py`
- `fetch_domestic_now(symbol_6: str) -> NormalizedQuote`
  - examples_llm의 국내 현재가 샘플(chk_inquire_price.py)을 그대로 참고하여
    - endpoint
    - params
    - tr_id
    를 정확히 맞춘다. :contentReference[oaicite:4]{index=4}
  - normalize 필드(화면 표시용):
    - last, change, change_rate, volume, open/high/low(가능 시)

Acceptance:
- 005930 같은 종목으로 정상 값 반환.

### Task P2-2: 해외 현재가
파일: `core/kis/overseas_quotes.py`
- `fetch_overseas_now(market: str, ticker: str) -> NormalizedQuote`
  - examples_llm의 해외 현재가/체결가 샘플을 찾아 동일하게 구현
  - market 코드/파라미터명/헤더(tr_id)는 샘플 그대로

Acceptance:
- 예: NASD + AAPL(or MMM) 조회 성공.

---

## P3. 5년 가격 차트(기간별 시세)

### Task P3-1: 국내 기간별 시세(5년)
파일: `core/kis/domestic_quotes.py`
- `fetch_domestic_history(symbol_6, start, end, period="D") -> DataFrame`
  - 국내 기간별 시세 API는 문서가 존재하며, 샘플 레포 구조에 맞춰 구현 :contentReference[oaicite:5]{index=5}
  - 5년 일봉이 한번에 제한될 수 있으니:
    - 기본 표시: 주봉("W") 또는 월봉("M") 우선
    - 일봉("D") 선택 시 구간 분할 호출 후 concat

Acceptance:
- 차트 데이터 생성 후 Streamlit line chart로 표시 가능.

### Task P3-2: 해외 기간별 시세(5년)
파일: `core/kis/overseas_quotes.py`
- `fetch_overseas_history(market, ticker, start, end, period="D") -> DataFrame`
  - examples_llm의 해외 기간별 시세 샘플을 기반으로 구현
  - 동일하게 구간 분할/집계 옵션 제공

Acceptance:
- 해외 티커 1개 이상 5년 차트 표시 성공.

---

## P4. Streamlit “종목 검색” 화면 연동

### Task P4-1: UI 추가(현재가 카드 + 차트)
- 입력값이 6자리 숫자면 국내로 간주
- 아니면 해외:
  - market 드롭다운 제공(NASD/NYSE/AMEX 등, 샘플에서 쓰는 코드로)
- 현재가:
  - st.cache_data(ttl=30~60) 적용
- 차트(5년):
  - st.cache_data(ttl=6~24h) 적용
  - 일/주/월 토글 제공(기본 주봉)

Acceptance:
- 국내/해외 모두: 현재가 + 5년 차트가 동일 화면에 표시.

---

## 구현 원칙(중요)
- TR_ID/파라미터/도메인은 반드시 open-trading-api 샘플(examples_llm)을 “단일 진실 소스”로 삼는다. :contentReference[oaicite:6]{index=6}
- 샘플이 동작하는 입력을 최소 1개(국내/해외 각각) 고정 테스트 케이스로 만들어 regression test로 유지한다.
