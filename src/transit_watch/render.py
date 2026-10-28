"""Two images per event, rendered as HTML and captured with headless Chrome:
a map (centerlines, visibility path, home, spot) and a disk preview (zenith up, the station drawn to scale
at the camera's frame rate)."""
import html
import json
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .geo import in_japan, local_xy, from_local

TILES = {
    "gsi": ("https://cyberjapandata.gsi.go.jp/xyz/std/{z}/{x}/{y}.png", "地理院タイル", 18),
    "esri": ("https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
             "Tiles © Esri", 19),
}
CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome",
]


def find_chrome(configured=""):
    for c in ([configured] if configured else []) + CHROME_CANDIDATES:
        if os.path.isfile(c) or shutil.which(c):
            return c if os.path.isfile(c) else shutil.which(c)
    return None


def screenshot(chrome, html_text, png, size):
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp, "page.html")
        src.write_text(html_text)
        subprocess.run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--user-data-dir={tmp}/profile",
                        f"--screenshot={png}", f"--window-size={size[0]},{size[1]}", "--virtual-time-budget=20000",
                        "--force-device-scale-factor=2", src.as_uri()], capture_output=True, timeout=180)
    return png


def render(e, home, stem, S, chrome, fps=20, tiles="auto"):
    stem.parent.mkdir(parents=True, exist_ok=True)
    return [screenshot(chrome, map_html(e, home, S, tiles), stem.with_name(stem.name + "-map.png"), (1400, 700)),
            screenshot(chrome, disk_html(e, S, fps), stem.with_name(stem.name + "-disk.png"), (800, 900))]


# ---------- map ----------

def band_edges(line, origin, half_km):
    xy = local_xy(line, origin)
    edges = ([], [])
    for i, (x, y) in enumerate(xy):
        x0, y0 = xy[max(i - 1, 0)]
        x1, y1 = xy[min(i + 1, len(xy) - 1)]
        n = math.hypot(x1 - x0, y1 - y0) or 1
        nx, ny = -(y1 - y0) / n * half_km, (x1 - x0) / n * half_km
        edges[0].append(list(from_local(x + nx, y + ny, origin)))
        edges[1].append(list(from_local(x - nx, y - ny, origin)))
    return edges


def map_html(e, home, S, tiles="auto"):
    spot = e["spot"]
    key = tiles if tiles in TILES else ("gsi" if in_japan(*spot) else "esri")
    url, attr, native = TILES[key]
    edges = band_edges(e["line"], spot, e["width"] / 2) if e["line"] else ([], [])
    data = json.dumps({"line": e["line"], "edges": edges, "home": home, "spot": spot, "tfline": e.get("tf_line") or [],
                       "home_label": e["home_name"], "spot_label": S["spot"]})
    target = S["sun_word"] if e["target"] == "S" else S["moon_word"]
    title = html.escape(S["map_title"].format(time=f"{e['time']:%Y-%m-%d %H:%M:%S}", sat=e["sat"], target=target,
                                              size=e["size"], dist=e["dist_cl"], width=e["width"], home=e["home_name"]))
    legend = f'<span style="color:#d01010">{html.escape(S["legend_main"].format(model=S["mode"][e["model"]].strip()))}</span>'
    if e.get("tf_line"):
        legend += f'　<span style="color:#ff8c00">{html.escape(S["legend_cmp"].format(model=S["mode"][e["cmp_model"]].strip()))}</span>'
    return f"""<!doctype html><meta charset="utf-8">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
body{{margin:0;font:15px -apple-system,"Hiragino Sans","PingFang SC","Noto Sans CJK SC",sans-serif;background:#fff}}
#t{{height:40px;line-height:40px;padding:0 14px;font-weight:600;white-space:nowrap;overflow:hidden}}
#w{{display:flex;gap:6px;height:660px}} .m{{flex:1}}
.lbl{{background:#fff;border:1px solid #333;border-radius:3px;padding:1px 5px;font-size:12px;white-space:nowrap}}
</style>
<div id="t">{title}<span style="font-weight:400;font-size:13px;margin-left:16px">{legend}</span></div>
<div id="w"><div id="a" class="m"></div><div id="b" class="m"></div></div>
<script>
const D={data};
function draw(id, zoomed){{
  const m=L.map(id,{{zoomControl:false}});
  L.tileLayer("{url}",{{maxNativeZoom:{native},maxZoom:19,attribution:"{attr}"}}).addTo(m);
  if(D.edges[0].length){{
    L.polygon(D.edges[0].concat(D.edges[1].slice().reverse()),{{stroke:false,fillColor:"#e03030",fillOpacity:.22}}).addTo(m);
    L.polyline(D.line,{{color:"#d01010",weight:2}}).addTo(m);
  }}
  if(D.tfline.length) L.polyline(D.tfline,{{color:"#ff8c00",weight:2,dashArray:"6,6"}}).addTo(m);
  L.circleMarker(D.home,{{radius:7,color:"#fff",weight:2,fillColor:"#1565c0",fillOpacity:1}}).addTo(m)
    .bindTooltip(D.home_label,{{permanent:true,direction:"right",className:"lbl"}});
  L.circleMarker(D.spot,{{radius:7,color:"#fff",weight:2,fillColor:"#d01010",fillOpacity:1}}).addTo(m)
    .bindTooltip(D.spot_label+" "+D.spot[0].toFixed(5)+", "+D.spot[1].toFixed(5),{{permanent:true,direction:"right",className:"lbl"}});
  if(zoomed){{ m.setView(D.spot, 13); }}
  else {{ L.polyline([D.home,D.spot],{{color:"#1565c0",weight:1.5,dashArray:"5,5"}}).addTo(m);
          m.fitBounds(L.latLngBounds([D.home,D.spot]).pad(0.5)); }}
  L.control.scale({{imperial:false,position:"bottomleft"}}).addTo(m);
}}
draw("a",false); draw("b",true);
</script>"""


