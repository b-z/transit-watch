"""The forecast pipeline: find transits, pick the ones worth shooting, place a reachable spot, add weather,
render images and write the report (Markdown + JSON)."""
import datetime as dt
import json
import math
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from skyfield import almanac
from skyfield.api import wgs84

from . import data, geo, render, weather
from .engine import Engine, TFCompatEngine
from .i18n import strings

NAMES = {25544: "ISS", 48274: "Tiangong", 20580: "Hubble"}
ENGINES = {"strict": Engine, "transit-finder": TFCompatEngine}


def grade(e, cfg):
    if not e["is_iss"]:
        return "other"
    g = cfg["grades"]
    s = e["size"]
    return ("excellent" if s >= g["excellent_arcsec"] else "good" if s >= g["good_arcsec"]
            else "fair" if s >= g["fair_arcsec"] else "poor")


def bright_limb_dir(eng, obs_at, t, latlon):
    """Bright limb of the Moon, degrees counter-clockwise from zenith (position-angle sense)."""
    ra_m, dec_m, _ = obs_at.observe(eng.bodies["M"]).apparent().radec(epoch="date")
    ra_s, dec_s, _ = obs_at.observe(eng.bodies["S"]).apparent().radec(epoch="date")
    am, dm, as_, ds = ra_m.radians, dec_m.radians, ra_s.radians, dec_s.radians
    chi = math.atan2(math.cos(ds) * math.sin(as_ - am),
                     math.sin(ds) * math.cos(dm) - math.cos(ds) * math.sin(dm) * math.cos(as_ - am))
    H = math.radians(t.gast * 15 + latlon[1]) - am
    lat = math.radians(latlon[0])
    q = math.atan2(math.sin(H), math.tan(lat) * math.cos(dm) - math.sin(dm) * math.cos(H))
    return math.degrees(chi - q)


def describe(eng, tr, spot, elev, tz):
    """Recompute the center instant and every observable at the spot."""
    sat = next(s for s in eng.sats if s.name == tr.sat)
    tt = eng.ts.tt_jd(tr.t_center.tt + np.arange(-6000, 6001) * 0.01 / 86400)
    t = eng.view_min_sep(sat, tr.target, spot, tt, elev)["t"]
    v = eng.view(sat, tr.target, spot, t, elev)
    o = (eng.earth + wgs84.latlon(spot[0], spot[1], elev)).at(t)
    return {
        "sat": NAMES.get(sat.model.satnum, tr.sat), "norad": sat.model.satnum, "target": tr.target, "t": t,
        "time": t.utc_datetime().astimezone(tz), "size": v["size_arcsec"], "alt": v["alt"], "az": v["az"],
        "range": v["range_km"], "width": v["width_km"] or 0.0, "motion_dir": v["motion_dir"],
        "ang_vel": v["omega_arcmin_s"], "target_size": v["body_arcmin"], "duration": v["duration_s"],
        "illum": float(almanac.fraction_illuminated(eng.eph, "moon", t)) if tr.target == "M" else None,
        "limb_dir": bright_limb_dir(eng, o, t, spot) if tr.target == "M" else None,
        "sun_alt": float(o.observe(eng.bodies["S"]).apparent().altaz()[0].degrees),
        "dist_cl": tr.dist_cl_km, "line": tr.line, "spot": tuple(spot), "elev": elev,
    }


def at_elevation(eng, tr, spot, h, provider):
    """The centerline shifts with the observer's height (about 300 m for 300 m at 40° altitude):
    recompute it at the spot's real elevation until the elevation settles."""
    sat = next(s for s in eng.sats if s.name == tr.sat)
    tr2 = tr
    for _ in range(4):
        cand = eng._refine(sat, tr.target, spot, None, tr.t_center.tt - 90 / 86400, tr.t_center.tt + 90 / 86400, 0.02, 0, h)
        if cand is None:
            break
        tr2, spot = cand, cand.spot
        h2 = geo.elevation_lookup(provider, *spot)
        if h2 is None or abs(h2 - h) < 3:
            return tr2, spot, h if h2 is None else h2
        h = h2
    return tr2, spot, h


