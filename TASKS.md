# TASKS.md — DART 배당 DB화 + Write-through 캐시 + 수동 Prefetch(관리자, 진행률/취소/재개)

## 목표
- DART DPS 데이터를 DB에 영속 캐시로 저장.
- 조회 시 DB 우선 + 누락분만 DART 호출(write-through).
- 자동 스케줄 없이, **관리자 페이지에서 수동 Prefetch** 수행.
- Prefetch 실행 중:
  - 진행률 표시
  - 중간 취소
  - 다음 실행 시 “이어서(재개)” 가능

---

## P0. DB 스키마/모델

### Task P0-1: `dividend_dps_cache` 테이블/모델 (**완료**)
(기존 Task 유지)
- Unique: (ticker, fiscal_year, reprt_code)
- 저장: dps_cash, raw_payload, fetched_at/updated_at, parser_version, etc.

Acceptance:
- DB에 저장/조회 가능. ✅

### Task P0-2: Prefetch 작업 상태 테이블 `prefetch_jobs` (**완료**)
새 모델 추가 (재개/취소를 위해 필요)

Table: `prefetch_jobs`
- `job_id` (PK, uuid 문자열 추천)
- `created_at` (datetime)
- `updated_at` (datetime)
- `status` (String: "RUNNING"|"CANCELLED"|"DONE"|"FAILED")
- `job_name` (String, nullable)  # 사용자 입력(예: "KR 대형주 2015-2025")
- `tickers_json` (Text)          # 작업 대상 ticker 목록
- `start_year` (int)
- `end_year` (int)
- `reprt_code` (String(5))
- `force_refresh` (bool)
- `cursor_index` (int)           # 현재 ticker 인덱스(0..n-1)
- `cursor_year` (int)            # 현재 처리 중 연도
- `processed_count` (int)
- `success_count` (int)
- `skip_count` (int)             # 013
- `fail_count` (int)
- `last_error` (Text, nullable)

Acceptance:
- job 생성/업데이트/조회 가능. ✅
- job을 저장하고 재개할 수 있는 최소 정보 포함.

---

## P1. Service Layer — Write-through + Prefetch Runner

### Task P1-1: `get_dps_series()` (write-through) (**완료**)
(기존 Task 유지)
- DB에서 조회 → 누락 연도만 DART 호출 → upsert.

Acceptance:
- 동일 ticker 재조회 시 DART 재호출 최소화. ✅

### Task P1-2: Prefetch 실행기(중단/재개 지원) (**완료**)
`core/prefetch_runner.py` 생성

필수 함수:
1) `create_job(tickers, start_year, end_year, reprt_code, force_refresh, job_name) -> job_id`
2) `load_job(job_id) -> job`
3) `request_cancel(job_id)`:
   - job status를 "CANCELLED_REQUESTED" 또는 session flag 기반으로 처리(선택)
4) `run_job_step(job_id, step_limit=1) -> job`
   - job의 cursor 위치부터 step_limit 만큼만 처리하고 저장
   - UI에서 반복 호출(루프)하여 진행률 업데이트 가능하도록 “한 스텝 실행” 방식으로 설계
5) `resume_job(job_id)`:
   - status가 CANCELLED/RUNNING이 아니면 RUNNING으로 바꾸고 실행 재개

실행 규칙:
- 처리 단위: (ticker, year)
- 각 step에서:
  - 취소 요청 체크 → 취소면 status="CANCELLED" 저장 후 return
  - 캐시 존재 + force_refresh=False면 스킵 처리 가능(옵션)
  - DART 호출
    - 013: skip_count++
    - 성공: success_count++
    - 실패: fail_count++ + last_error 저장(단, 전체 중단 vs continue는 옵션)
  - cursor_year 증가 → end_year 넘으면 다음 ticker로 cursor_index 증가, cursor_year = start_year
- DONE 조건: cursor_index == len(tickers)

Acceptance:
- 중간에 job을 멈추고(cursor 저장), 다시 실행하면 이어서 진행됨. ✅
- step_limit 기반으로 UI 진행률 갱신 가능.

---

## P2. UI — 관리자 수동 Prefetch(진행률/취소/재개)

