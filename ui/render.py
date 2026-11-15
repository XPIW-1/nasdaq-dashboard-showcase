"""HTML builders for the designed instrument panels (rendered with st.html)."""
from html import escape

from config import AMMO_RESERVE_DD
from ui.viewmodel import LADDER_FLOOR, LADDER_MARKS, LADDER_SPLIT, ladder_scale, ladder_segments, tier_key

TIER_ORDER = ["100", "125", "150", "200", "250", "300"]


def _tier_var(key):
    return f"var(--tier-{key})" if key else "var(--rule-strong)"


def top_bar(as_of_text):
    return (
        '<div class="ins ins-top">'
        '<h1><span class="mono">NDX-100</span>长期定投读数</h1>'
        f'<span class="etch">{escape(as_of_text)}</span>'
        "</div>"
    )


def section(title, etch=""):
    etch_html = f'<span class="etch">{escape(etch)}</span>' if etch else ""
    return f'<div class="ins ins-section"><h2>{escape(title)}</h2>{etch_html}</div>'


def readout(*, value, kind_label, reason, next_lines, fresh, issues, pe_hint, change, animate):
    """The first-screen reading: multiplier, why, what's next, and data freshness."""
    key = tier_key(value)
    scale = "".join(
        f'<span class="{"on" if key and TIER_ORDER.index(k) <= TIER_ORDER.index(key) else ""}"></span>'
        for k in TIER_ORDER
    )
    if value is None:
        number = '<div class="value na">—</div>'
    else:
        number = (
            f'<div class="value" data-target="{value:.2f}" data-animate="{int(animate)}">'
            f'<span class="n">{value:.2f}</span><span class="x">×</span></div>'
        )
    pills = f'<span class="pill">{escape(kind_label)}</span>'
    if change == "up":
        pills += '<span class="pill change">今日升档</span>'
    elif change == "down":
        pills += '<span class="pill change">今日降档</span>'
    next_html = "".join(f"<li>{escape(line)}</li>" for line in next_lines)
    next_block = f'<ul class="next">{next_html}</ul>' if next_lines else ""
    hint = (
        f'<span class="hint {pe_hint["level"]}">{escape(pe_hint["text"])}</span>' if pe_hint else ""
    )
    fresh_html = (
        f'<a class="fresh {fresh["level"]}" href="#data-health">'
        f'<span class="dot" aria-hidden="true"></span>{escape(fresh["text"])}</a>'
    )
    issue_html = (
        '<ul class="issues">' + "".join(f"<li>{escape(i)}</li>" for i in issues) + "</ul>"
        if issues
        else ""
    )
    return f"""
<section class="ins readout" style="--tier-color:{_tier_var(key)}" aria-label="今日定投读数">
  <div class="scale" aria-hidden="true">{scale}</div>
  <div class="body">
    <div>
      <div class="etch">Multiplier · 今日倍数</div>
      {number}
      <div class="kind">{pills}</div>
    </div>
    <div>
      <p class="reason">{escape(reason)}</p>
      {next_block}
    </div>
  </div>
  <div class="foot">{fresh_html}{hint}</div>
  {issue_html}
</section>
<script>
(() => {{
  const el = document.querySelector('.readout .value[data-animate="1"] .n');
  if (!el) return;
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const target = parseFloat(el.parentElement.dataset.target);
  if (!isFinite(target) || target <= 1) return;
  const start = performance.now(), dur = 620;
  const ease = t => 1 - Math.pow(2, -10 * t);
  const step = now => {{
    const t = Math.min((now - start) / dur, 1);
    el.textContent = (1 + (target - 1) * ease(t)).toFixed(2);
    if (t < 1) requestAnimationFrame(step); else el.textContent = target.toFixed(2);
  }};
  el.textContent = '1.00';
  requestAnimationFrame(step);
}})();
</script>"""


