import streamlit as st

from core.db import engine, run_simple_migrations
from core.models import Base

st.set_page_config(page_title="Dividend Dashboard", layout="wide")

# DB 테이블 생성 및 간단 마이그레이션
Base.metadata.create_all(bind=engine)
run_simple_migrations()

home = st.Page("app_pages/0_앱_소개.py", title="앱 소개", icon="🏠", default=True)
dashboard = st.Page("app_pages/1_대시보드.py", title="대시보드", icon="📊")
portfolio = st.Page("app_pages/2_포트폴리오_관리.py", title="포트폴리오 관리", icon="🧺")
dividend_import = st.Page("app_pages/3_배당_내역_가져오기.py", title="배당 내역 가져오기", icon="📥")
holding_trend = st.Page("app_pages/4_보유_종목_배당_추이.py", title="보유 종목 배당 추이", icon="📈")
ticker_lookup = st.Page("app_pages/5_종목_검색.py", title="종목 검색", icon="🔍")
alimtalk_parser = st.Page("app_pages/6_알림톡_파서.py", title="알림톡 파서", icon="💬")
admin_ledger = st.Page("app_pages/90_관리자_배당_원장_테이블.py", title="배당 원장 테이블", icon="📑")
admin_master = st.Page("app_pages/91_관리자_종목_마스터_관리.py", title="종목 마스터 관리", icon="🗂️")
admin_missing = st.Page("app_pages/92_관리자_미등록_티커_확인.py", title="미등록 티커 확인", icon="❓")
admin_dart_single = st.Page("app_pages/93_관리자_DART_단건_조회.py", title="DART 단건 조회", icon="🛰️")
admin_dart_prefetch = st.Page("app_pages/94_관리자_DART_배당_미리채우기.py", title="DART 배당 미리 채우기", icon="⚙️")

nav = st.navigation(
    {
        "소개": [home],
        "내 포지션": [dashboard, portfolio, dividend_import, holding_trend],
        "유틸": [ticker_lookup, alimtalk_parser],
        "관리자": [
            admin_ledger,
            admin_master,
            admin_missing,
            admin_dart_single,
            admin_dart_prefetch,
        ],
    }
)
nav.run()
