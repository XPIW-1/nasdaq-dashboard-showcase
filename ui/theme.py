"""Design tokens and global styles for the "precision instrument" world (see DESIGN.md)."""

FONT_IMPORT = (
    "https://fonts.googleapis.com/css2?"
    "family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap"
)

TOKENS_CSS = """
:root {
  --paper: #F3F0E8; --paper-raised: #FAF8F3;
  --ink: #1F2124; --ink-2: #55585D;
  --rule: #D3CEC2; --rule-strong: #8C877C;
  --tier-100: #C4CCD8; --tier-125: #9DAECB; --tier-150: #7690C2;
  --tier-200: #4C6DB4; --tier-250: #2B4FA4; --tier-300: #15338C;
  --cursor: #15338C;
  --ok: #3D6643; --warn: #8A5D12; --bad: #9C3826;
  --ok-wash: rgba(61,102,67,.10); --warn-wash: rgba(176,122,31,.12); --bad-wash: rgba(156,56,38,.10);
  --select: rgba(118,144,194,.32);
  --mono: "IBM Plex Mono", ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace;
  --sans: "IBM Plex Sans", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans CJK SC", system-ui, sans-serif;
  --cjk: "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans CJK SC", system-ui, sans-serif;
  --ease-out: cubic-bezier(0.16, 1, 0.3, 1);
  --ease-overshoot: cubic-bezier(0.34, 1.35, 0.5, 1);
}
@media (prefers-color-scheme: dark) {
  :root {
    --paper: #1C1B19; --paper-raised: #252421;
    --ink: #ECE8DF; --ink-2: #A8A39A;
    --rule: #3A3834; --rule-strong: #6B675F;
    --tier-100: #3A4458; --tier-125: #44567A; --tier-150: #4F6AA3;
    --tier-200: #5E80CC; --tier-250: #7A9BE6; --tier-300: #9DB8FF;
    --cursor: #9DB8FF;
    --ok: #7FB287; --warn: #D9A653; --bad: #E07A64;
    --ok-wash: rgba(127,178,135,.12); --warn-wash: rgba(217,166,83,.13); --bad-wash: rgba(224,122,100,.12);
    --select: rgba(122,155,230,.35);
  }
}
"""