def ladder(*, dd, position, zone_key, decidable, vxn_value, vxn_live, flash, animate):
    segs = ladder_segments(zone_key)
    seg_html = []
    for seg in segs:
        upgrade = (
            f'<span class="u">VXN&gt;{seg["upgrade"][0]:.0f}<br>→ {seg["upgrade"][1]:.2f}×</span>'
            if seg["upgrade"]
            else '<span class="u">VXN<br>不参与</span>'
        )
        classes = "seg" + (" current" if seg["current"] else "") + (
            " flash" if seg["current"] and flash else ""
        )
        seg_html.append(
            f'<div class="{classes}" style="--s:{seg["start"]:.4f};--e:{seg["end"]:.4f};'
            f'--tier-color:var(--tier-{seg["tier"]})" title="{escape(seg["label"])} {escape(seg["range"])}">'
            f'<div class="m">{seg["base"]:.2f}×</div>{upgrade}</div>'
        )
    label_parts = []
    for seg in segs:
        text = "0%" if seg["key"] == "normal" else "%.0f%%" % (seg["top"] * 100)
        label_parts.append('<span style="--s:%.4f">%s</span>' % (seg["start"], text))
    marks_html = []
    for level in LADDER_MARKS:
        at = ladder_scale(level)
        is_end = abs(level - LADDER_FLOOR) < 1e-9
        if not is_end:
            label_parts.append('<span style="--s:%.4f" class="deep">%.0f%%</span>' % (at, level * 100))
        tag = "弹药保留区" if abs(level - AMMO_RESERVE_DD) < 1e-9 else "手动补仓点"
        marks_html.append(
            '<div class="dmark%s" style="--s:%.4f" title="%.0f%% %s"><span>%s</span></div>'
            % (" end" if is_end else "", at, level * 100, tag, tag if not is_end else "")
        )
    labels = "".join(label_parts) + '<span style="--s:1" class="end">%.0f%%</span>' % (LADDER_FLOOR * 100)

    cursor = ""
    if position is not None and dd is not None:
        edge = " edge-l" if position < 0.08 else (" edge-r" if position > 0.9 else "")
        ref = "" if decidable else " ref"
        tip = f"{dd * 100:.1f}%" + ("" if decidable else " 参考")
        cursor = (
            f'<div class="cursor{edge}{ref}" style="--pos:{position:.4f}" aria-label="当前回撤 {tip}">'
            f'<span class="tip">{escape(tip)}</span><span class="needle"></span></div>'
        )

    sub = ""
    if vxn_value is not None:
        lo, hi = 10.0, 60.0
        x = min(max((vxn_value - lo) / (hi - lo), 0.0), 1.0)
        active = None
        if zone_key in ("mild", "moderate", "deep", "extreme"):
            active = {"mild": 30, "moderate": 35, "deep": 40, "extreme": 45}[zone_key]
        marks = "".join(
            f'<div class="mark{" active" if t == active else ""}" style="--x:{(t - lo) / (hi - lo):.4f}"><span>{t}</span></div>'
            for t in (30, 35, 40, 45)
        )
        state = "" if vxn_live else "（未用于升档）"
        sub = (
            '<div class="sub">'
            '<div class="etch">VXN</div>'
            f'<div class="bar" aria-label="VXN {vxn_value:.1f}">{marks}<span class="now" style="--x:{x:.4f}"></span></div>'
            "<div></div>"
            f'<div class="read">当前 {vxn_value:.1f}{state} · 本档阈值以粗线标出</div>'
            "</div>"
        )

    wrapper = "ins ladder" + (" animate" if animate else "")
    return f"""
<div class="{wrapper}">
  <div class="ruler" role="img" aria-label="回撤档位尺">
    {cursor}
    <div class="track" style="--split:{LADDER_SPLIT:.4f}">{''.join(seg_html)}{''.join(marks_html)}</div>
    <div class="ticks" aria-hidden="true" style="--split:{LADDER_SPLIT:.4f}"></div>
    <div class="labels" aria-hidden="true">{labels}</div>
  </div>
  {sub}
  <p class="legend">每格标注该回撤区间的基础倍数，以及 VXN 超过阈值后的上调倍数。-35% 以下刻度压缩显示：倍数不再上调，-35% 起动用弹药保留区，-45%、-55% 各是一个手动补仓点。游标为当前回撤；虚线游标表示数据仅供参考。</p>
</div>"""


def gauge(label_etch, label_cn, value_text, detail_html):
    return (
        '<div class="gauge">'
        f'<div class="lab">{escape(label_cn)}<span class="etch">{escape(label_etch)}</span></div>'
        f'<div class="v">{escape(value_text)}</div>'
        f'<div class="d">{detail_html}</div>'
        "</div>"
    )


