"""Build reports/FLY_TAMAGOTCHI_GUIDE.pdf from reports/guide/guide.html.

Fills in the diagrams (SVG), the membrane-voltage figure (from lif_trace.json, made with
the project's own simulator), the MN9 bar chart (numbers from reports/PHASE_1_REPORT.md),
a real tick from the recorded session, the commit and the date, then prints the page to
PDF with headless Chrome/Edge over the DevTools protocol.

Usage: python reports/guide/build_guide.py
"""

from __future__ import annotations

import asyncio
import base64
import datetime as dt
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

from websockets.asyncio.client import connect  # noqa: E402

from server.validate_dashboard import Cdp, find_chrome, page_ws_url, start_chrome  # noqa: E402

OUT_PDF = ROOT / "reports" / "FLY_TAMAGOTCHI_GUIDE.pdf"
INK, MUTED, LINE, ACCENT = "#1b2330", "#5b6576", "#d9dee6", "#2a5fb0"
SUGAR, BITTER, MN9 = "#1f9e62", "#9b43c9", "#c97d0a"
# Two-series palette for the bar chart, checked with the dataviz validator
# (light surface: lightness, chroma, CVD separation, contrast all pass).
REAL, SHUFFLED = "#2a78d6", "#eb6834"


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ------------------------------------------------------------------ figures
def lif_svg() -> str:
    d = json.loads((HERE / "lif_trace.json").read_text())
    v, step = d["v"], d["dt_ms"]
    W, H, L, R, T, B = 640, 230, 52, 16, 14, 34
    t_max, v_lo, v_hi = len(v) * step, -55.0, -40.0
    x = lambda t: L + (W - L - R) * t / t_max  # noqa: E731
    y = lambda mv: T + (H - T - B) * (v_hi - mv) / (v_hi - v_lo)  # noqa: E731
    pts = " ".join(f"{x(i * step):.1f},{y(val):.1f}" for i, val in enumerate(v))
    out = [f'<svg class="diagram" viewBox="0 0 {W} {H}" role="img" aria-label="Membrane voltage of one model neuron over 200 ms">']
    for mv in (-54, -52, -48, -44, -40):
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{y(mv):.1f}" y2="{y(mv):.1f}" stroke="{LINE}" stroke-width="1"/>')
        out.append(f'<text x="{L - 6}" y="{y(mv) + 4:.1f}" font-size="11" text-anchor="end" fill="{MUTED}">{mv}</text>')
    for t in range(0, 201, 50):
        out.append(f'<text x="{x(t):.1f}" y="{H - 14}" font-size="11" text-anchor="middle" fill="{MUTED}">{t}</text>')
    out.append(f'<text x="{(L + W - R) / 2}" y="{H - 1}" font-size="11" text-anchor="middle" fill="{MUTED}">time (ms)</text>')
    out.append(f'<text x="12" y="{T + 2}" font-size="11" fill="{MUTED}" transform="rotate(-90 12 {T + 2})" text-anchor="end">mV</text>')
    out.append(f'<line x1="{L}" x2="{W - R}" y1="{y(-45):.1f}" y2="{y(-45):.1f}" stroke="{MN9}" stroke-width="1.5" stroke-dasharray="5 4"/>')
    out.append(f'<text x="{W - R}" y="{y(-45) - 5:.1f}" font-size="11" text-anchor="end" fill="{INK}">threshold −45 mV</text>')
    out.append(f'<text x="{L + 4}" y="{y(-52) + 14:.1f}" font-size="11" fill="{INK}">rest −52 mV (reset after each spike)</text>')
    for s in d["spikes_ms"]:
        out.append(f'<line x1="{x(s):.1f}" x2="{x(s):.1f}" y1="{y(-45):.1f}" y2="{T:.1f}" stroke="{ACCENT}" stroke-width="2" stroke-linecap="round"/>')
    out.append(f'<polyline points="{pts}" fill="none" stroke="{ACCENT}" stroke-width="1.6" stroke-linejoin="round"/>')
    out.append(f'<text x="{x(d["spikes_ms"][0]) + 6:.1f}" y="{T + 10}" font-size="11" fill="{INK}">spike</text>')
    out.append("</svg>")
    return "".join(out)