def compare(other, e):
    sat = next((s for s in other.sats if s.model.satnum == e["norad"]), None)
    if sat is None:
        return None
    tr = other._refine(sat, e["target"], e["spot"], None, e["t"].tt - 120 / 86400, e["t"].tt + 120 / 86400, 0.02, 0, e["elev"])
    if tr is None:
        return None
    (x, y), = geo.local_xy([tr.spot], e["spot"])
    return {"line": tr.line, "spot": tr.spot, "offset_m": math.hypot(x, y) * 1000, "dir": geo.bearing_index(x, y),
            "time": tr.t_center.utc_datetime()}


def maps_url(p):
    return f"https://www.google.com/maps/search/?api=1&query={p[0]:.5f},{p[1]:.5f}"


def run(cfg, render_images=None, log=print):
    loc, srch, rules = cfg["location"], cfg["search"], cfg["rules"]
    tz = ZoneInfo(loc["timezone"])
    home = (float(loc["latitude"]), float(loc["longitude"]))
    elev0 = float(loc["elevation_m"])
    S = strings(cfg["output"]["language"])
    mode = cfg["model"]["mode"]
    cmp_mode = "transit-finder" if mode == "strict" else "strict"
    provider = cfg["spot"]["land_provider"]

    tle = data.prepare(srch["satellites"])
    eng = ENGINES[mode](tle, data_dir=str(data.DATA_DIR))
    other = ENGINES[cmp_mode](tle, data_dir=str(data.DATA_DIR)) if cfg["model"]["compare_transit_finder"] else None
    iss_id = srch["satellites"][0]

    now = dt.datetime.now(tz)
    t0, t1 = eng.ts.from_datetime(now), eng.ts.from_datetime(now + dt.timedelta(days=srch["days"]))
    max_km = max(r["max_distance_km"] for g in rules.values() for r in g.values())
    found = eng.find(home, t0, t1, travel_km=max_km, min_alt=srch["min_altitude_deg"], elev_m=elev0)

    picks = []
    for tr in found:
        e = describe(eng, tr, tr.spot, elev0, tz)
        e["is_iss"] = e["norad"] == iss_id
        r = rules["iss" if e["is_iss"] else "other"]["sun" if e["target"] == "S" else "moon"]
        if e["size"] < r["min_size_arcsec"] or e["dist_cl"] > r["max_distance_km"] or e["alt"] < srch["min_altitude_deg"]:
            continue
        if e["target"] == "M" and (e["illum"] or 0) < r.get("min_illumination", 0):
            continue
        land = geo.nearest_land_on_line(tr.line, home, provider, max_search_km=cfg["spot"]["max_search_km"])
        if land:
            tr_h, spot, h = at_elevation(eng, tr, land[1:3], land[3], provider)
            dist_cl = e["dist_cl"]
            e = describe(eng, tr_h, spot, h, tz)
            e["is_iss"], e["dist_cl"], e["on_land"] = e["norad"] == iss_id, dist_cl, True
            (x, y), = geo.local_xy([spot], home)
            e["spot_km"] = math.hypot(x, y)
        else:
            e["on_land"], e["spot_km"] = False, e["dist_cl"]
        e["grade"] = grade(e, cfg)
        e["model"], e["cmp_model"] = mode, cmp_mode
        e["cmp"] = compare(other, e) if other else None
        e["wx"] = weather.forecast(*e["spot"], e["time"], loc["timezone"]) if cfg["weather"]["enabled"] else None
        e["home_name"] = S["home"] if loc["name"] in ("", "Home") else loc["name"]
        picks.append(e)
        log(f"  {e['time']:%m-%d %H:%M:%S} {e['sat']} {e['target']} {e['size']:.1f}″")

    out_dir = Path(cfg["output"]["dir"]).expanduser()
    today = now.date()
    img_dir = out_dir / str(today)
    do_render = cfg["render"]["enabled"] if render_images is None else render_images
    chrome = render.find_chrome(cfg["render"]["chrome"]) if do_render else None
    if do_render and not chrome:
        print("[warning] Chrome/Chromium not found; skipping images (set render.chrome in the config).", file=sys.stderr)

    epochs = ", ".join(f"{NAMES.get(s.model.satnum, s.name)} {s.epoch.utc_datetime().astimezone(tz):%m-%d %H:%M}"
                       for s in eng.sats)
    end = today + dt.timedelta(days=srch["days"])
    md = [f"# {S['title'].format(date=today, start=today, end=end, found=len(found), picked=len(picks))}",
          S["tle"].format(epochs=epochs, mode=S["mode"][mode]), ""]
    if not picks:
        md.append(S["none"])
    for e in picks:
        if e["cmp"]:
            e["tf_line"] = e["cmp"]["line"]
        imgs = []
        if chrome:
            stem = img_dir / f"{e['time']:%m%d-%H%M%S}-{e['sat']}-{e['target']}"
            imgs = [str(p) for p in render.render(e, home, stem, S, chrome, cfg["render"]["fps"], cfg["render"]["tiles"])]
        e["images"] = imgs
        target = S["sun"] if e["target"] == "S" else S["moon_illum"].format(illum=round(e["illum"] * 100))
        stale = S["stale"] if (e["time"].date() - today).days > 7 else ""
        when = f"{e['time']:%Y-%m-%d} {S['weekdays'][e['time'].weekday()]} " + f"{e['time']:%H:%M:%S.%f}"[:-4]
        md.append(f"## {when} {e['sat']} {target} — {e['size']:.1f}″ "
                  f"{S['grade'][e['grade']]}{stale}")
        md.append(S["geom"].format(size=e["size"], range=e["range"], width=e["width"], alt=e["alt"], az=e["az"],
                                   sun_alt=e["sun_alt"], dur=e["duration"]))
        md.append(S["spot_land"].format(km=e["spot_km"], elev=e["elev"], url=maps_url(e["spot"]), home=e["home_name"])
                  if e["on_land"] else S["spot_sea"].format(max=cfg["spot"]["max_search_km"], url=maps_url(e["spot"])))
        if other:
            c = e["cmp"]
            model = S["mode"][cmp_mode].strip()
            md.append(S["cmp"].format(model=model, dist=c["offset_m"], dir=S["dirs"][c["dir"]],
                                      time=f"{c['time'].astimezone(tz):%H:%M:%S.%f}"[:-4], url=maps_url(c["spot"]))
                      if c else S["cmp_none"].format(model=model))
        wx = e["wx"]
        if wx is not None:
            md.append(S["weather"].format(verdict=S["verdict"][wx["verdict"]], cc=wx["cloud_cover"], lo=wx["cloud_cover_low"],
                                          mid=wx["cloud_cover_mid"], hi=wx["cloud_cover_high"], pp=wx["precipitation_probability"])
                      if "verdict" in wx else S["weather_err"].format(err=wx["error"]))
        if imgs:
            md.append(S["images"].format(paths="  ".join(imgs)))
        md.append("")

    out_dir.mkdir(parents=True, exist_ok=True)
    report = "\n".join(md)
    (out_dir / f"{today}.md").write_text(report)
    keep = ("sat", "norad", "target", "size", "alt", "az", "range", "width", "motion_dir", "ang_vel", "target_size",
            "duration", "illum", "sun_alt", "dist_cl", "spot", "elev", "on_land", "spot_km", "grade", "wx", "images")
    js = [{**{k: e.get(k) for k in keep}, "time": e["time"].isoformat(),
           "comparison": ({k: v for k, v in e["cmp"].items() if k != "line"} | {"model": cmp_mode,
                          "time": e["cmp"]["time"].astimezone(tz).isoformat()}) if e.get("cmp") else None}
          for e in picks]
    (out_dir / f"{today}.json").write_text(json.dumps({"model": mode, "events": js}, ensure_ascii=False, indent=1))
    return report, out_dir