def groups(decision_gauges, reference_gauges):
    return f"""
<div class="ins groups">
  <section class="group" aria-label="决策指标">
    <header><h3>决策指标</h3><span class="etch">Drives the multiplier</span></header>
    <div class="rows">{''.join(decision_gauges)}</div>
  </section>
  <section class="group ref" aria-label="参考指标">
    <header><h3>参考指标</h3><span class="tag">仅参考，不影响倍数</span></header>
    <div class="rows">{''.join(reference_gauges)}</div>
  </section>
</div>"""


def _yuan(amount):
    return f"¥{amount:,.0f}"


def _short_date(day):
    try:
        return f"{day.month}/{day.day}"
    except AttributeError:
        return str(day)


def tier_line(tier_info, multiplier):
    """Tier-change reminder: (level, text)."""
    if multiplier is None:
        return "muted", "今天没有正式倍数，不加仓。"
    if tier_info is None:
        return "muted", "还没有往日记录，暂时算不出距上次换档的天数。"
    if tier_info["changed_today"]:
        return "change", (
            f"今日换档 {tier_info['previous']:.2f}× → {multiplier:.2f}×："
            "从今天起按新金额加仓。"
        )
    since = tier_info["since"]
    return "ok", (
        f"距上次换档 {tier_info['days']} 天（{_short_date(since)} 起为 {multiplier:.2f}×），加仓金额不变。"
    )


def _fund_code(fund):
    return fund.code or fund.name


def auto_line(auto_funds):
    parts = " · ".join(f"{escape(_fund_code(f))} {_yuan(f.daily)}" for f in auto_funds)
    total = sum(f.daily for f in auto_funds)
    return f'<p class="tp-auto"><span class="etch">自动定投 · 固定</span>{parts}，合计 {_yuan(total)}，每天照常扣款，不用改。</p>'


def plan_panel(*, state, topup, previous_topup, auto_funds, tier_info, ammo, ammo_name, ammo_age,
               stale_days, checkpoint, manual_record, manual_fund, last_auto):
    """Today's manual top-up, the fixed auto-invest, tier reminder and ammo.

    ``state`` is 'final' or 'unavailable'.
    """
    auto_html = auto_line(auto_funds)
    if state != "final" or topup is None:
        head = (
            '<div class="tp-head"><span class="tp-amount na">—</span>'
            '<span class="tp-note">今天没有正式倍数，不加仓；自动定投照常扣款。</span></div>'
        )
        return f'<section class="ins topup" aria-label="今日加仓">{head}{auto_html}</section>'

    m = ammo.get("multiplier")
    if topup.total > 0:
        note = f"今日手动加仓 · {_yuan(topup.base)} × ({topup.multiplier:.2f} − 1)"
    elif ammo.get("exhausted"):
        note = "今日不加仓 · 本区弹药额度已用完"
    else:
        note = "今日无需加仓"
    was = ""
    if tier_info is not None and tier_info.get("changed_today") and previous_topup is not None:
        if previous_topup.total != topup.total:
            was = f'<span class="was mono">{_yuan(previous_topup.total)}</span>'
    head = (
        f'<div class="tp-head">{was}<span class="tp-amount">{_yuan(topup.total)}</span>'
        f'<span class="tp-note">{escape(note)}</span></div>'
    )
    banner = ""
    if ammo.get("exhausted"):
        banner = (
            f'<p class="tp-banner warn">本区弹药额度已用完：倍数读数 {m:.2f}×，'
            "按 1.00× 执行（不加仓），直到回撤进入下一个弹药区。</p>"
        )
    elif topup.limited_to is not None:
        banner = (
            f'<p class="tp-banner warn">本区弹药只剩 {_yuan(topup.limited_to)}，'
            f"今天按剩余额度加仓（规则应加 {_yuan(topup.needed)}）。</p>"
        )
    level, text = tier_line(tier_info, m)
    if level == "change":
        text = f"今日换档 {tier_info['previous']:.2f}× → {m:.2f}×：每日加仓改为 {_yuan(topup.total)}。"
    banner += f'<p class="tp-tier {level}">{escape(text)}</p>'

    rows_html = ""
    if topup.items:
        rows = [
            '<li><span class="f">%s<span class="p">%s%s</span></span><span class="a mono">加 %s</span></li>'
            % (
                escape(fund.label),
                escape(fund.platform),
                f" · 单日上限 {_yuan(fund.cap)}（含自动定投 {_yuan(fund.daily)}）" if fund.cap is not None else "",
                _yuan(amount),
            )
            for fund, amount in topup.items
        ]
        rows_html = '<ul class="tp-rows">' + "".join(rows) + "</ul>"
    if topup.over_cap:
        rows_html += (
            f'<p class="tp-gap">可加仓基金的单日上限不够，{_yuan(topup.over_cap)} 今天买不进，放弃。</p>'
        )

    manual = ""
    if checkpoint:
        if manual_record:
            manual = (
                f'<p class="tp-run">本档（{escape(checkpoint)}）已额外补仓 {_yuan(manual_record["amount"])}'
                f'（{escape(str(manual_record.get("date") or ""))}），本档不再补。</p>'
            )
        else:
            fund_text = f"，可买 {escape(manual_fund)}" if manual_fund else ""
            manual = (
                f'<p class="tp-run accent">本档（{escape(checkpoint)}）还可以额外补仓一次：只用弹药{fund_text}。</p>'
            )

    booked = ""
    if last_auto and last_auto.get("amount"):
        booked = (
            f'<p class="tp-run">最近一次自动记账：{escape(str(last_auto.get("date")))} 加仓 '
            f'{_yuan(last_auto["amount"])} 已计入弹药。没加仓或金额不同，请在下方修改。</p>'
        )
    body = rows_html + auto_html + manual + ammo_line(ammo, ammo_name, ammo_age, stale_days) + booked
    return f'<section class="ins topup" aria-label="今日加仓">{head}{banner}{body}</section>'


