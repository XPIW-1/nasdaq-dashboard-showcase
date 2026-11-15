"""Daily WeChat push (phase 3). Run by GitHub Actions at 08:30 Beijing time.

    python -m push.daily_push            # send if today is an A-share trading day
    python -m push.daily_push --dry-run  # print the message, send nothing, save nothing
    python -m push.daily_push --force    # send even on a non-trading day or a second time

Environment: SERVERCHAN_SENDKEY, SUPABASE_URL, SUPABASE_KEY, DASHBOARD_URL.
"""
import argparse
import datetime as dt
import os
import sys
from zoneinfo import ZoneInfo

from data_sources.ndx import fetch_ndx
from data_sources.valuation import fetch_pe
from data_sources.vxn import fetch_vxn
from model import allocation as alloc_model
from model.decision import decide
from push import serverchan
from push.message import build_body, build_title
from push.trading_calendar import is_trading_day
from ui.viewmodel import tier_change
from utils import settings_store

BEIJING = ZoneInfo("Asia/Shanghai")
STATE_KEY = "push_state"


def load_state():
    record, backend, error = settings_store.get_setting(STATE_KEY)
    value = record.get("value") if isinstance(record, dict) else None
    return (value if isinstance(value, dict) else {}), backend, error


def _tier_start(state, multiplier, today, change):
    """ISO date the current multiplier started (best known)."""
    if change or state.get("multiplier") is None:
        return today.isoformat()
    return state.get("tier_since") or state.get("date") or today.isoformat()


def run(today=None, dry_run=False, force=False, fetch=None, send=None, out=print):
    today = today or dt.datetime.now(BEIJING).date()
    trading, calendar_note = is_trading_day(today)
    if not trading and not force:
        out(f"{today} 不是 A 股交易日，不推送。")
        return "skipped"

    state, backend, state_error = load_state()
    if state_error:
        out(f"警告：推送状态读取失败，已回退到 {backend}：{state_error}")
    if state.get("sent_date") == today.isoformat() and not force:
        out(f"{today} 已推送过，跳过（用 --force 重发）。")
        return "duplicate"

    ndx, vxn, pe = (fetch or _fetch)()
    decision = decide(ndx, vxn, pe)

    config = alloc_model.load_config()
    final = decision["kind"] == "final"
    m = decision["multiplier"]
    ammo_record = settings_store.get_ammo()
    ammo_state = ammo_record["state"]
    if ammo_record["error"]:
        out(f"警告：弹药记录读取失败，已回退到 {ammo_record['backend']}：{ammo_record['error']}")
    ammo = alloc_model.ammo_status(decision["dd"] if final else None, m, config, ammo_state)
    topup = alloc_model.topup_for(ammo, config) if final else None
    previous = {
        "date": state.get("date"),
        "multiplier": state.get("multiplier"),
    }
    change = tier_change(m, previous["multiplier"]) if final else None
    tier_start = _tier_start(state, m, today, change) if final else state.get("tier_since")
    tier_days = (today - dt.date.fromisoformat(tier_start)).days if final and tier_start else None
    previous_topup = alloc_model.daily_topup(previous["multiplier"], config) if change else None
    will_book = bool(final and topup.total > 0 and ammo["zone"] is not None and ammo["recorded"])
    checkpoint = alloc_model.checkpoint(decision["dd"], m) if final else None
    manual = (ammo_state.get("manual") or {}) if ammo_state else {}

    title = build_title(decision, topup, change, previous["multiplier"], ammo)
    body = build_body(
        decision=decision,
        topup=topup,
        previous_topup=previous_topup,
        auto_funds=config.auto_funds,
        will_book=will_book,
        change=change,
        tier_days=tier_days,
        previous=previous if previous["date"] else None,
        ammo=ammo,
        ammo_name=config.ammo_name,
        checkpoint=checkpoint,
        manual_record=manual.get(checkpoint) if checkpoint else None,
        manual_fund=next((f.label for f in config.funds if f.manual_only), None),
        dashboard_url=os.environ.get("DASHBOARD_URL", "").strip() or None,
        calendar_note=calendar_note,
    )

    if dry_run:
        out(f"[dry-run] 标题：{title}\n\n{body}")
        return "dry-run"

    (send or _send)(title, body)
    new_state = {**state, "sent_date": today.isoformat()}
    if decision["kind"] == "final":
        new_state.update(
            date=today.isoformat(),
            multiplier=m,
            effective=ammo["effective"],
            daily_topup=topup.total,
            tier_since=tier_start,
        )
        new_state.pop("daily_total", None)
    saved_backend, save_error = settings_store.set_setting(STATE_KEY, new_state)
    out(f"已推送：{title}（状态保存到 {saved_backend}）")
    if save_error:
        out(f"警告：推送状态写入 Supabase 失败：{save_error}")
    if will_book:
        booked, ammo_backend, ammo_error = settings_store.book_topup(
            ammo_state, ammo["zone"].key, topup.total, today.isoformat()
        )
        if booked:
            out(f"已记入弹药：{ammo['zone'].label} +{topup.total}（保存到 {ammo_backend}）")
        if ammo_error:
            out(f"警告：弹药记账写入 Supabase 失败：{ammo_error}")
    return "sent"


def _fetch():
    return fetch_ndx("max"), fetch_vxn("10y"), fetch_pe()


def _send(title, body):
    serverchan.send(os.environ.get("SERVERCHAN_SENDKEY", ""), title, body)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--date", help="Beijing date to run as (YYYY-MM-DD), for testing")
    args = parser.parse_args(argv)
    today = dt.date.fromisoformat(args.date) if args.date else None
    try:
        run(today=today, dry_run=args.dry_run, force=args.force)
    except Exception as exc:
        print(f"推送失败：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
