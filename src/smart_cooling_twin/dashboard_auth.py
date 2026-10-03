"""Optional shared password for a single-owner hosted dashboard."""

import hashlib
import hmac
import os
import streamlit as st


def require_dashboard_access() -> None:
    password = os.environ.get("DASHBOARD_PASSWORD", "")
    if not password:
        return  # Local development; hosted launcher requires a strong secret.
    revision = hashlib.sha256(password.encode()).hexdigest()
    if st.session_state.get("dashboard_authenticated") == revision:
        return

    def authenticate() -> None:
        supplied = st.session_state.pop("dashboard_login_password", "")
        if hmac.compare_digest(supplied.encode(), password.encode()):
            st.session_state["dashboard_authenticated"] = revision
            st.session_state.pop("dashboard_login_failed", None)
        else:
            st.session_state["dashboard_login_failed"] = True

    st.title("Smart Cooling Digital Twin")
    with st.form("dashboard_login"):
        st.text_input("Dashboard password", type="password", key="dashboard_login_password")
        st.form_submit_button("Sign in", on_click=authenticate)
    if st.session_state.get("dashboard_login_failed"):
        st.error("Incorrect password.")
    st.stop()
