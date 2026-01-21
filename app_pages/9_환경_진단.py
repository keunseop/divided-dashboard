from __future__ import annotations

import importlib
import sys
from importlib import metadata

import streamlit as st


def _try_import(module_name: str) -> tuple[bool, str]:
    try:
        module = importlib.import_module(module_name)
        module_file = getattr(module, "__file__", None)
        return True, module_file or "imported (no __file__)"
    except Exception as exc:
        return False, f"import failed: {exc}"


def _get_version(dist_name: str) -> str:
    try:
        return metadata.version(dist_name)
    except Exception:
        return "not installed"


st.set_page_config(page_title="환경 진단", page_icon="🧪")
st.title("환경 진단")
st.caption("배포 환경에서 실행 중인 파이썬/패키지 상태를 확인합니다.")

st.subheader("Python")
st.write("sys.executable:", sys.executable)
st.write("sys.version:", sys.version)
st.write("sys.path count:", len(sys.path))

st.subheader("Package Versions")
st.write("python-kis:", _get_version("python-kis"))
st.write("pykis:", _get_version("pykis"))

st.subheader("Module Import")
for name in ("pykis.public_api", "pykis", "python_kis", "python_kis.public_api"):
    ok, info = _try_import(name)
    st.write(name, ok, info)
