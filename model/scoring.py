import math

import numpy as np


def _finite_number(value):
    """Coerce a value to a finite float; return None for missing or invalid input."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def percentile_score(value,history,inverse=False):
    value=_finite_number(value)
    if value is None:return None
    try:
        a=np.asarray(history,dtype=float) if history is not None else np.array([])
    except (TypeError,ValueError,OverflowError):
        return None
    a=a[np.isfinite(a)]
    if a.size<20:return None
    p=float((a<=value).mean()*100); return round(100-p if inverse else p,1)
def fallback_vxn(v):
    x=_finite_number(v)
    if x is None or x<=0:return None
    for lim,s in [(15,10),(20,30),(25,50),(30,65),(35,80),(45,90),(float('inf'),100)]:
        if x<lim:return s
    return None
def fallback_pe(v):
    if v is None:return None
    for lim,s in [(20,100),(23,90),(26,80),(29,65),(32,50),(35,35),(40,20),(float('inf'),5)]:
        if v<lim:return s
def score_pe(pe):
    """Continuous valuation score used for both automatic and manual PE."""
    x=_finite_number(pe)
    if x is None or x<=0:return None
    if x<=20:return 100.0
    if x<=25:return float(np.interp(x,[20,25],[100,85]))
    if x<=30:return float(np.interp(x,[25,30],[85,65]))
    if x<=35:return float(np.interp(x,[30,35],[65,45]))
    if x<=40:return float(np.interp(x,[35,40],[45,25]))
    if x<=50:return float(np.interp(x,[40,50],[25,5]))
    return 0.0
def score_drawdown(drawdown_pct):
    value=_finite_number(drawdown_pct)
    if value is None:return None
    x=abs(value)
    # Drawdown is current/high - 1, so its magnitude can never exceed 100%.
    if x>100:return None
    if x>=30:return 100.0
    return round(float(np.interp(x,[0,5,10,15,20,30],[0,0,30,55,75,90])),1)
def drawdown_score(dd):
    if dd is None:return None
    x=abs(dd)*100; return round(float(np.interp(x,[0,5,10,15,20,25,30,100],[10,10,30,50,65,80,90,100])),1)
def breadth_score(breadth):
    """Inverse piecewise-linear score: weaker breadth means higher opportunity."""
    if breadth is None:return None
    return round(float(np.interp(float(breadth),[0,10,20,30,40,50,60,70,80,100],[100,100,90,80,65,50,35,20,10,10])),1)
def total_score(scores,weights):
    valid={}
    for key,value in scores.items():
        number=_finite_number(value); weight=_finite_number(weights.get(key,0.0))
        if number is None or weight is None or weight<=0:continue
        valid[key]=(number,weight)
    if not valid:return None,0.0
    d=sum(weight for _,weight in valid.values())
    if d<=0:return None,0.0
    return round(max(0.0,min(100.0,sum(number*weight for number,weight in valid.values())/d)),1),d
def composite_score(scores,weights,min_valid=3):
    valid=0
    for key,value in scores.items():
        if _finite_number(value) is None:continue
        weight=_finite_number(weights.get(key,0.0))
        if weight is not None and weight>0:valid+=1
    if valid<min_valid:return None,0.0
    return total_score(scores,weights)
def confidence(scores,weights,stale_flags=None):
    stale_flags=stale_flags or {}
    base=0.0
    for key,value in scores.items():
        weight=_finite_number(weights.get(key,0.0))
        if _finite_number(value) is not None and weight is not None and weight>0:base+=weight
    pen=0.0
    for key,is_stale in stale_flags.items():
        if not is_stale or _finite_number(scores.get(key)) is None:continue
        weight=_finite_number(weights.get(key,0.0))
        if weight is not None and weight>0:pen+=weight*.25
    return round(max(0.0,min(100.0,(base-pen)*100)),1)
