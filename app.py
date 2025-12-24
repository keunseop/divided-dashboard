import streamlit as st

from core.db import engine
from core.models import Base

st.set_page_config(page_title="Dividend Dashboard", layout="wide")

# DB 테이블 생성
Base.metadata.create_all(bind=engine)

st.title("Dividend Dashboard")
st.write("왼쪽에서 **Import / Table / Dashboard** 페이지로 이동하세요.")
