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

from . import data, geo, interactive, render, weather
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
    """The centerline shifts with the observer's height (about 360 m for 300 m at 40° altitude), so the spot must
    be a point whose own ground height puts it on the centerline. h is above sea level (the geoid); the engine
    needs the height above the ellipsoid, so the geoid height is added.

    Simple iteration (look up the height, recompute the line, repeat) diverges on slopes steeper than about the
    altitude angle, so solve along the line's normal instead: the line for height z crosses the normal at
    x_L(z) = k (z - z_a); find x with x = x_L(ground(x)) by bracketing and bisection.
    Returns (transit, spot, elevation above sea level, geoid height)."""
    sat = next(s for s in eng.sats if s.name == tr.sat)
    n = geo.geoid_height(*spot)
    t0, t1 = tr.t_center.tt - 90 / 86400, tr.t_center.tt + 90 / 86400

    def line_at(z, near):
        return eng._refine(sat, tr.target, near, None, t0, t1, 0.02, 0, z)

    za = h + n
    a = line_at(za, spot)
    b = line_at(za + 100, a.spot) if a else None
    if a is None or b is None:
        return tr, spot, h, n
    (bx, by), = geo.local_xy([b.spot], a.spot)
    shift = math.hypot(bx, by)                      # km per 100 m of height
    if shift == 0:
        return a, a.spot, h, n
    ux, uy, k = bx / shift, by / shift, shift * 10  # unit normal, metres of shift per metre of height

    def ground(x):
        lat, lon = geo.from_local(ux * x / 1000, uy * x / 1000, a.spot)
        v = geo.elevation_lookup(provider, lat, lon)
        return (lat, lon), (0.0 if v is None else v)

    def g(x):
        p, z = ground(x)
        return x - k * (z + n - za), p, z

    g0, p0, z0 = g(0.0)
    if abs(g0) < 0.5:
        return a, a.spot, z0, n
    direction, lo, glo, step, hit = (1 if g0 < 0 else -1), 0.0, g0, max(10.0, abs(g0)), None
    for _ in range(10):
        hi = lo + direction * step
        ghi, p, z = g(hi)
        if (ghi > 0) != (glo > 0):
            for _ in range(14):
                if abs(hi - lo) < 0.5:
                    break
                mid = (lo + hi) / 2
                gm, p, z = g(mid)
                if (gm > 0) == (glo > 0):
                    lo, glo = mid, gm
                else:
                    hi = mid
            hit = ground((lo + hi) / 2)
            break
        lo, glo, step = hi, ghi, step * 2
    if hit is None:
        return a, a.spot, z0, n
    (lat, lon), z = hit
    final = line_at(z + n, (lat, lon))
    return (final, final.spot, z, n) if final else (a, a.spot, z0, n)


def compare(other, e):
    sat = next((s for s in other.sats if s.model.satnum == e["norad"]), None)
    if sat is None:
        return None
    tr = other._refine(sat, e["target"], e["spot"], None, e["t"].tt - 120 / 86400, e["t"].tt + 120 / 86400, 0.02, 0, e["h_ell"])
    if tr is None:
        return None
    (x, y), = geo.local_xy([tr.spot], e["spot"])
    return {"line": tr.line, "spot": tr.spot, "offset_m": math.hypot(x, y) * 1000, "dir": geo.bearing_index(x, y),
            "time": tr.t_center.utc_datetime()}


