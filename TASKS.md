# TASKS.md — 매도 처리 + 연도별 배당 Top15 + 현금 입력/추이(대시보드)

## 범위(요약)
1) 포트폴리오 거래에서 **매도(SELL)** 를 지원하여 보유수량/평단/평가/손익 계산이 정확히 되게 한다.
2) 배당 Top 15 위젯에 **연도 선택/연도별 Top 15** 기능을 추가한다.
3) 대시보드에 **현금(Cash)** 을 입력/관리하고, 총자산(매입원금+현금, 평가액+현금)의 **추이**를 표시한다.

전제:
- 로그인/유저 개념 없음.
- 관리자 비번 게이트만 유지.
- 데이터 입력은 CSV import + 필요 시 UI 수동 입력(현금) 허용.

---

# P1. 매도(SELL) 처리 지원

## Task P1-1: CSV 스키마/Importer에서 매도 지원
대상: `holdings_lots`(또는 현재 거래 테이블)
- `side` 컬럼에 BUY/SELL 지원
- CSV에서 "매수/매도", "BUY/SELL", "매도" 등을 normalize:
  - 매수 -> BUY
  - 매도 -> SELL
- 매도는 수량/단가/통화/환율(필요시) 동일하게 입력되며, KRW 환산금액도 계산/저장

Acceptance:
- 매도 행이 import되어 DB에 저장됨.
- 기존 BUY-only 파일도 그대로 import 가능.

## Task P1-2: 포지션 계산 로직에 매도 반영(가중평균법)
현재 포지션 계산을 다음 규칙으로 수정:
- `qty`:
  - qty = ΣBUY - ΣSELL
- `cost_basis_krw`(잔존 원가):
  - BUY: cost += buy_krw
  - SELL: 평균원가 기준으로 비례 차감
    - avg_cost = cost / qty_before_sell
    - cost -= avg_cost * sell_qty
- `avg_buy_price_krw`:
  - qty>0 이면 cost_basis_krw / qty
  - qty=0 이면 0 또는 None
- (선택) `realized_pnl_krw`(실현손익)도 계산:
  - proceeds_krw = sell_qty * sell_price_krw
  - realized += proceeds_krw - (avg_cost * sell_qty)

예외/검증:
- 매도 수량이 보유 수량을 초과하면:
  - (선택1) 에러로 막기
  - (선택2) 경고 + 0 이하 허용(비추천)
- 동일 티커/계좌구분 단위로 계산

Acceptance:
- 매도 후 잔존 수량/평단/원가가 기대대로 감소함.
- 잔존 수량 0이면 평단/원가가 정상 초기화됨.
- (선택) 실현손익이 계산되어 표에 표시 가능.

## Task P1-3: UI 표(보유 종목/대시보드)에서 매도 반영 확인
- 보유 종목 테이블:
  - qty 감소 반영
  - cost_basis_krw 감소 반영
  - (선택) realized_pnl_krw 컬럼 표시 토글
- 종목 상세:
  - 거래 내역(BUY/SELL) 필터/정렬

Acceptance:
- 매도 입력 후 화면이 일관되게 갱신.

---

# P2. 연도별 배당 Top 15

## Task P2-1: 대시보드 Top 15 영역에 “연도 선택” UI 추가
- 기본값: "전체(모든 연도)" 또는 "최근 연도"
- 연도 dropdown:
  - dividend_events에서 존재하는 연도 목록을 자동 생성
- 선택 연도에 따라 Top 15 계산을 다시 수행

Acceptance:
- 연도 선택 시 Top 15 목록이 바뀜.
- "전체" 선택 시 기존 동작 유지.

## Task P2-2: Top 15 계산 로직 확장(연도별/전체)
- 입력:
  - year: int | None
- 로직:
  - year가 있으면 해당 연도만 필터 후 종목별 합계(세전배당/세후배당 중 표시 기준은 기존과 동일)
  - year가 None이면 전체 기간 합계(기존과 동일)
- 표시:
  - 종목명(또는 ticker/name_ko)
  - 합계 배당금(KRW)
  - (옵션) 전년 대비 증감(YoY) 같이 보여주면 유용 (가능하면)

Acceptance:
- Top 15가 정확히 year 기준으로 집계됨.

## Task P2-3: “연도별 Top15 요약 테이블” 옵션(선택)
- 버튼/토글: “연도별로 보기”
- 출력:
  - 연도 x 순위(1~15) 형태 또는
  - 연도별 Top15 리스트를 아래에 확장 표시

Acceptance:
- 사용자가 연도별로 Top15 변화를 한눈에 볼 수 있음.

---

# P3. 대시보드에 ‘현금’ 추가 + 추이(총자산)

## Task P3-1: 현금 입력 방식 결정 및 테이블 추가
권장: 스냅샷 기반(추이를 위해)
- 테이블: `cash_snapshots`
  - id (PK)
  - snapshot_date (date)  # 월말 또는 사용자가 입력한 날짜
  - account_type (ALL/TAXABLE/ISA) (현재는 ALL만 써도 됨)
  - cash_krw (float)
  - note (text)
  - created_at/updated_at

입력 UI:
- 대시보드에 “현금 입력/업데이트” 섹션:
  - 날짜 선택(기본: 오늘)
  - 금액 입력
  - 저장 버튼(해당 날짜가 있으면 update, 없으면 insert)
- (선택) CSV import도 지원(나중에)

Acceptance:
- 현금 값을 날짜별로 저장 가능.
- 동일 날짜 입력 시 update 동작.

## Task P3-2: 총 매입금/평가액에 현금 포함한 지표 추가
현재 대시보드가 보여주는:
- 총 매입금(투입 원금/원가)
- 현재 평가액(주식 평가액)

여기에 아래를 추가:
- 현금(cash_krw)
- 총자산(원가 기준) = 매입원금 + 현금
- 총자산(평가 기준) = 평가액 + 현금

표시 형식:
- KRW 천단위 콤마 + "원"
- 현금 데이터가 없으면:
  - "현금 입력 필요" 안내 + 입력 섹션 강조

Acceptance:
- 현금 입력 후 4개 지표가 함께 갱신되어 표시됨.

## Task P3-3: 추이 차트(현금 포함)
차트 2개 권장:
1) 시계열(월 단위): 
   - 매입원금(또는 cost_basis)
   - 평가액
   - 현금
   - 총자산(평가 기준)
2) (선택) 누적 납입 vs 총자산 비교(이미 납입 스냅샷이 있다면)

데이터 정렬:
- snapshot_date 기준
- 현금이 없는 날짜는 forward-fill(선택) 또는 결측 표시(선택)

Acceptance:
- 현금 스냅샷이 누적되면 차트가 자연스럽게 업데이트.
- 최근 12~24개월 구간 필터(선택) 제공.

---

# 테스트 체크리스트(필수)
- 매도 CSV 1건 추가 후:
  - 보유수량 감소, 잔존 원가 감소, 평가액/손익 변화 확인
- 배당 Top15:
  - 연도 바꿔도 정상 집계
- 현금:
  - 날짜별 2개 입력 → 차트에 반영
  - 현금 포함 총자산 지표가 정확히 계산

---

# 구현 메모
- 금액 계산은 모두 KRW 기준으로 통일(환율 적용은 기존 로직 재사용).
- SQLAlchemy 세션 종료 후 객체 접근 문제(DetachedInstanceError) 방지를 위해:
  - 페이지단에서 필요한 값은 session 내부에서 dict/df로 변환 후 반환.