def ammo_line(ammo, name, age, stale_days):
    name = escape(name)
    zone = ammo.get("zone")
    level = ""
    if not ammo.get("recorded"):
        return f'<p class="tp-run warn">{name}余额和各区已用额度尚未填写，展开下方即可填写；填写后才会自动记账。</p>'
    parts = [f"{name} {_yuan(ammo['balance'] or 0)}"]
    if zone is None:
        parts.append("回撤未到 -8%，不动用弹药")
    else:
        parts.append(
            f"{escape(zone.label)}（{escape(zone.range_label)}）剩 {_yuan(ammo['remaining'])} / {_yuan(zone.budget)}"
        )
        if ammo.get("exhausted"):
            level = " warn"
        elif ammo["monthly"] > 0:
            parts.append(f"按 {ammo['effective']:.2f}× 每月动用 {_yuan(ammo['monthly'])}")
            if ammo["months_left"] is not None:
                parts.append(f"约可撑 {ammo['months_left']:.1f} 个月")
                if ammo["months_left"] < 1:
                    level = " warn"
            if ammo.get("short_of_balance"):
                parts.append("余额少于本区剩余额度，按余额计算")
                level = " warn"
        else:
            parts.append("今日不动用弹药")
    text = " · ".join(parts)
    if age is not None and age > stale_days:
        level = " warn"
        text += f" · 已 {age} 天未更新，可能已过时"
    return f'<p class="tp-run{level}">{text}</p>'


def tier_amounts(table, current_multiplier, monthly):
    """Daily top-up per tier, how to buy it, and the monthly ammo draw."""
    rows = []
    for top in table:
        current = current_multiplier is not None and abs(top.multiplier - current_multiplier) < 1e-9
        how = " + ".join(f"{escape(_fund_code(f))} {a:,.0f}" for f, a in top.items) or "不加仓"
        gap = f'<span class="gap">买不进 {top.over_cap:,.0f}</span>' if top.over_cap else ""
        rows.append(
            f'<tr class="{"current" if current else ""}" style="--tier-color:var(--tier-{tier_key(top.multiplier)})">'
            f'<td class="m mono">{top.multiplier:.2f}×</td>'
            f'<td class="t mono">{top.total:,.0f}</td>'
            f"<td>{how}{gap}</td>"
            f'<td class="mono">{monthly(top.multiplier):,.0f}</td></tr>'
        )
    return (
        '<div class="tiers-wrap"><table class="ins tiers"><thead><tr><th>倍数</th><th>每日加仓</th>'
        "<th>买法</th><th>每月弹药</th></tr></thead>"
        f'<tbody>{"".join(rows)}</tbody></table></div>'
    )


def locked(note):
    return (
        '<section class="ins topup locked" aria-label="资金信息已锁定">'
        '<div class="tp-head"><span class="tp-amount na">锁定</span>'
        f'<span class="tp-note">{escape(note)}</span></div></section>'
    )