GLOBAL_CSS = TOKENS_CSS + """
@property --p { syntax: '<number>'; inherits: true; initial-value: 0; }

/* Streamlit chrome carries the instrument's paper and ink. */
.stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"] { background: var(--paper); }
[data-testid="stHeader"] { box-shadow: none; }
.stApp, .stApp p, .stApp li, .stApp label { color: var(--ink); font-family: var(--cjk); }
.block-container { max-width: 1120px; padding-top: 2.25rem; padding-bottom: 4rem; }
@media (max-width: 640px) { .block-container { padding-left: 16px; padding-right: 16px; padding-top: 1rem; } }
::selection { background: var(--select); }
.stApp *:focus-visible { outline: 2px solid var(--cursor); outline-offset: 2px; }
.stApp ::-webkit-scrollbar { width: 8px; height: 8px; }
.stApp ::-webkit-scrollbar-thumb { background: var(--rule-strong); border-radius: 4px; }
.stApp ::-webkit-scrollbar-track { background: transparent; }
[data-testid="stExpander"] details { border: 1px solid var(--rule); border-radius: 2px; background: var(--paper-raised); }
[data-testid="stExpander"] summary p { font-family: var(--sans); font-weight: 500; letter-spacing: .02em; }
[data-testid="stMetricValue"] { font-family: var(--mono); font-variant-numeric: tabular-nums; font-size: 1.35rem; }
[data-testid="stExpander"] h3 { font-family: var(--cjk); font-size: 1rem; font-weight: 600; padding: 1rem 0 .4rem; border-bottom: 1px solid var(--rule); margin-bottom: .6rem; }
.stButton button, [data-testid="stButtonGroup"] button { border-radius: 2px; font-family: var(--sans); }
.stButton button { background: var(--paper-raised); color: var(--ink); border: 1px solid var(--rule-strong); }
.stButton button:hover { border-color: var(--cursor); color: var(--cursor); }
[data-testid="stButtonGroup"] button { background: transparent; color: var(--ink-2); border-color: var(--rule-strong); }
[data-testid="stButtonGroup"] button[aria-checked="true"] { background: var(--cursor) !important; border-color: var(--cursor) !important; color: var(--paper-raised) !important; }
[data-testid="stButtonGroup"] button[aria-checked="true"] * { color: var(--paper-raised) !important; }
[data-testid="stButtonGroup"] button:hover { color: var(--cursor); border-color: var(--cursor); }

/* ---------- instrument primitives ---------- */
.ins { font-family: var(--cjk); color: var(--ink); }
.ins .mono { font-family: var(--mono); font-variant-numeric: tabular-nums; }
.ins .etch { font-family: var(--sans); font-size: .72rem; font-weight: 500; letter-spacing: .1em;
  text-transform: uppercase; color: var(--ink-2); }
.ins-section { margin: 2.75rem 0 .9rem; display: flex; align-items: baseline; gap: .75rem;
  border-bottom: 1px solid var(--rule-strong); padding-bottom: .4rem; }
.ins-section h2 { font-family: var(--cjk); font-size: 1.05rem; font-weight: 600; margin: 0; padding: 0; color: var(--ink); }
.ins-section .etch { margin-left: auto; }

/* ---------- top bar ---------- */
.ins-top { display: flex; align-items: baseline; justify-content: space-between; gap: 1rem; margin-bottom: .9rem; }
.ins-top h1 { font-family: var(--cjk); font-size: 1rem; font-weight: 600; margin: 0; padding: 0; color: var(--ink); letter-spacing: .02em; }
.ins-top h1 .mono { font-weight: 500; color: var(--ink-2); margin-right: .5rem; }

/* ---------- readout (hero) ---------- */
.readout { position: relative; background: var(--paper-raised); border: 1px solid var(--rule-strong);
  padding: 0 0 1.25rem; overflow: hidden; }
.readout .scale { display: grid; grid-template-columns: repeat(6, 1fr); height: 6px; }
.readout .scale span { background: var(--rule); border-right: 1px solid var(--paper-raised); }
.readout .scale span.on { background: var(--tier-color); }
.readout .body { display: grid; grid-template-columns: minmax(0, auto) 1fr; gap: .5rem 2.5rem;
  padding: 1.25rem 1.5rem 0; align-items: end; }
.readout .value { font-family: var(--mono); font-variant-numeric: tabular-nums; font-weight: 500;
  font-size: clamp(3.5rem, 13vw, 5.25rem); line-height: .95; letter-spacing: -.03em; color: var(--ink); }
.readout .value .x { font-weight: 400; color: var(--ink-2); margin-left: .04em; }
.readout .value.na { color: var(--ink-2); font-size: clamp(2.5rem, 9vw, 3.5rem); }
.readout .kind { margin-top: .55rem; display: flex; gap: .6rem; align-items: center; flex-wrap: wrap; }
.readout .pill { font-family: var(--sans); font-size: .72rem; font-weight: 500; letter-spacing: .06em;
  padding: .12rem .45rem; border: 1px solid var(--rule-strong); color: var(--ink-2); }
.readout .pill.change { border-color: var(--cursor); color: var(--cursor); }
.readout .reason { font-size: 1rem; line-height: 1.65; max-width: 40em; margin: 0; }
.readout .next { list-style: none; margin: .65rem 0 0; padding: 0; display: grid; gap: .3rem; }
.readout .next li { font-size: .9rem; color: var(--ink-2); display: flex; gap: .55rem; align-items: baseline; }
.readout .next li::before { content: ""; flex: none; width: 10px; height: 1px; background: var(--rule-strong); transform: translateY(-.28em); }
.readout .foot { display: flex; flex-wrap: wrap; gap: .5rem 1.25rem; align-items: center;
  margin: 1.1rem 1.5rem 0; padding-top: .8rem; border-top: 1px dashed var(--rule); }
.fresh { display: inline-flex; align-items: center; gap: .5rem; font-size: .85rem; color: var(--ink-2);
  text-decoration: none; }
.fresh .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--ok); flex: none; }
.fresh.warn .dot { background: var(--warn); } .fresh.bad .dot { background: var(--bad); }
.fresh.warn, .fresh.bad { color: var(--ink); }
.fresh.warn .dot, .fresh.bad .dot { animation: breathe 1.1s ease-in-out 2; }
.fresh a, a.fresh { color: inherit; text-underline-offset: 3px; text-decoration-color: var(--rule-strong); }
.hint { font-size: .85rem; padding: .15rem .5rem; }
.hint.warn { color: var(--warn); background: var(--warn-wash); }
.hint.ok { color: var(--ok); background: var(--ok-wash); }
.issues { margin: .4rem 1.5rem 0; padding: 0; list-style: none; font-size: .85rem; color: var(--ink-2); }
.issues li { padding: .1rem 0; }
@media (max-width: 640px) {
  .readout .body { grid-template-columns: 1fr; padding: 1rem 1rem 0; gap: .9rem; }
  .readout .foot, .issues { margin-left: 1rem; margin-right: 1rem; }
}

/* ---------- ladder ---------- */
.ladder { --pos: 0; display: grid; gap: 1.6rem; }
.ruler { position: relative; padding-top: 2.4rem; }
.ruler .track { position: relative; height: 72px; border-top: 1px solid var(--rule-strong); border-bottom: 1px solid var(--rule-strong); }
.ruler .seg { position: absolute; top: 0; bottom: 0; left: calc(var(--s) * 100%); width: calc((var(--e) - var(--s)) * 100%);
  border-left: 1px solid var(--rule-strong); padding: .35rem .5rem; overflow: hidden;
  background: color-mix(in srgb, var(--tier-color) 16%, transparent); }
.ruler .seg.current { background: color-mix(in srgb, var(--tier-color) 34%, transparent); }
.ruler .seg.flash { animation: flash 900ms var(--ease-out) 1 both; }
.ruler .seg .m { font-family: var(--mono); font-size: 1rem; font-weight: 500; }
.ruler .seg .u { display: block; margin-top: .15rem; font-family: var(--mono); font-size: .7rem; line-height: 1.35; color: var(--ink-2); white-space: nowrap; }
.ruler .ticks { position: absolute; left: 0; right: 0; top: 2.4rem; height: 72px; pointer-events: none;
  right: auto; width: calc(var(--split) * 100%);
  background-image: repeating-linear-gradient(90deg, var(--rule-strong) 0 1px, transparent 1px calc(100% / 35));
  -webkit-mask: linear-gradient(#000 0 7px, transparent 7px); mask: linear-gradient(#000 0 7px, transparent 7px); opacity: .7; }
.ruler .dmark { position: absolute; top: -6px; bottom: -6px; left: calc(var(--s) * 100%); width: 0;
  border-left: 1px dashed var(--ink-2); pointer-events: none; z-index: 1; }
.ruler .dmark.end { border-left-style: solid; }
.ruler .dmark span { position: absolute; bottom: .3rem; left: .3rem; font-size: .66rem; line-height: 1.2; color: var(--ink-2);
  writing-mode: vertical-rl; white-space: nowrap; }
.ruler .track::after { content: ""; position: absolute; top: 0; bottom: 0; left: calc(var(--split) * 100%); right: 0; pointer-events: none;
  background: repeating-linear-gradient(135deg, transparent 0 5px, color-mix(in srgb, var(--ink-2) 14%, transparent) 5px 6px); }
.ruler .labels { position: relative; height: 1.4rem; margin-top: .35rem; }
.ruler .labels span.deep { color: var(--ink-2); opacity: .8; }
.ruler .labels span { position: absolute; left: calc(var(--s) * 100%); transform: translateX(-50%);
  font-family: var(--mono); font-size: .72rem; color: var(--ink-2); }
.ruler .labels span:first-child { transform: none; }
.cursor { position: absolute; top: 0; bottom: 1.75rem; left: calc(var(--p) * 100%); --p: var(--pos); width: 0; z-index: 2; }
.cursor .needle { position: absolute; top: 1.55rem; bottom: 0; left: -1px; width: 2px; background: var(--cursor); }
.cursor .tip { position: absolute; top: 0; left: 0; transform: translateX(-50%); white-space: nowrap;
  font-family: var(--mono); font-size: .85rem; font-weight: 600; color: var(--paper-raised); background: var(--cursor);
  padding: .05rem .4rem; }
.cursor .tip::after { content: ""; position: absolute; left: 50%; bottom: -5px; transform: translateX(-50%);
  border: 5px solid transparent; border-bottom: 0; border-top-color: var(--cursor); }
.cursor.edge-r .tip { transform: translateX(-100%); } .cursor.edge-r .tip::after { left: auto; right: -5px; transform: none; }
.cursor.edge-l .tip { transform: none; } .cursor.edge-l .tip::after { left: -5px; transform: none; }
.cursor.ref .needle { background: repeating-linear-gradient(var(--cursor) 0 4px, transparent 4px 7px); }
.cursor.ref .tip { background: var(--paper-raised); color: var(--cursor); outline: 1px solid var(--cursor); }
.animate .cursor { animation: cursor-in 760ms var(--ease-overshoot) both; }
.sub { display: grid; grid-template-columns: 4.5rem 1fr; gap: .75rem; align-items: center; }
.sub .bar { position: relative; height: 30px; border-bottom: 1px solid var(--rule-strong); }
.sub .bar .mark { position: absolute; bottom: 0; height: 12px; width: 1px; left: calc(var(--x) * 100%); background: var(--rule-strong); }
.sub .bar .mark.active { height: 22px; width: 2px; background: var(--ink); }
.sub .bar .mark span { position: absolute; bottom: 100%; transform: translateX(-50%); font-family: var(--mono);
  font-size: .68rem; color: var(--ink-2); white-space: nowrap; }
.sub .bar .mark.active span { color: var(--ink); font-weight: 600; }
.sub .bar .now { position: absolute; bottom: -5px; left: calc(var(--p) * 100%); --p: var(--x); width: 10px; height: 10px;
  transform: translateX(-50%) rotate(45deg); background: var(--cursor); }
.animate .sub .bar .now { animation: cursor-in 760ms var(--ease-overshoot) 80ms both; }
.sub .read { font-family: var(--mono); font-size: .85rem; color: var(--ink-2); }
.ladder .legend { font-size: .85rem; color: var(--ink-2); margin: 0; }
@media (max-width: 640px) {
  .ruler { padding-top: 0; padding-left: 4.6rem; }
  .ruler .track { height: 420px; border: 0; border-left: 1px solid var(--rule-strong); border-right: 1px solid var(--rule-strong); }
  .ruler .seg { left: 0; right: 0; width: auto; top: calc(var(--s) * 100%); height: calc((var(--e) - var(--s)) * 100%);
    bottom: auto; border-left: 0; border-top: 1px solid var(--rule-strong); display: flex; gap: .6rem; align-items: baseline; flex-wrap: wrap; }
  .ruler .ticks { display: none; }
  .ruler .seg .u { display: inline; margin-top: 0; } .ruler .seg .u br { display: none; }
  .ruler .labels { position: absolute; left: 0; top: 0; width: 4rem; height: 420px; margin: 0; }
  .ruler .labels span { left: auto; right: .4rem; top: calc(var(--s) * 100%); transform: translateY(-50%); }
  .ruler .labels span:first-child { transform: none; }
  .ruler .dmark { top: calc(var(--s) * 100%); bottom: auto; left: -6px; right: -6px; width: auto; height: 0;
    border-left: 0; border-top: 1px dashed var(--ink-2); }
  .ruler .dmark.end { border-top-style: solid; }
  .ruler .dmark span { writing-mode: horizontal-tb; bottom: auto; top: .15rem; left: auto; right: .5rem; }
  .ruler .track::after { left: 0; right: 0; top: calc(var(--split) * 100%); bottom: 0;
    background: repeating-linear-gradient(45deg, transparent 0 5px, color-mix(in srgb, var(--ink-2) 14%, transparent) 5px 6px); }
  .cursor { left: 4.6rem; right: 0; top: calc(var(--p) * 420px); bottom: auto; width: auto; height: 0; }
  .cursor .needle { top: -1px; left: 0; right: 0; bottom: auto; width: auto; height: 2px; }
  .cursor .tip, .cursor.edge-r .tip, .cursor.edge-l .tip { left: auto; right: 0; top: 0; transform: translateY(-50%); }
  .cursor .tip::after, .cursor.edge-r .tip::after, .cursor.edge-l .tip::after { display: none; }
  .cursor.ref .needle { background: repeating-linear-gradient(90deg, var(--cursor) 0 4px, transparent 4px 7px); }
}

/* ---------- indicator groups ---------- */
.groups { display: grid; grid-template-columns: 3fr 2fr; gap: 1.5rem; }
.group { border-top: 2px solid var(--ink); padding-top: .6rem; }
.group.ref { border-top: 1px solid var(--rule-strong); }
.group header { display: flex; align-items: baseline; justify-content: space-between; gap: .75rem; margin-bottom: .5rem; }
.group header h3 { font-family: var(--cjk); font-size: .95rem; font-weight: 600; margin: 0; padding: 0; color: var(--ink); }
.group .tag { font-size: .75rem; color: var(--ink-2); border: 1px solid var(--rule-strong); padding: .05rem .4rem; }
.group .rows { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 1.25rem; }
.group.ref .rows { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.gauge { padding: .7rem 0; border-bottom: 1px solid var(--rule); }
.gauge .v { font-family: var(--mono); font-variant-numeric: tabular-nums; font-size: 1.85rem; font-weight: 500; line-height: 1.1; margin-top: .2rem; }
.group.ref .gauge .v { font-size: 1.35rem; color: var(--ink-2); }
.gauge .lab { font-size: .85rem; font-weight: 600; display: flex; gap: .5rem; align-items: baseline; }
.gauge .lab .etch { font-weight: 500; }
.gauge .d { font-size: .8rem; color: var(--ink-2); margin-top: .25rem; line-height: 1.5; }
.gauge .d .mono { color: var(--ink); }
@media (max-width: 760px) { .groups { grid-template-columns: 1fr; } }

/* ---------- top-up ---------- */
.topup { border: 1px solid var(--rule-strong); background: var(--paper); padding: 1rem 1.5rem 1.1rem; }
.topup .tp-head { display: flex; align-items: baseline; gap: 1rem; flex-wrap: wrap; }
.topup .tp-amount { font-family: var(--mono); font-variant-numeric: tabular-nums; font-size: 2rem; font-weight: 500; line-height: 1; }
.topup .tp-amount.na { color: var(--ink-2); font-size: 1.4rem; }
.topup .tp-note { font-size: .9rem; color: var(--ink-2); }
.topup .tp-rows { list-style: none; margin: .8rem 0 0; padding: 0; border-top: 1px solid var(--rule); }
.topup .tp-rows li { display: flex; justify-content: space-between; align-items: baseline; gap: 1rem; padding: .5rem 0; border-bottom: 1px solid var(--rule); }
.topup .tp-rows li.muted { color: var(--ink-2); }
.topup .tp-rows .f { font-weight: 600; display: flex; gap: .6rem; align-items: baseline; flex-wrap: wrap; }
.topup .tp-rows .p { font-weight: 400; font-size: .8rem; color: var(--ink-2); }
.topup .tp-rows .a { font-size: 1.1rem; font-weight: 600; color: var(--cursor); white-space: nowrap; }
.topup .tp-gap { margin: .6rem 0 0; font-size: .85rem; color: var(--warn); background: var(--warn-wash); padding: .3rem .5rem; }
.topup .tp-run { margin: .8rem 0 0; font-size: .85rem; color: var(--ink-2); }
.topup .tp-run.warn { color: var(--warn); }
.topup .tp-run.accent { color: var(--ink); }
.topup .tp-head .was { font-family: var(--mono); font-size: 1.1rem; color: var(--ink-2); text-decoration: line-through; }
.topup .tp-auto { margin: .8rem 0 0; font-size: .85rem; color: var(--ink-2); }
.topup .tp-auto .etch { margin-right: .6rem; }
.topup .tp-banner { margin: .7rem 0 0; font-size: .9rem; padding: .4rem .6rem; }
.topup .tp-banner.warn { color: var(--warn); background: var(--warn-wash); }
.topup .tp-tier { margin: .7rem 0 0; font-size: .88rem; color: var(--ink-2); }
.topup .tp-tier.change { color: var(--paper-raised); background: var(--cursor); padding: .45rem .6rem; font-weight: 600;
  animation: flash-in 900ms var(--ease-out) 1 both; }
.topup .tp-rows .was { font-size: .85rem; font-weight: 400; color: var(--ink-2); margin-right: .5rem; text-decoration: line-through; }
.tiers-wrap { overflow-x: auto; }
.tiers td.moved { color: var(--warn); }
@media (max-width: 640px) { .topup { padding: .9rem 1rem 1rem; } }
.tiers { width: 100%; border-collapse: collapse; font-size: .88rem; }
.tiers th { text-align: left; font-family: var(--sans); font-size: .72rem; font-weight: 500; letter-spacing: .08em; color: var(--ink-2); padding: .3rem .5rem; border-bottom: 1px solid var(--rule-strong); }
.tiers td { padding: .45rem .5rem; border-bottom: 1px solid var(--rule); vertical-align: baseline; }
.tiers td.m { width: 5.5rem; white-space: nowrap; }
.tiers td.m::before { content: ""; display: inline-block; width: 8px; height: 8px; margin-right: .45rem; background: var(--tier-color); }
.tiers td.t { width: 6rem; }
.tiers tr.current td { background: color-mix(in srgb, var(--tier-color) 22%, transparent); font-weight: 600; }
.tiers .gap { margin-left: .6rem; color: var(--warn); font-size: .8rem; }

/* ---------- motion ---------- */
@keyframes cursor-in { from { --p: 0; } }
@keyframes flash-in { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: none; } }
@keyframes breathe { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: .35; transform: scale(1.5); } }
@keyframes flash { 0% { background: color-mix(in srgb, var(--cursor) 70%, transparent); } 100% { background: color-mix(in srgb, var(--tier-color) 34%, transparent); } }
@media (prefers-reduced-motion: reduce) {
  .animate .cursor, .animate .sub .bar .now, .ruler .seg.flash, .fresh .dot, .topup .tp-tier.change { animation: none !important; }
}
"""


def global_style():
    return f"<style>@import url('{FONT_IMPORT}');{GLOBAL_CSS}</style>"
