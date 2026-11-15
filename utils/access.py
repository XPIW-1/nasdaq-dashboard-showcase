"""Optional access code that hides personal money figures on a public app.

If ``access_code`` is set in Streamlit secrets, money panels stay locked until
the visitor enters it once per session. Without a configured code (local
runs) everything is unlocked.
"""
import hmac

import streamlit as st

SESSION_KEY = "_money_unlocked"


def configured_code():
    try:
        code = st.secrets.get("access_code")
    except Exception:
        return None
    code = str(code).strip() if code is not None else ""
    return code or None


def is_unlocked():
    if configured_code() is None:
        return True
    return bool(st.session_state.get(SESSION_KEY, False))


def try_unlock(attempt):
    code = configured_code()
    if code is None:
        return True
    ok = hmac.compare_digest(str(attempt or "").strip().encode("utf-8"), code.encode("utf-8"))
    if ok:
        st.session_state[SESSION_KEY] = True
    return ok