# ---------- disk ----------

def screen_deg(phi):
    """Direction phi degrees counter-clockwise from zenith in a zenith-up image -> SVG angle (clockwise from +x)."""
    return math.degrees(math.atan2(-math.cos(math.radians(phi)), -math.sin(math.radians(phi))))


def station(sat, px, rot):
    """Silhouette spanning px pixels; the ISS truss lies across the direction of motion."""
    s = px / 2
    if sat == "ISS":
        panels = "".join(f'<rect x="{x:.2f}" y="{-s * 0.42:.2f}" width="{s * 0.22:.2f}" height="{s * 0.84:.2f}"/>'
                         for x in (-s, -s + s * 0.28, s - s * 0.22, s - s * 0.5))
        body = (f'<rect x="{-s:.2f}" y="{-s * 0.03:.2f}" width="{2 * s:.2f}" height="{s * 0.06:.2f}"/>'
                f'<rect x="{-s * 0.07:.2f}" y="{-s * 0.5:.2f}" width="{s * 0.14:.2f}" height="{s:.2f}"/>' + panels)
    else:
        body = (f'<rect x="{-s:.2f}" y="{-s * 0.15:.2f}" width="{2 * s:.2f}" height="{s * 0.3:.2f}"/>'
                f'<rect x="{-s * 0.12:.2f}" y="{-s * 0.35:.2f}" width="{s * 0.24:.2f}" height="{s * 0.7:.2f}"/>')
    return f'<g transform="rotate({rot:.2f})">{body}</g>'


