"""ECharts panels rendered in a component iframe (theme follows the system)."""
import json
import math

from ui.theme import FONT_IMPORT, TOKENS_CSS

ECHARTS_SRC = "https://cdnjs.cloudflare.com/ajax/libs/echarts/5.5.0/echarts.min.js"


def _points(series, scale=1.0, digits=2):
    if series is None or len(series) == 0:
        return []
    out = []
    for index, value in series.items():
        try:
            number = float(value) * scale
        except (TypeError, ValueError):
            continue
        if not math.isfinite(number):
            continue
        out.append([index.strftime("%Y-%m-%d"), round(number, digits)])
    return out


_SHELL = """<!doctype html><html><head><meta charset="utf-8">
<style>@import url('__FONT__');__TOKENS__
html,body{margin:0;background:transparent;font-family:var(--mono);}
#c{width:100%;height:__H__px;}
.empty{font:14px var(--cjk);color:var(--ink-2);padding:1rem 0;}
</style></head><body><div id="c"></div>
<script src="__SRC__"></script>
<script>
const PAYLOAD = __PAYLOAD__;
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
function build() {
  const T = {ink: css('--ink'), ink2: css('--ink-2'), rule: css('--rule'), strong: css('--rule-strong'),
    paper: css('--paper-raised'), cursor: css('--cursor'),
    tiers: ['--tier-100','--tier-125','--tier-150','--tier-200','--tier-250','--tier-300'].map(css)};
  const panels = PAYLOAD.panels, n = panels.length, gap = 44, top = 28, bottom = 46;
  const h = (PAYLOAD.height - top - bottom - gap * (n - 1)) / n;
  const axisLabel = {color: T.ink2, fontFamily: 'IBM Plex Mono, monospace', fontSize: 11};
  const grid = [], xAxis = [], yAxis = [], series = [], title = [];
  panels.forEach((p, i) => {
    const y = top + i * (h + gap);
    grid.push({left: 48, right: 14, top: y, height: h});
    title.push({text: p.title, left: 48, top: y - 22, textStyle: {color: T.ink, fontSize: 12, fontWeight: 600,
      fontFamily: 'PingFang SC, Microsoft YaHei, sans-serif'}});
    xAxis.push({type: 'time', gridIndex: i, axisLine: {lineStyle: {color: T.strong}}, axisTick: {lineStyle: {color: T.strong}},
      axisLabel: Object.assign({show: i === n - 1, hideOverlap: true}, axisLabel), splitLine: {show: false}});
    yAxis.push(Object.assign({type: 'value', gridIndex: i, scale: !p.zeroTop, axisLabel: Object.assign({formatter: p.unit === '%' ? '{value}%' : '{value}'}, axisLabel),
      splitLine: {lineStyle: {color: T.rule, type: [2, 4]}}}, p.zeroTop ? {max: 0} : {}));
    const markLine = {silent: true, symbol: 'none', animationDuration: reduce ? 0 : 300,
      label: {color: T.ink2, fontFamily: 'IBM Plex Mono, monospace', fontSize: 10, position: 'insideStartTop'},
      lineStyle: {color: T.strong, type: [3, 3], width: 1}, data: (p.lines || []).map(v => ({yAxis: v.y, label: {formatter: v.label}}))};
    const markArea = p.bands ? {silent: true, data: p.bands.map(b => [{yAxis: b.from, itemStyle: {color: T.tiers[b.tier], opacity: .18}}, {yAxis: b.to}])} : undefined;
    series.push({type: 'line', name: p.title, xAxisIndex: i, yAxisIndex: i, data: p.data, showSymbol: p.data.length < 30, symbolSize: 5,
      lineStyle: {color: i === 0 && p.primary ? T.cursor : T.ink, width: 1.4}, itemStyle: {color: T.cursor},
      emphasis: {disabled: true}, markLine, markArea});
  });
  return {
    animation: !reduce, animationDuration: 900, animationEasing: 'cubicOut',
    textStyle: {fontFamily: 'IBM Plex Mono, monospace'}, title, grid, xAxis, yAxis, series,
    axisPointer: {link: [{xAxisIndex: 'all'}], lineStyle: {color: T.cursor}, label: {backgroundColor: T.cursor}},
    tooltip: {trigger: 'axis', backgroundColor: T.paper, borderColor: T.strong, borderRadius: 2,
      textStyle: {color: T.ink, fontFamily: 'IBM Plex Mono, monospace', fontSize: 12},
      valueFormatter: v => (v == null ? '—' : v)}
  };
}
function render() {
  if (!window.echarts) { document.getElementById('c').innerHTML = '<div class="empty">图表库加载失败，请检查网络后刷新。</div>'; return; }
  const chart = echarts.getInstanceByDom(document.getElementById('c')) || echarts.init(document.getElementById('c'), null, {renderer: 'svg'});
  chart.setOption(build(), true);
  window.addEventListener('resize', () => chart.resize());
  new ResizeObserver(() => chart.resize()).observe(document.getElementById('c'));
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => chart.setOption(build(), true));
}
render();
</script></body></html>"""


def chart_html(panels, height):
    payload = json.dumps({"panels": panels, "height": height}, ensure_ascii=False)
    return (
        _SHELL.replace("__FONT__", FONT_IMPORT)
        .replace("__TOKENS__", TOKENS_CSS)
        .replace("__SRC__", ECHARTS_SRC)
        .replace("__H__", str(height))
        .replace("__PAYLOAD__", payload.replace("</", "<\\/"))
    )


def drawdown_panel(drawdown_series):
    bands = [
        {"from": 0, "to": -8, "tier": 0},
        {"from": -8, "to": -12, "tier": 1},
        {"from": -12, "to": -18, "tier": 2},
        {"from": -18, "to": -25, "tier": 3},
        {"from": -25, "to": -60, "tier": 4},
    ]
    data = _points(drawdown_series, scale=100.0, digits=2)
    low = min((p[1] for p in data), default=-10.0)
    visible = [b for b in bands if b["from"] > low - 2]
    return {
        "title": "回撤 %（相对历史最高收盘价）",
        "unit": "%",
        "data": data,
        "zeroTop": True,
        "primary": True,
        "bands": [{**b, "to": max(b["to"], low - 2)} for b in visible],
        "lines": [{"y": y, "label": f"{y}%"} for y in (-8, -12, -18, -25) if y > low - 2],
    }


def vxn_panel(vxn_series):
    return {
        "title": "VXN",
        "unit": "",
        "data": _points(vxn_series),
        "lines": [{"y": y, "label": f"{y}"} for y in (30, 35, 40, 45)],
    }


def plain_panel(title, series, lines=None):
    return {"title": title, "unit": "", "data": _points(series), "lines": lines or []}
