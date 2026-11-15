"""Build the daily push: a title that is the conclusion, and a short body."""
from config import DRAWDOWN_ZONES
from push.serverchan import TITLE_LIMIT
from ui.viewmodel import build_next_steps, build_pe_hint, build_reason

NEAR_TIER_PP = 2.0  # percentage points of drawdown


def fmt_multiplier(m):
    return f"{m:.2f}" if round(m * 100) % 10 else f"{m:.1f}"


def _yuan(amount):
    return f"¥{amount:,.0f}"


def _near_next_tier(dd, zone):
    if dd is None or zone is None:
        return None
    index = next(i for i, z in enumerate(DRAWDOWN_ZONES) if z["key"] == zone["key"])
    if index >= len(DRAWDOWN_ZONES) - 1:
        return None
    nxt = DRAWDOWN_ZONES[index + 1]
    distance = (abs(nxt["max_dd"]) - abs(dd)) * 100
    return nxt if 0 <= distance < NEAR_TIER_PP else None


def _buy(topup):
    return " + ".join(f"{f.code or f.name} ¥{a:,.0f}" for f, a in topup.items)


def build_title(decision, topup, change, previous_multiplier=None, ammo=None):
    if decision["kind"] != "final":
        return "⚠ 数据异常 · 请打开仪表盘核对"
    m = decision["multiplier"]
    total = topup.total if topup is not None else 0
    if change and previous_multiplier is not None:
        return f"换档 {fmt_multiplier(previous_multiplier)}→{fmt_multiplier(m)}× · 每日加仓¥{total:,.0f}"[:TITLE_LIMIT]
    head = f"纳指 {fmt_multiplier(m)}×"
    if ammo and ammo.get("exhausted"):
        return f"{head} · 本区弹药用完 今日不加仓"
    if total == 0:
        return f"{head} · 今日无需加仓"
    title = f"{head} · 加仓 {_buy(topup)}"
    if len(title) > TITLE_LIMIT:
        title = f"{head} · 加仓 ¥{total:,.0f}"
    return title


def ammo_text(ammo, name):
    if not ammo.get("recorded"):
        return f"{name}余额和各区已用额度尚未填写，请在仪表盘填写（填写后才会自动记账）。"
    zone = ammo.get("zone")
    head = f"{name} {_yuan(ammo['balance'] or 0)}"
    if zone is None:
        return f"{head}，回撤未到 -8%，不动用弹药。"
    text = f"{head}，{zone.label}（{zone.range_label}）剩 {_yuan(ammo['remaining'])} / {_yuan(zone.budget)}"
    if ammo.get("exhausted"):
        return text + "，**本区额度已用完，按 1.00× 执行**。"
    if ammo["monthly"] <= 0:
        return text + "，今日不动用弹药。"
    text += f"，按 {ammo['effective']:.2f}× 每月动用 {_yuan(ammo['monthly'])}"
    if ammo["months_left"] is not None:
        text += f"，约可撑 {ammo['months_left']:.1f} 个月"
    if ammo.get("short_of_balance"):
        text += "（余额少于本区剩余额度，按余额计算）"
    return text + "。"


def build_body(
    *,
    decision,
    topup,
    previous_topup,
    auto_funds,
    will_book,
    change,
    tier_days,
    previous,
    ammo,
    ammo_name,
    checkpoint,
    manual_record,
    manual_fund,
    dashboard_url,
    calendar_note=None,
):
    lines = []
    kind = decision["kind"]
    auto = " · ".join(f"{f.code or f.name} {_yuan(f.daily)}" for f in auto_funds)
    if kind != "final":
        lines.append("**今天没有正式倍数，不加仓；自动定投照常扣款。**")
        lines.append("")
        for issue in decision["issues"] or ["关键数据不完整"]:
            lines.append(f"- {issue}")
    else:
        lines.append(build_reason(kind, decision["dd"], decision["zone"], decision["vxn_value"], decision["vxn_live"]))
        lines.append("")
        if ammo.get("exhausted"):
            lines.append(f"**本区弹药额度已用完：倍数读数 {decision['multiplier']:.2f}×，按 1.00× 执行，今日不加仓。**")
        elif topup.total > 0:
            before = ""
            if previous_topup is not None and previous_topup.total != topup.total:
                before = f"（原 {_yuan(previous_topup.total)}）"
            lines.append(
                f"**今日手动加仓 {_yuan(topup.total)}**{before}：{_yuan(topup.base)} × ({topup.multiplier:.2f} − 1)"
            )
            for fund, amount in topup.items:
                lines.append(f"- {fund.label}（{fund.platform}）：加 {_yuan(amount)}")
            if topup.limited_to is not None:
                lines.append(f"- 本区弹药只剩 {_yuan(topup.limited_to)}，按剩余额度加仓（规则应加 {_yuan(topup.needed)}）")
            if topup.over_cap:
                lines.append(f"- 单日上限不够，{_yuan(topup.over_cap)} 今天买不进，放弃")
        else:
            lines.append("**今日无需加仓。**")
        lines.append(f"自动定投照常：{auto}。")
        lines.append("")
        if change:
            lines.append(f"**今日换档：从今天起每日加仓 {_yuan(topup.total)}。**")
        elif tier_days is not None:
            lines.append(f"距上次换档 {tier_days} 天，加仓金额不变。")
        for step in build_next_steps(kind, decision["dd"], decision["zone"], decision["vxn_value"], decision["vxn_live"]):
            lines.append(f"- {step}")
        near = _near_next_tier(decision["dd"], decision["zone"])
        if near is not None:
            lines.append(f"- 回撤接近 {near['base']:.2f}× 档（{near['max_dd'] * 100:.0f}%）。")

        if checkpoint:
            lines.append("")
            if manual_record:
                lines.append(f"本档（{checkpoint}）已额外补仓 {_yuan(manual_record['amount'])}，本档不再补。")
            else:
                fund_text = f"，可买 {manual_fund}" if manual_fund else ""
                lines.append(f"本档（{checkpoint}）还可以额外补仓一次：只用弹药{fund_text}，补完在仪表盘记录。")

        lines.append("")
        lines.append(ammo_text(ammo, ammo_name))
        if will_book:
            lines.append(f"今日加仓 {_yuan(topup.total)} 已自动计入弹药；没加仓或金额不同，请在仪表盘修改。")

        hint = build_pe_hint(decision["pe_value"], decision["pe_live"])
        if hint:
            lines.append("")
            lines.append(hint["text"])
        if decision["issues"]:
            lines.append("")
            lines.extend(f"- 注意：{issue}" for issue in decision["issues"])

    lines.append("")
    if previous and previous.get("date"):
        prev_m = previous.get("multiplier")
        prev_text = f"{fmt_multiplier(prev_m)}×" if isinstance(prev_m, (int, float)) else "无正式倍数"
        lines.append(f"上次推送：{previous['date']}（{prev_text}）")
    lines.append(f"数据：NDX {decision['ndx_date'] or '—'} · VXN {decision['vxn_date'] or '—'} 美股收盘")
    if calendar_note:
        lines.append(calendar_note)
    if dashboard_url:
        lines.append(f"[打开仪表盘]({dashboard_url})")
    # Server酱 renders Markdown: one blank line between items keeps them apart.
    return "\n\n".join(line for line in lines if line != "")
