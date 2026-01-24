from __future__ import annotations

import streamlit as st

from core.secrets import SecretUtil

_ADMIN_STATE_KEY = "admin_unlocked"
_ADMIN_FORM_KEY = "admin_gate_form"
_ADMIN_GATE_ENV = "ADMIN_GATE_ENABLED"


def _trigger_rerun() -> None:
    """Call st.rerun when available while keeping backwards compatibility."""
    rerun_fn = getattr(st, "rerun", None) or getattr(st, "experimental_rerun", None)
    if rerun_fn:
        rerun_fn()


def _get_admin_password() -> str | None:
    """Fetch the admin password from Streamlit secrets or environment."""
    return SecretUtil.get("ADMIN_PASSWORD")


def _is_admin_gate_enabled() -> bool:
    return SecretUtil.get_bool(_ADMIN_GATE_ENV)


def is_admin_unlocked() -> bool:
    """Check whether the current session already passed the admin gate."""
    return st.session_state.get(_ADMIN_STATE_KEY, False) is True


def lock_admin() -> None:
    """Reset the admin gate for the current session."""
    if _ADMIN_STATE_KEY in st.session_state:
        del st.session_state[_ADMIN_STATE_KEY]


def require_admin() -> None:
    """Stop execution unless the user provides the configured admin password."""
    if not _is_admin_gate_enabled():
        return
    if is_admin_unlocked():
        return

    password = _get_admin_password()
    if not password:
        st.error("관리자 비밀번호가 설정되어 있지 않습니다. ADMIN_PASSWORD 값을 환경변수 또는 secrets.toml에 추가해 주세요.")
        st.stop()

    st.warning("관리자 메뉴입니다. 비밀번호를 입력해 주세요.")
    with st.form(_ADMIN_FORM_KEY, clear_on_submit=True):
        entered = st.text_input("관리자 비밀번호", type="password")
        submitted = st.form_submit_button("확인")

    if not submitted:
        st.stop()

    if entered == password:
        st.session_state[_ADMIN_STATE_KEY] = True
        st.success("관리자 권한이 확인되었습니다.")
        _trigger_rerun()

    st.error("비밀번호가 올바르지 않습니다.")
    st.stop()
