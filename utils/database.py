"""Optional Supabase backend. Secrets are read only on the server side."""
import streamlit as st

import os

TABLE="nasdaq_dashboard_history"
def _credentials():
    """Streamlit secrets first; SUPABASE_URL/SUPABASE_KEY env vars for headless jobs."""
    try:
        s = st.secrets.get("supabase", {})
        if s.get("url") and s.get("key"): return s["url"], s["key"]
    except Exception:
        pass
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
    return (url, key) if url and key else None
def is_supabase_configured():
    return _credentials() is not None
def get_supabase_client():
    if not is_supabase_configured(): return None
    creds=_credentials()
    if creds is None: return None
    try:
        from supabase import create_client
        return create_client(*creds)
    except Exception: return None
def test_connection():
    c=get_supabase_client()
    if c is None: return {"configured":is_supabase_configured(),"ok":False,"error":"Not configured" if not is_supabase_configured() else "Client unavailable"}
    try: c.table(TABLE).select("date",count="exact").limit(1).execute(); return {"configured":True,"ok":True,"error":None}
    except Exception as e: return {"configured":True,"ok":False,"error":str(e)}
def upsert_snapshot(record):
    c=get_supabase_client()
    if c is None: raise RuntimeError("Supabase is not configured")
    return c.table(TABLE).upsert(record,on_conflict="date").execute()
def load_history():
    c=get_supabase_client()
    if c is None: raise RuntimeError("Supabase is not configured")
    r=c.table(TABLE).select("*").order("date").execute(); return r.data or []