def bars_svg() -> str:
    # MN9 primary, 5 seeds, full brain: reports/PHASE_1_REPORT.md "Validation".
    conds = [("Sugar", (85.8, 5.8), (0.0, 0.0)),
             ("Sugar + bitter", (9.6, 3.2), (0.0, 0.0)),
             ("Bitter only", (0.0, 0.0), (0.0, 0.0))]
    W, H, L, R, T, B = 640, 250, 52, 16, 40, 36
    y_max = 100.0
    y = lambda hz: T + (H - T - B) * (1 - hz / y_max)  # noqa: E731
    gw = (W - L - R) / len(conds)
    bw = 46
    out = [f'<svg class="diagram" viewBox="0 0 {W} {H}" role="img" aria-label="MN9 firing rate, real vs shuffled brain">']
    # legend (two series, also direct-labelled on the first group)
    out.append(f'<rect x="{L}" y="8" width="12" height="12" rx="3" fill="{REAL}"/><text x="{L + 18}" y="18" font-size="12" fill="{INK}">Real FlyWire wiring</text>')
    out.append(f'<rect x="{L + 170}" y="8" width="12" height="12" rx="3" fill="{SHUFFLED}"/><text x="{L + 188}" y="18" font-size="12" fill="{INK}">Shuffled wiring (control)</text>')
    for hz in (0, 20, 40, 60, 80, 100):
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{y(hz):.1f}" y2="{y(hz):.1f}" stroke="{LINE}" stroke-width="1"/>')
        out.append(f'<text x="{L - 6}" y="{y(hz) + 4:.1f}" font-size="11" text-anchor="end" fill="{MUTED}">{hz}</text>')
    out.append(f'<text x="12" y="{T}" font-size="11" fill="{MUTED}" transform="rotate(-90 12 {T})" text-anchor="end">MN9 rate (Hz)</text>')
    # the eating line used by the game
    out.append(f'<line x1="{L}" x2="{W - R}" y1="{y(20):.1f}" y2="{y(20):.1f}" stroke="{INK}" stroke-width="1" stroke-dasharray="4 4"/>')
    out.append(f'<text x="{W - R}" y="{y(20) - 5:.1f}" font-size="11" text-anchor="end" fill="{INK}">eating line, 20 Hz</text>')
    base = y(0)
    for i, (name, real, shuf) in enumerate(conds):
        cx = L + gw * i + gw / 2
        for j, ((m, sd), color) in enumerate(((real, REAL), (shuf, SHUFFLED))):
            bx = cx - bw - 1 + j * (bw + 2)
            top = y(m)
            h = max(0.0, base - top)
            if h >= 4:
                out.append(f'<path d="M{bx},{base} V{top + 4} q0,-4 4,-4 H{bx + bw - 4} q4,0 4,4 V{base} Z" fill="{color}"/>')
            else:
                out.append(f'<rect x="{bx}" y="{base - 2}" width="{bw}" height="2" fill="{color}"/>')
            if sd > 0:
                bxc = bx + bw / 2
                out.append(f'<line x1="{bxc}" x2="{bxc}" y1="{y(m + sd):.1f}" y2="{y(m - sd):.1f}" stroke="{INK}" stroke-width="1.2"/>')
                out.append(f'<line x1="{bxc - 5}" x2="{bxc + 5}" y1="{y(m + sd):.1f}" y2="{y(m + sd):.1f}" stroke="{INK}" stroke-width="1.2"/>')
            label = f"{m:.1f}" if m else "0"
            ly = min(y(m + sd), base) - 6
            out.append(f'<text x="{bx + bw / 2}" y="{ly:.1f}" font-size="11" text-anchor="middle" fill="{INK}">{label}</text>')
        out.append(f'<text x="{cx}" y="{H - 12}" font-size="12" text-anchor="middle" fill="{INK}">{name}</text>')
    out.append("</svg>")
    return "".join(out)


def box(x, y, w, h, title, sub="", fill="#fff", stroke=INK, title_color=INK):
    s = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{fill}" stroke="{stroke}" stroke-width="1.4"/>'
    s += f'<text x="{x + w / 2}" y="{y + (h / 2 if not sub else h / 2 - 6)}" font-size="14" font-weight="700" text-anchor="middle" fill="{title_color}">{title}</text>'
    for k, line in enumerate(sub.split("\n") if sub else []):
        s += f'<text x="{x + w / 2}" y="{y + h / 2 + 12 + 14 * k}" font-size="11" text-anchor="middle" fill="{MUTED}">{esc(line)}</text>'
    return s


def arrow(x1, y1, x2, y2, label="", color=INK, above=True, dash=False):
    s = (f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="1.6" '
         f'marker-end="url(#ah)"{" stroke-dasharray=\"5 4\"" if dash else ""}/>')
    if label:
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2 + (-7 if above else 15)
        s += f'<text x="{mx}" y="{my}" font-size="11" text-anchor="middle" fill="{INK}">{esc(label)}</text>'
    return s


