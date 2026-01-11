from __future__ import annotations

import os

import streamlit as st

_USER_STATE_KEY = "user_unlocked"
_USER_FORM_KEY = "user_gate_form"


def _trigger_rerun() -> None:
    rerun_fn = getattr(st, "rerun", None) or getattr(st, "experimental_rerun", None)
    if rerun_fn:
        rerun_fn()


def _get_user_password() -> str | None:
    secret = st.secrets.get("USER_PASSWORD") if hasattr(st, "secrets") else None
    if isinstance(secret, str) and secret.strip():
        return secret.strip()
    env_value = os.environ.get("USER_PASSWORD")
    if env_value and env_value.strip():
        return env_value.strip()
    return None


def is_user_unlocked() -> bool:
    return st.session_state.get(_USER_STATE_KEY, False) is True


def lock_user() -> None:
    if _USER_STATE_KEY in st.session_state:
        del st.session_state[_USER_STATE_KEY]


def require_user() -> None:
    if is_user_unlocked():
        return

    password = _get_user_password()
    if not password:
        st.error("사용자 비밀번호가 설정되어 있지 않습니다. USER_PASSWORD 값을 secrets.toml 또는 환경변수에 추가해 주세요.")
        st.stop()

    st.info("내 포지션 메뉴입니다. 사용자 비밀번호를 입력해 주세요.")
    with st.form(_USER_FORM_KEY, clear_on_submit=True):
        entered = st.text_input("사용자 비밀번호", type="password")
        submitted = st.form_submit_button("확인")

    if not submitted:
        st.stop()

    if entered == password:
        st.session_state[_USER_STATE_KEY] = True
        st.success("접근이 허용되었습니다.")
        _trigger_rerun()

    st.error("비밀번호가 올바르지 않습니다.")
    st.stop()
