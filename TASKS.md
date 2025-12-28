# TASKS.md — 사이드바 메뉴 정리 + Admin 비밀번호 게이트(로그인/유저DB 없이)

## 목표
- Streamlit 좌측 메뉴를 “회원(일반 사용자)” 중심으로 재구성한다.
- 로그인/회원가입/유저 테이블은 **지금 단계에서 구현하지 않는다.**
- 대신 “관리자 메뉴”에 들어갈 때만 **관리자 비밀번호를 요구**하는 방식으로 접근 제어한다.
- 메뉴명/페이지 제목은 **한글**로 통일한다.

현재 페이지 목록:
1) import_csv
2) dividends_table
3) dashboard
4) ticker_master
5) missing_ticker
6) alimtalk_parser
7) held_ticker_trends
8) ticker_search
9) dart_single_fetch
10) portfolio_imports

---

## P0. 메뉴 정보구조(IA) 확정

### Task P0-1: 최종 메뉴 그룹/라벨(한글) 정의
일반 사용자(기본):
- **대시보드**
- **포트폴리오 가져오기** (portfolio_imports)
- **배당 내역 가져오기** (import_csv)
- **보유 종목 배당 추이** (held_ticker_trends)
- **종목 검색** (ticker_search)
- **알림톡 파서** (alimtalk_parser)

관리자(게이트 필요):
- **[관리자] 배당 원장 테이블** (dividends_table)
- **[관리자] 종목 마스터 관리** (ticker_master)
- **[관리자] 미등록 티커 확인** (missing_ticker)
- **[관리자] DART 단건 조회(디버그)** (dart_single_fetch)

산출물:
- `docs/menu_structure.md` (간단한 문서: 메뉴 구성/매핑/설명)

Acceptance:
- 위 구성이 docs에 정리되어 있고, 기존 페이지가 모두 어디로 가는지 매핑됨.

---

## P1. Admin 비밀번호 게이트(로그인 없이)

### Task P1-1: 관리자 접근 제어 유틸 추가
`core/admin_gate.py` 생성:

기능:
- `is_admin_unlocked() -> bool`
- `require_admin()` : 관리자 비밀번호 입력 UI(한 번만) + 성공 시 session_state에 플래그 저장
- `lock_admin()` : 관리자 잠금(세션 플래그 해제)
- 비밀번호는 코드에 하드코딩하지 말고 `st.secrets["ADMIN_PASSWORD"]` 또는 환경변수로 읽기
- 실패 시: 경고 메시지 + `st.stop()`

Acceptance:
- 관리자 페이지에 들어가면 비밀번호 입력이 뜨고, 맞으면 페이지가 열림.
- 새로고침/재접속 시(세션이 날아가면) 다시 요구할 수 있음(OK).
- 일반 메뉴에는 영향 없음.

### Task P1-2: 모든 관리자 페이지 상단에 게이트 적용
다음 페이지들 맨 위에 `require_admin()` 호출 추가:
- dividends_table
- ticker_master
- missing_ticker
- dart_single_fetch

Acceptance:
- 비밀번호 없이 관리자 페이지 접근 불가.
- 비밀번호 입력 후 정상 표시.

---

## P2. 페이지 파일명/정렬/한글 타이틀 정리

### Task P2-1: 페이지 파일명 변경(사이드바 정렬)
Streamlit은 파일명(접두 숫자)로 정렬되므로 아래처럼 변경한다.

일반 사용자:
- `pages/1_대시보드.py` (기존 dashboard)
- `pages/2_포트폴리오_가져오기.py` (기존 portfolio_imports)
- `pages/3_배당_내역_가져오기.py` (기존 import_csv)
- `pages/4_보유_종목_배당_추이.py` (기존 held_ticker_trends)
- `pages/5_종목_검색.py` (기존 ticker_search)
- `pages/6_알림톡_파서.py` (기존 alimtalk_parser)

관리자:
- `pages/90_관리자_배당_원장_테이블.py` (기존 dividends_table)
- `pages/91_관리자_종목_마스터_관리.py` (기존 ticker_master)
- `pages/92_관리자_미등록_티커_확인.py` (기존 missing_ticker)
- `pages/93_관리자_DART_단건_조회.py` (기존 dart_single_fetch)

Acceptance:
- 사이드바 메뉴가 위 순서대로 표시됨.
- 관리자 메뉴는 맨 아래에 모임.

### Task P2-2: 각 페이지 타이틀/설명 한글 통일
각 페이지에서 `st.title()` / `st.caption()`을 한글로 정리한다.
예:
- 대시보드: “대시보드”
- 배당 내역 가져오기: “배당 내역 가져오기(CSV)”
- 포트폴리오 가져오기: “포트폴리오 가져오기”
- 관리자 페이지: “관리자: …”

Acceptance:
- 페이지 제목이 파일명/메뉴명과 일치.
- 혼합된 영문/스네이크케이스 제목 제거.

---

## P3. UX: 관리자 잠금/해제 버튼(선택)

### Task P3-1: 사이드바에 “관리자 잠금/해제” 섹션 추가
- 일반 사용자 메뉴 하단에:
  - “관리자 잠금 해제” 버튼(누르면 require_admin 흐름)
  - 관리자 해제된 상태면 “관리자 잠금” 버튼 표시
- 단, “관리자 메뉴”를 누르지 않아도 미리 풀 수 있게 제공

Acceptance:
- 관리자가 편하게 토글 가능.
- 일반 사용자는 버튼 눌러도 비밀번호 없으면 풀리지 않음.

---

## 제외(이번 범위에서 하지 않음)
- 로그인/회원가입
- user_id/portfolio_id 등 멀티유저 DB 스키마 변경
- 권한(Role) 테이블/세션 영구 저장

---

## 구현 메모
- 비밀번호는 `st.secrets`를 우선 사용:
  - `.streamlit/secrets.toml`에 `ADMIN_PASSWORD="..."` 설정
- 게이트 상태 저장:
  - `st.session_state["admin_unlocked"] = True/False`
- 관리자 페이지는 “숨기기”보다는 “접근 시 비밀번호 요구”로 충분.