DEFS = (f'<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        f'<path d="M0,0 L10,5 L0,10 z" fill="{INK}"/></marker></defs>')


def arch_svg() -> str:
    W, H = 640, 300
    s = [f'<svg class="diagram" viewBox="0 0 {W} {H}" role="img" aria-label="Architecture">', DEFS]
    s.append(box(10, 30, 135, 110, "iPhone", "web/phone/\ntap, shake, camera\nvibrates on eating", fill="#fbfcfe"))
    s.append(box(252, 20, 136, 130, "Server", "server/ (FastAPI)\nevents → rates\ntimers, readouts\nbroadcasts", fill="#fbfcfe"))
    s.append(box(495, 30, 135, 110, "Dashboard", "web/dashboard/\nfly, brain, meters\nchart, sound", fill="#fbfcfe"))
    s.append(box(252, 200, 136, 92, "Brain", "brain/ LIF model\n19,698 neurons\n50 ms chunks", fill="#eef3fb", stroke=ACCENT))
    s.append(arrow(145, 62, 252, 62, "sugar, bitter, light"))
    s.append(arrow(252, 108, 145, 108, "status 5 Hz", above=False))
    s.append(arrow(388, 62, 495, 62, "tick 20 Hz"))
    s.append(arrow(495, 108, 388, 108, "reset_brain", above=False))
    s.append(arrow(300, 150, 300, 200))
    s.append(f'<text x="292" y="180" font-size="11" text-anchor="end" fill="{INK}">input rates</text>')
    s.append(arrow(340, 200, 340, 150))
    s.append(f'<text x="348" y="180" font-size="11" fill="{INK}">spikes</text>')
    s.append(f'<text x="77" y="162" font-size="11" text-anchor="middle" fill="{MUTED}">WebSocket /ws/phone</text>')
    s.append(f'<text x="562" y="162" font-size="11" text-anchor="middle" fill="{MUTED}">WebSocket /ws/dashboard</text>')
    s.append("</svg>")
    return "".join(s)


def taste_svg() -> str:
    W, H = 640, 150
    s = [f'<svg class="diagram" viewBox="0 0 {W} {H}" role="img" aria-label="Taste to feeding pathway">', DEFS]
    s.append(box(10, 12, 150, 52, "Sugar GRNs (21)", fill="#eaf6f0", stroke=SUGAR))
    s.append(box(10, 86, 150, 52, "Bitter GRNs (21)", fill="#f4ecf9", stroke=BITTER))
    s.append(box(245, 30, 160, 90, "Thousands of", "intermediate neurons\n(the connectome)", fill="#fbfcfe"))
    s.append(box(490, 45, 140, 60, "MN9", "feeding motor neuron", fill="#fdf5e7", stroke=MN9))
    s.append(arrow(160, 38, 245, 58, "excite", color=SUGAR))
    s.append(arrow(160, 112, 245, 92, color=BITTER))
    s.append(f'<text x="200" y="130" font-size="11" text-anchor="middle" fill="{INK}">inhibit, via paths</text>')
    s.append(arrow(405, 75, 490, 75, "fires → eats"))
    s.append("</svg>")
    return "".join(s)


def timeline_svg() -> str:
    W, H = 640, 175
    L, R = 20, 20
    t_max = 260.0
    x = lambda t: L + (W - L - R) * t / t_max  # noqa: E731
    s = [f'<svg class="diagram" viewBox="0 0 {W} {H}" role="img" aria-label="Timeline of one tap">', DEFS]
    s.append(f'<line x1="{L}" x2="{W - R}" y1="120" y2="120" stroke="{INK}" stroke-width="1.4"/>')
    for t in range(0, 261, 50):
        s.append(f'<line x1="{x(t)}" x2="{x(t)}" y1="116" y2="124" stroke="{INK}"/>')
        s.append(f'<text x="{x(t)}" y="140" font-size="11" text-anchor="middle" fill="{MUTED}">{t} ms</text>')
    # chunk bands
    for k in range(5):
        s.append(f'<rect x="{x(10 + 50 * k)}" y="94" width="{x(58 + 50 * k) - x(10 + 50 * k)}" height="18" rx="4" fill="#eef3fb" stroke="{ACCENT}" stroke-width="0.8"/>')
        s.append(f'<text x="{(x(10 + 50 * k) + x(58 + 50 * k)) / 2}" y="107" font-size="10" text-anchor="middle" fill="{ACCENT}">chunk {k + 1}</text>')
    events = [(0, "tap: phone sends sugar", 20), (8, "server: timer on", 44),
              (10, "sugar GRNs at 150 Hz", 68)]
    for t, label, yy in events:
        s.append(f'<line x1="{x(t)}" x2="{x(t)}" y1="{yy + 4}" y2="116" stroke="{MUTED}" stroke-dasharray="2 3"/>')
        s.append(f'<circle cx="{x(t)}" cy="{yy}" r="4" fill="{SUGAR}"/>')
        s.append(f'<text x="{x(t) + 9}" y="{yy + 4}" font-size="11" fill="{INK}">{esc(label)}</text>')
    s.append(f'<rect x="{x(116)}" y="30" width="{x(251) - x(116)}" height="22" rx="6" fill="#fdf5e7" stroke="{MN9}"/>')
    s.append(f'<text x="{(x(116) + x(251)) / 2}" y="45" font-size="11" text-anchor="middle" fill="{INK}">phone shows eating (116–251 ms)</text>')
    s.append(f'<text x="{x(135)}" y="75" font-size="11" fill="{MUTED}">MN9 climbs; its 500 ms average crosses 20 Hz</text>')
    s.append(f'<text x="{L}" y="165" font-size="11" fill="{MUTED}">Each chunk: 50 ms of brain time computed in ~8 ms, then a tick to the dashboard; every 4th tick also goes to the phone.</text>')
    s.append("</svg>")
    return "".join(s)


def tick_json() -> str:
    sample = ROOT / "web" / "dashboard" / "samples" / "session.jsonl"
    for line in sample.read_text(encoding="utf-8").splitlines():
        m = json.loads(line)["msg"]
        if m.get("type") == "tick" and m["game"]["eating"] and m["group_counts"]["mn9_primary"] > 0:
            break
    else:
        raise SystemExit("no eating tick in the sample")
    m["spiking_ids"] = m["spiking_ids"][:2] + ["..."]
    m["group_rates_hz"] = {k: round(v, 1) for k, v in m["group_rates_hz"].items()}
    m["game"]["mn9_rate_hz"] = round(m["game"]["mn9_rate_hz"], 1)
    m["perf"] = {k: round(v, 1) for k, v in m["perf"].items()}
    m["server_time_ms"] = round(m["server_time_ms"])
    lines = [f' "{k}": {json.dumps(v)}' for k, v in m.items()]
    return esc("{\n" + ",\n".join(lines) + "\n}")


# ------------------------------------------------------------------ build
def build_html() -> Path:
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True).stdout.strip() or "unknown"
    html = (HERE / "guide.html").read_text(encoding="utf-8")
    fills = {
        "{{COMMIT}}": commit,
        "{{DATE}}": dt.date.today().strftime("%d %B %Y").lstrip("0"),
        "{{LIF_SVG}}": lif_svg(),
        "{{BARS_SVG}}": bars_svg(),
        "{{ARCH_SVG}}": arch_svg(),
        "{{ARCH_TASTE_SVG}}": taste_svg(),
        "{{TIMELINE_SVG}}": timeline_svg(),
        "{{TICK_JSON}}": tick_json(),
    }
    for k, v in fills.items():
        if k not in html:
            raise SystemExit(f"placeholder {k} missing from guide.html")
        html = html.replace(k, v)
    out = HERE / "guide_built.html"
    out.write_text(html, encoding="utf-8")
    return out