def sky_per_metre(eng, sat, e, step_m=150.0):
    """How the station's path on the disk moves when the observer steps sideways off the centerline: arcsec on the
    zenith-up frame per metre to the left of the line's direction of travel. The interactive map uses it to draw the
    view from any point (the shift is linear across the visibility path)."""
    xy = geo.local_xy(e["line"], e["spot"])
    i = min(range(len(xy) - 1), key=lambda k: math.hypot(*xy[k]) + math.hypot(*xy[k + 1]))
    dx, dy = xy[i + 1][0] - xy[i][0], xy[i + 1][1] - xy[i][1]
    n = math.hypot(dx, dy) or 1
    lx, ly = -dy / n, dx / n                                    # left normal, unit
    tt = eng.ts.tt_jd(e["t"].tt + np.arange(-3000, 3001) * 0.002 / 86400)
    off = []
    for sgn in (1, -1):
        p = geo.from_local(sgn * lx * step_m / 1000, sgn * ly * step_m / 1000, e["spot"])
        off.append(eng.sky_offset(sat, e["target"], p, tt, e["h_ell"]))
    return [(off[0][0] - off[1][0]) / (2 * step_m), (off[0][1] - off[1][1]) / (2 * step_m)]


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
    h_home = elev0 + geo.geoid_height(*home)
    found = eng.find(home, t0, t1, travel_km=max_km, min_alt=srch["min_altitude_deg"], elev_m=h_home)

    picks = []
    for tr in found:
        e = describe(eng, tr, tr.spot, h_home, tz)
        e["is_iss"] = e["norad"] == iss_id
        r = rules["iss" if e["is_iss"] else "other"]["sun" if e["target"] == "S" else "moon"]
        if e["size"] < r["min_size_arcsec"] or e["dist_cl"] > r["max_distance_km"] or e["alt"] < srch["min_altitude_deg"]:
            continue
        if e["target"] == "M" and (e["illum"] or 0) < r.get("min_illumination", 0):
            continue
        land = geo.nearest_land_on_line(tr.line, home, provider, max_search_km=cfg["spot"]["max_search_km"])
        # over the sea the "spot" is the nearest centerline point at sea level
        tr_h, spot, h, n = (at_elevation(eng, tr, land[1:3], land[3], provider) if land
                            else at_elevation(eng, tr, tr.spot, 0.0, "none"))
        dist_cl = e["dist_cl"]
        e = describe(eng, tr_h, spot, h + n, tz)
        e["is_iss"], e["dist_cl"], e["on_land"] = e["norad"] == iss_id, dist_cl, bool(land)
        e["elev"], e["geoid"], e["h_ell"] = h, n, h + n
        (x, y), = geo.local_xy([spot], home)
        e["spot_km"] = math.hypot(x, y)
        e["grade"] = grade(e, cfg)
        e["model"], e["cmp_model"] = mode, cmp_mode
        e["cmp"] = compare(other, e) if other else None
        e["wx"] = weather.forecast(*e["spot"], e["time"], loc["timezone"]) if cfg["weather"]["enabled"] else None
        e["home_name"] = S["home"] if loc["name"] in ("", "Home") else loc["name"]
        e["id"] = f"{e['sat']}-{'sun' if e['target'] == 'S' else 'moon'}-{e['t'].utc_datetime():%Y%m%dT%H%M}Z".lower()
        sat = next(s for s in eng.sats if s.model.satnum == e["norad"])
        e["track"] = eng.track(sat, e["target"], e["t"], home, max_km + 40)
        if e["track"]:
            p0 = e["track"]["p0"]
            # geoid along the line for the map; a coarser grid keeps the number of geoid requests down
            e["track"]["geoid"] = [round(geo.geoid_height(*p0[i], grid=0.25), 2) for i in e["track"]["sparse"]["i"]]
        e["sky_per_m"] = sky_per_metre(eng, sat, e)
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
    map_path = interactive.write(picks, home, S, cfg, out_dir / f"{today}-map.html", now.isoformat(timespec="minutes"))
    md.append(f"{S['imap']['title']}: {map_path}")
    report = "\n".join(md)
    (out_dir / f"{today}.md").write_text(report)
    for e in picks:
        e["grade_label"] = S["grade"][e["grade"]]
        e["weather_label"] = S["verdict"][e["wx"]["verdict"]] if e.get("wx") and "verdict" in e["wx"] else None
    keep = ("id", "grade_label", "weather_label", "sat", "norad", "target", "size", "alt", "az", "range", "width", "motion_dir", "ang_vel", "target_size",
            "duration", "illum", "sun_alt", "dist_cl", "spot", "elev", "geoid", "on_land", "spot_km", "grade", "wx", "images")
    js = [{**{k: e.get(k) for k in keep}, "time": e["time"].isoformat(),
           "comparison": ({k: v for k, v in e["cmp"].items() if k != "line"} | {"model": cmp_mode,
                          "time": e["cmp"]["time"].astimezone(tz).isoformat()}) if e.get("cmp") else None}
          for e in picks]
    tle_epochs = {NAMES.get(s.model.satnum, s.name): s.epoch.utc_datetime().astimezone(tz).isoformat(timespec="minutes")
                  for s in eng.sats}
    (out_dir / f"{today}.json").write_text(json.dumps({"model": mode, "generated": now.isoformat(timespec="seconds"),
                                                      "map": str(map_path), "tle_epochs": tle_epochs, "events": js},
                                                      ensure_ascii=False, indent=1))
    return report, out_dir