def disk_html(e, S, fps=20):
    W, R, C = 800, 320, 400
    sun = e["target"] == "S"
    scale = R / (e["target_size"] * 30)               # px per arcsec
    sta_px = e["size"] * scale
    track = screen_deg(e["motion_dir"])
    dur = e["target_size"] / e["ang_vel"]
    v_px = e["ang_vel"] * 60 * scale                  # px per second

    if sun:
        bg = "#9fc4e8"
        disk = ('<defs><radialGradient id="g"><stop offset="0" stop-color="#fffbe8"/><stop offset=".75" stop-color="#ffe9a8"/>'
                f'<stop offset="1" stop-color="#f2a640"/></radialGradient></defs><circle r="{R}" fill="url(#g)"/>')
        sil = "#111"
    else:
        bg = "#05070d" if e["sun_alt"] < -6 else "#2b3a5c" if e["sun_alt"] < 0 else "#7fa6d6"
        k = e["illum"]
        a = R * abs(2 * k - 1)
        lit = (f'<path d="M0 {-R} A{R} {R} 0 0 1 0 {R} A{a:.2f} {R} 0 0 {1 if k > 0.5 else 0} 0 {-R}Z" '
               f'fill="#e9e6dc" transform="rotate({screen_deg(e["limb_dir"]):.2f})"/>')
        disk = f'<circle r="{R}" fill="#2a2a2e" opacity=".9"/>{lit}'
        sil = "#000"

    # one silhouette per camera frame; frame 0 is the center instant, drawn up to one frame off the disk
    dt_s = 1 / fps
    n = int(R / (v_px * dt_s)) + 1
    frames = 2 * (n - 1) + 1
    ux, uy = math.cos(math.radians(track)), math.sin(math.radians(track))
    ghosts = "".join(
        f'<g transform="translate({ux * v_px * dt_s * i:.2f},{uy * v_px * dt_s * i:.2f})" opacity="{1 if i == 0 else .45}" '
        f'fill="{sil}">{station(e["sat"], sta_px, track + 90)}</g>' for i in range(-n, n + 1))
    Lt = R * 1.18
    path = (f'<line x1="{-ux * Lt:.1f}" y1="{-uy * Lt:.1f}" x2="{ux * Lt:.1f}" y2="{uy * Lt:.1f}" stroke="#d01010" '
            'stroke-width="1.5" stroke-dasharray="6 6" opacity=".8"/>'
            f'<polygon points="0,-9 18,0 0,9" fill="#d01010" transform="translate({ux * Lt:.1f},{uy * Lt:.1f}) rotate({track:.1f})"/>')

    fg = "#111" if (sun or e["sun_alt"] >= 0) else "#ddd"
    inset = (f'<g transform="translate({C - 110},{C - 100})"><rect x="-95" y="-95" width="190" height="195" rx="6" '
             f'fill="{"#fff1c9" if sun else "#e9e6dc"}" stroke="{fg}" stroke-opacity=".4"/>'
             f'<g fill="#000" transform="translate(0,-8)">{station(e["sat"], 120, track + 90)}</g>'
             f'<text x="0" y="86" text-anchor="middle" font-size="12" fill="#333">'
             f'{html.escape(S["zoom"].format(sat=e["sat"], zoom=120 / sta_px))}</text></g>')
    title = html.escape(f"{e['time']:%Y-%m-%d %H:%M:%S}  {e['sat']}  " + (S["sun"] if sun else S["moon"]).split(" ", 1)[1])
    info = html.escape(S["disk_info"].format(
        sat=e["sat"], size=e["size"], body=S["sun_word"] if sun else S["moon_word"], body_size=e["target_size"],
        illum="" if sun else S["disk_illum"].format(illum=round(e["illum"] * 100)), dur=dur, fps=fps, frames=frames))
    note = html.escape(S["disk_note"].format(alt=e["alt"], az=e["az"]))
    return f"""<!doctype html><meta charset="utf-8">
<style>body{{margin:0;background:{bg};font:15px -apple-system,"Hiragino Sans","PingFang SC","Noto Sans CJK SC",sans-serif;color:{fg}}}
.h{{padding:12px 16px 0;font-weight:600;font-size:17px}} .s{{padding:4px 16px 0;font-size:13px;opacity:.85}}</style>
<div class="h">{title}</div>
<div class="s">{info}</div>
<div class="s">{note}</div>
<svg width="{W}" height="{W}" viewBox="{-C} {-C} {W} {W}">
  <g transform="translate(0,10)">{disk}{path}{ghosts}</g>
  {inset}
  <g transform="translate({-C + 30},{-C + 40})" fill="{fg}" stroke="{fg}">
    <line x1="0" y1="34" x2="0" y2="4" stroke-width="2"/><polygon points="0,-4 -6,8 6,8" stroke="none"/>
    <text x="10" y="24" stroke="none" font-size="13">{html.escape(S["zenith"])}</text>
  </g>
</svg>"""