FOOTER = ('<div style="width:100%;font:8px \'Segoe UI\',sans-serif;color:#5b6576;padding:0 18mm;'
          'display:flex;justify-content:space-between"><span>Fly Tamagotchi, explained</span>'
          '<span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>')


async def print_pdf(html: Path) -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as prof:
        proc = start_chrome(find_chrome(None), prof)
        try:
            async with connect(page_ws_url(), max_size=None) as ws:
                cdp = Cdp(ws)
                await cdp.call("Page.enable")
                await cdp.call("Runtime.enable")
                await cdp.call("Page.navigate", url=html.as_uri())
                await asyncio.sleep(1.0)
                await cdp.eval("document.fonts.ready.then(() => new Promise(r => setTimeout(r, 800))).then(() => true)")
                await cdp.eval("Promise.all([...document.images].map(i => i.complete ? 1 : new Promise(r => i.onload = i.onerror = r))).then(() => true)")
                r = await cdp.call("Page.printToPDF", printBackground=True, preferCSSPageSize=True,
                                   displayHeaderFooter=True, headerTemplate="<div></div>",
                                   footerTemplate=FOOTER)
                OUT_PDF.write_bytes(base64.b64decode(r["data"]))
        finally:
            proc.terminate()
            proc.wait(timeout=30)


def main() -> int:
    html = build_html()
    asyncio.run(print_pdf(html))
    print(f"wrote {OUT_PDF} ({OUT_PDF.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
