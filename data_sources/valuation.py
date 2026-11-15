"""Auditable Nasdaq-100 valuation proxy with strict source priority."""
from datetime import datetime, timezone
from html import unescape
import re, requests
BLACKROCK_URL="https://www.blackrock.com/us/individual/products/351653/ishares-nasdaq-100-etf"
def _candidate(name,value,date,scope,kind,method,url,usable,note): return {"source_name":name,"value":value,"date":date,"index_or_etf":scope,"trailing_or_forward":kind,"calculation_method":method,"source_url":url,"usable_for_model":usable,"note":note}
def _base(): return {"selected_value":None,"selected_source":None,"selected_date":None,"selected_type":None,"selected_method":None,"candidates":[],"usable_for_model":False,"error_message":None,"value":None,"date":None,"updated_at":datetime.now(timezone.utc).isoformat(),"history":None,"source":"PE source audit","note":"N/A unless a validated proxy is available.","status":"error","fallback_used":False}
def parse_blackrock_pe(html):
    text=unescape(html); start=text.find('"priceEarnings":{'); end=text.find('},"rocPct"',start)
    if start<0 or end<0: raise ValueError("Portfolio Characteristics priceEarnings object not found")
    block=text[start:end]
    if '"label":"P/E Ratio"' not in block: raise ValueError("P/E Ratio label missing")
    vm=re.search(r'"formattedValue":"([0-9,.]+)"',block); dm=re.search(r'"formattedAsOfDate":"([^"]+)"',block)
    if not vm or not dm: raise ValueError("P/E value or as-of date missing")
    value=float(vm.group(1).replace(",",""))
    if not 0<value<200: raise ValueError(f"P/E value out of range: {value}")
    return value,dm.group(1)
def fetch_nasdaq100_pe():
    out=_base(); errors=[]
    try:
        r=requests.get(BLACKROCK_URL,headers={"User-Agent":"Mozilla/5.0 (compatible; NasdaqDashboard/1.0)"},timeout=20); r.raise_for_status(); value,date=parse_blackrock_pe(r.text)
        c=_candidate("BlackRock / iShares IQQ",value,date,"IQQ ETF portfolio","Portfolio P/E (latest fiscal-year earnings)","BlackRock Portfolio Characteristics P/E Ratio",BLACKROCK_URL,True,"IQQ directly tracks the Nasdaq 100 Index; this is an ETF portfolio P/E proxy, not an official index P/E."); out["candidates"].append(c); out.update(selected_value=value,selected_source=c["source_name"],selected_date=date,selected_type="Nasdaq-100 ETF Portfolio P/E Proxy",selected_method=c["calculation_method"],usable_for_model=True,value=value,date=date,source=c["source_name"],note=c["note"],status="ok"); return out
    except Exception as e: errors.append(f"BlackRock: {e}")
    out["candidates"].append(_candidate("BlackRock / iShares IQQ",None,None,"IQQ ETF portfolio","Portfolio P/E", "BlackRock Portfolio Characteristics P/E Ratio",BLACKROCK_URL,False,errors[0])); out["error_message"]="; ".join(errors); out["note"]="暂无可靠估值数据。Yahoo Finance QQQ trailingPE 不作为正式回退源。"; return out
def fetch_pe(): return fetch_nasdaq100_pe()
def manual_pe(value,source,pe_type,note=""):
    usable=pe_type=="Nasdaq-100 Index trailing P/E"; today=datetime.now(timezone.utc).date().isoformat(); v=float(value) if usable else None
    return {"selected_value":v,"selected_source":source,"selected_date":today,"selected_type":pe_type,"selected_method":"User-provided value","candidates":[],"usable_for_model":usable,"error_message":None if usable else "Only Nasdaq-100 Index trailing P/E is eligible for the current model.","value":v,"date":today,"updated_at":datetime.now(timezone.utc).isoformat(),"history":None,"source":"Manual","note":note,"status":"ok" if usable else "reference","fallback_used":False}
