from pathlib import Path
import pandas as pd
from . import database
PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIELDS=["date","ndx","ndx_date","ath","ath_date","drawdown","drawdown_score","vxn","vxn_date","vxn_score","pe","pe_score","pe_source","pe_type","pe_note","pe_input_mode","breadth","breadth_score","breadth_source","breadth_above_count","breadth_usable_count","breadth_total_count","breadth_date","total_score","confidence","multiplier","market_status","signal","model_version"]
def upsert_history(row,path=None):
    p=Path(path) if path else PROJECT_ROOT / "data" / "history.csv"; p.parent.mkdir(parents=True,exist_ok=True); old=pd.read_csv(p) if p.exists() else pd.DataFrame(columns=FIELDS)
    for field in FIELDS:
        if field not in old.columns: old[field] = None
    old=old[FIELDS]
    if not old.empty: old=old[old.date.astype(str)!=str(row["date"])]
    pd.concat([old,pd.DataFrame([{k:row.get(k) for k in FIELDS}])],ignore_index=True).to_csv(p,index=False)
def load_history(path=None):
    p=Path(path) if path else PROJECT_ROOT / "data" / "history.csv"
    if not p.exists(): return pd.DataFrame(columns=FIELDS)
    df=pd.read_csv(p)
    for field in FIELDS:
        if field not in df.columns: df[field]=None
    return df[FIELDS]

def save_history(record):
    """Cloud-first save with explicit CSV fallback status."""
    status=database.test_connection()
    if status.get("ok"):
        try: database.upsert_snapshot({k:record.get(k) for k in FIELDS}); return "Supabase", None
        except Exception as e: status={"ok":False,"error":str(e),"configured":True}
    upsert_history(record)
    return "Local CSV fallback", status.get("error")

def load_history_preferred():
    status=database.test_connection()
    if status.get("ok"):
        try: return pd.DataFrame(database.load_history()).reindex(columns=FIELDS), "Supabase", None
        except Exception as e: status={"ok":False,"error":str(e),"configured":True}
    return load_history(), "Local CSV fallback", status.get("error")

def _migration_failure(position, row, error):
    raw_date = row.get("date")
    if raw_date is None or pd.isna(raw_date):
        date = None
    elif hasattr(raw_date, "date"):
        date = raw_date.date().isoformat()
    else:
        date = str(raw_date)
    return {"row": int(position) + 2, "date": date, "error": error}


def _migration_error_text(exc):
    message = str(exc).strip()
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__


def migrate_local_csv():
    df=load_history(); rows_read=len(df); uploaded=failed=0; failed_rows=[]
    if not database.test_connection().get("ok"):
        failed_rows=[
            _migration_failure(position,row,"Supabase unavailable")
            for position,(_,row) in enumerate(df.iterrows())
        ]
        return {"rows_read":rows_read,"rows_uploaded":0,"rows_failed":rows_read,"error":"Supabase unavailable","failed_rows":failed_rows}
    for position,(_,row) in enumerate(df.iterrows()):
        try: database.upsert_snapshot({k:(None if pd.isna(row.get(k)) else row.get(k)) for k in FIELDS}); uploaded+=1
        except Exception as exc:
            failed+=1
            failed_rows.append(_migration_failure(position,row,_migration_error_text(exc)))
    return {"rows_read":rows_read,"rows_uploaded":uploaded,"rows_failed":failed,"error":None if failed==0 else "Some rows failed","failed_rows":failed_rows}
