from datetime import datetime
from pathlib import Path
import sqlite3
import tempfile

import streamlit as st
from sqlalchemy import desc, select

from core.admin_gate import require_admin
from core.db import DB_PATH, DB_URL, db_session
from core.models import DividendEvent, AccountType, TickerMaster

require_admin()

st.title("관리자: 배당 원장 테이블")
st.caption("배당 원장 데이터를 조회하고 아카이브 상태를 직접 조정합니다.")

show_archived = st.checkbox("archived 포함", value=False)
account_filter = st.selectbox("계좌", ["ALL", AccountType.TAXABLE.value, AccountType.ISA.value])

def fmt_money(x):
    return "" if x is None else f"{x:,.0f}"

with db_session() as s:
    q = (
        select(DividendEvent, TickerMaster.name_ko)
        .join(TickerMaster, TickerMaster.ticker == DividendEvent.ticker, isouter=True)
        .order_by(desc(DividendEvent.pay_date))
        .limit(2000)
    )

    if not show_archived:
        q = q.where(DividendEvent.archived == False)  # noqa: E712

    if account_filter != "ALL":
        q = q.where(DividendEvent.account_type == AccountType(account_filter))

    rows = s.execute(q).all()

    data = []
    for ev, name_ko in rows:
        data.append({
            "rowId": ev.row_id,
            "payDate": ev.pay_date,
            "ticker": ev.ticker,
            "name": name_ko or "(미등록)",
            "currency": ev.currency,
            "grossDividend(표시)": fmt_money(ev.gross_dividend),
            "krwGross(표시)": (fmt_money(ev.krw_gross) + "원") if ev.krw_gross is not None else "",
            "tax": ev.tax,
            "netDividend": ev.net_dividend,
            "accountType": ev.account_type.value,
            "archived": ev.archived,
        })

st.dataframe(data, use_container_width=True)

st.divider()
st.subheader("rowId로 archived 토글(간단한 수정 기능)")

row_id = st.text_input("rowId")
if st.button("archived 토글") and row_id:
    with db_session() as s:
        obj = s.execute(select(DividendEvent).where(DividendEvent.row_id == row_id)).scalar_one_or_none()
        if obj is None:
            st.error("해당 rowId를 찾지 못했습니다.")
        else:
            obj.archived = not obj.archived
            st.success(f"{row_id}: archived={obj.archived}")

st.divider()
st.subheader("DB 백업 다운로드(임시)")
st.caption("배포 환경의 최신 DB 파일을 로컬로 내려받기 위한 임시 기능입니다.")

def _backup_sqlite_db(db_path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = Path(tempfile.gettempdir()) / f"dividends_backup_{timestamp}.sqlite3"
    with sqlite3.connect(db_path.as_posix()) as src:
        with sqlite3.connect(backup_path.as_posix()) as dst:
            src.backup(dst)
    return backup_path


if DB_PATH is None:
    st.warning("DIVIDENDS_DB_URL이 설정되어 있어 로컬 SQLite 파일 경로를 확인할 수 없습니다.")
    st.write("현재 DB_URL:", DB_URL)
else:
    st.write("현재 DB 경로:", str(DB_PATH))
    if st.button("백업 파일 생성"):
        backup_path = _backup_sqlite_db(DB_PATH)
        st.session_state["db_backup_path"] = str(backup_path)
        st.success(f"백업 생성 완료: {backup_path.name}")

    backup_path_str = st.session_state.get("db_backup_path")
    if backup_path_str:
        backup_path = Path(backup_path_str)
        if backup_path.exists():
            with backup_path.open("rb") as f:
                st.download_button(
                    label="백업 DB 다운로드",
                    data=f,
                    file_name=backup_path.name,
                    mime="application/x-sqlite3",
                )

st.divider()
st.subheader("DB 삭제(주의)")
st.caption("영구 디스크의 DB 파일을 삭제합니다. 삭제 후 재시작 시 initial_data가 있으면 최초 1회 복사됩니다.")

if DB_PATH is None:
    st.warning("DIVIDENDS_DB_URL이 설정되어 있어 로컬 SQLite 파일을 삭제할 수 없습니다.")
else:
    st.write("삭제 대상 DB:", str(DB_PATH))
    confirm_delete = st.checkbox("정말 삭제할 것을 확인했습니다.")
    confirm_restart = st.checkbox("삭제 후 앱을 재시작해야 함을 이해했습니다.")
    if st.button("DB 파일 삭제") and confirm_delete and confirm_restart:
        if DB_PATH.exists():
            DB_PATH.unlink()
            st.success("DB 파일 삭제 완료. 앱을 재시작해 주세요.")
        else:
            st.info("DB 파일이 이미 존재하지 않습니다.")