### Task P2-1: 관리자 페이지 `관리자_DART_배당_미리채우기` 구현 (**완료**)
파일 예: `pages/94_관리자_DART_배당_미리채우기.py`
(관리자 비밀번호 게이트 적용)

UI 구성:
1) 입력 섹션
- tickers 입력(멀티라인/콤마/공백 지원)
- 또는 자동 선택:
  - ticker_master에서
  - dividend_events에서(보유/등장 티커)
- year range (start_year/end_year)
- reprt_code (default 11011)
- force_refresh 체크박스
- job_name 입력(optional)

2) “작업 생성” 버튼
- create_job 호출 → job_id 생성
- session_state에 `active_job_id` 저장

3) 진행 섹션(작업이 있을 때)
- 진행률(progress bar):
  - total_steps = len(tickers) * (end_year - start_year + 1)
  - done_steps = processed_count
  - progress = done_steps / total_steps
- 현재 처리 중 표시:
  - 현재 ticker, year
  - success/skip/fail 카운트
  - 최근 에러(last_error) 있으면 표시
- 버튼:
  - “계속 실행(▶)” (RUNNING 시작/재개)
  - “일시 중지(⏸)” (CANCELLED 또는 PAUSED로 상태 변경)
  - “취소(⛔)” (CANCELLED 상태)
  - “처음부터 다시(🔄)” (새 job 생성 유도; 기존 job은 DONE/CANCELLED로 유지)

진행 갱신 방식(중요):
- Streamlit은 단일 실행 흐름이므로, “계속 실행”을 누르면:
  - while-loop로 무한 돌리지 말고,
  - `run_job_step(job_id, step_limit=k)` 호출 후 `st.rerun()`을 반복하는 방식 사용
  - 예: 한 rerun 당 k=5~20 step 처리(너무 크면 UI 멈춤)

Acceptance:
- progress bar가 실시간으로 증가. ✅
- 취소/일시정지 버튼이 즉시 반영.
- 재개 시 이전 cursor 위치부터 다시 시작.

### Task P2-2: “나중에 이어서” UX (**완료**)
- 페이지 상단에 최근 job 목록 표시(최근 10개)
  - job_name, created_at, status, progress%
  - “재개” 버튼(해당 job_id를 active_job_id로 선택)
- DONE/CANCELLED도 목록에 남겨서 히스토리 확인 가능

Acceptance:
- 새로고침/앱 재시작 후에도(세션이 날아가도) DB에 저장된 job을 선택하여 재개 가능. ✅

---

## P3. 안정성/성능/품질

### Task P3-1: 캐시 존재 시 스킵 정책 (**완료**)
Prefetch에서 성능 최적화:
- force_refresh=False이면 DB에 이미 값이 있는 (ticker,year)은 호출하지 않고 스킵
- 단, 최근 1~2개 연도는 옵션으로 “항상 재검증” 토글 가능(선택)

Acceptance:
- 이미 채워진 구간은 매우 빠르게 완료. ✅

### Task P3-2: 네트워크 보호(재시도/백오프) (**완료**)
- 실패 시 1~2회 재시도(간단)
- 연속 실패가 많으면 sleep(예: 0.2~0.5s) 옵션
- DART rate limit을 고려해 과도한 병렬 처리 금지

Acceptance:
- 일시적 네트워크 실패에 견고. ✅

### Task P3-3: 파서 버전/원본 저장 (**완료**)
- `parser_version` 고정값 저장 (예: "v1")
- `raw_payload`에 DART 응답 일부 저장(크기 제한 가능)

Acceptance:
- 나중에 파서 개선 시 force_refresh로 재생성 가능. ✅

---

## 구현 메모(중요)
- Streamlit에서 “취소”는 즉시 프로세스를 kill할 수 없으니,
  **각 step마다 cancel flag를 확인**하는 구조로 설계해야 한다.
- 권장 상태 값:
  - RUNNING / PAUSED / CANCELLED / DONE / FAILED
- st.session_state:
  - `active_job_id`
  - `run_mode` (True/False)
  - `cancel_requested` (optional, but DB status가 더 안정적)
- UI 멈춤 방지:
  - 한 rerun 당 처리량(step_limit)을 적절히 제한 (예: 10)
  - 처리 후 `st.rerun()`으로 갱신
