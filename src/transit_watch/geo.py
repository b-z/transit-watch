"""Local geometry, elevation lookups and the search for a reachable (on-land) spot on the centerline."""
import json
import math
import time
import urllib.parse
import urllib.request

from .data import USER_AGENT


def local_xy(points, origin):
    """(lat, lon) points -> local flat (x east, y north) km around origin."""
    k = math.cos(math.radians(origin[0]))
    return [((lon - origin[1]) * k * 111.32, (lat - origin[0]) * 110.57) for lat, lon in points]


def from_local(x, y, origin):
    k = math.cos(math.radians(origin[0]))
    return y / 110.57 + origin[0], x / (k * 111.32) + origin[1]


def in_japan(lat, lon):
    return 24 <= lat <= 46 and 122 <= lon <= 146


def _get_json(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def elevation_gsi(lat, lon):
    """Geospatial Information Authority of Japan DEM. None over the sea or outside Japan."""
    q = urllib.parse.urlencode({"lon": f"{lon:.5f}", "lat": f"{lat:.5f}", "outtype": "JSON"})
    # a failed request must not read as sea, or the chosen spot jumps along the line from run to run
    for wait in (0, 2, 5, 10):
        time.sleep(wait)
        try:
            v = _get_json("https://cyberjapandata2.gsi.go.jp/general/dem/scripts/getelevation.php?" + q)["elevation"]
            break
        except Exception:
            continue
    else:
        return None
    return None if v == "-----" else float(v)


def elevation_open_meteo(lat, lon):
    """Copernicus DEM via Open-Meteo. Water reads as 0 m or below, which we treat as not reachable."""
    q = urllib.parse.urlencode({"latitude": f"{lat:.5f}", "longitude": f"{lon:.5f}"})
    try:
        v = _get_json("https://api.open-meteo.com/v1/elevation?" + q)["elevation"][0]
    except Exception:
        return None
    return float(v) if v is not None and v > 0 else None


_GEOID_CACHE = {}


def _geoid_gsi_point(lat, lon):
    """Geoid height (m) from the GSI geoid calculator, cached on disk. The service allows only a few requests in a
    row, so space them out and back off when it says it is busy."""
    from .data import DATA_DIR
    path = DATA_DIR / "geoid-cache.json"
    if not _GEOID_CACHE and path.exists():
        _GEOID_CACHE.update(json.loads(path.read_text()))
    key = f"{lat:.2f},{lon:.2f}"
    if key in _GEOID_CACHE:
        return _GEOID_CACHE[key]
    q = urllib.parse.urlencode({"outputType": "json", "latitude": f"{lat:.4f}", "longitude": f"{lon:.4f}"})
    for wait in (1.2, 3, 6, 12, 24):
        time.sleep(wait)
        try:
            v = float(_get_json("https://vldb.gsi.go.jp/sokuchi/surveycalc/geoid/calcgh/cgi/geoidcalc.pl?" + q, 30)
                      ["OutputData"]["geoidHeight"])
            break
        except Exception:
            continue            # busy (it answers with an error message instead of data), or a network error
    else:
        return None
    _GEOID_CACHE[key] = v
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_GEOID_CACHE))
    return v


def geoid_height(lat, lon, grid=0.1):
    """Height of the geoid above the WGS84 ellipsoid (m). DEM elevations are above the geoid, while the centerline
    needs ellipsoidal heights: around Tokyo the difference is ~37 m, which moves a centerline ~40 m.
    Japan: GSI geoid model, bilinear on a `grid`-degree grid. Elsewhere 0 (not modelled)."""
    if not in_japan(lat, lon):
        return 0.0
    la0, lo0 = math.floor(lat / grid) * grid, math.floor(lon / grid) * grid
    fy, fx = (lat - la0) / grid, (lon - lo0) / grid
    c = [_geoid_gsi_point(la0 + dy * grid, lo0 + dx * grid) for dy in (0, 1) for dx in (0, 1)]
    if any(v is None for v in c):
        ok = [v for v in c if v is not None]
        return sum(ok) / len(ok) if ok else 0.0
    return (c[0] * (1 - fx) + c[1] * fx) * (1 - fy) + (c[2] * (1 - fx) + c[3] * fx) * fy


def elevation_lookup(provider, lat, lon):
    if provider == "none":
        return 0.0
    if provider == "gsi" or (provider == "auto" and in_japan(lat, lon)):
        return elevation_gsi(lat, lon)
    return elevation_open_meteo(lat, lon)


def nearest_land_on_line(line, home, provider="auto", step_km=1.0, max_search_km=80.0):
    """Walk the centerline outwards from the point nearest home and return (km_from_home, lat, lon, elevation_m)
    of the first point on land, or None. Candidates sit at fixed arc lengths from that nearest point, so the
    result does not depend on how the line happened to be sampled."""
    if not line:
        return None
    xy = local_xy(line, home)
    seg, cum = [], [0.0]
    for (x1, y1), (x2, y2) in zip(xy, xy[1:]):
        seg.append(((x1, y1), (x2, y2)))
        cum.append(cum[-1] + math.hypot(x2 - x1, y2 - y1))
    best = None
    for i, ((x1, y1), (x2, y2)) in enumerate(seg):
        dx, dy = x2 - x1, y2 - y1
        L2 = dx * dx + dy * dy or 1e-12
        u = min(1, max(0, -(x1 * dx + y1 * dy) / L2))
        d = math.hypot(x1 + u * dx, y1 + u * dy)
        if best is None or d < best[0]:
            best = (d, cum[i] + u * math.sqrt(L2))
    s0 = best[1]

    def at(s):
        i = max(0, min(len(seg) - 1, next((k for k in range(len(seg)) if cum[k + 1] >= s), len(seg) - 1)))
        (x1, y1), (x2, y2) = seg[i]
        L = cum[i + 1] - cum[i] or 1e-12
        u = (s - cum[i]) / L
        return x1 + u * (x2 - x1), y1 + u * (y2 - y1)

    offsets = [0.0] + [k * step_km * sign for k in range(1, int(max_search_km / step_km) + 1) for sign in (1, -1)]
    pts = [at(s0 + o) for o in offsets if 0 <= s0 + o <= cum[-1]]
    pts.sort(key=lambda p: math.hypot(*p))
    for x, y in pts:
        lat, lon = from_local(x, y, home)
        h = elevation_lookup(provider, lat, lon)
        if h is not None:
            return math.hypot(x, y), lat, lon, h
    return None


def bearing_index(dx, dy):
    """Index 0..7 of N, NE, E, SE, S, SW, W, NW for a local offset."""
    return int((math.degrees(math.atan2(dx, dy)) % 360 + 22.5) // 45) % 8
