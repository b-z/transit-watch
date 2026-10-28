"""Local geometry, elevation lookups and the search for a reachable (on-land) spot on the centerline."""
import json
import math
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
    try:
        v = _get_json("https://cyberjapandata2.gsi.go.jp/general/dem/scripts/getelevation.php?" + q)["elevation"]
    except Exception:
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


def elevation_lookup(provider, lat, lon):
    if provider == "none":
        return 0.0
    if provider == "gsi" or (provider == "auto" and in_japan(lat, lon)):
        return elevation_gsi(lat, lon)
    return elevation_open_meteo(lat, lon)


def nearest_land_on_line(line, home, provider="auto", step_km=1.0, max_search_km=80.0):
    """Walk the centerline outwards from home and return (km_from_home, lat, lon, elevation_m) of the first
    point on land, or None."""
    if not line:
        return None
    xy = local_xy(line, home)
    pts, carry = [xy[0]], 0.0
    for (x1, y1), (x2, y2) in zip(xy, xy[1:]):
        seg = math.hypot(x2 - x1, y2 - y1)
        s = step_km - carry
        while s <= seg:
            pts.append((x1 + (x2 - x1) * s / seg, y1 + (y2 - y1) * s / seg))
            s += step_km
        carry = (carry + seg) % step_km if seg else carry
    pts.sort(key=lambda p: math.hypot(*p))
    for x, y in pts[: int(2 * max_search_km / step_km)]:
        lat, lon = from_local(x, y, home)
        h = elevation_lookup(provider, lat, lon)
        if h is not None:
            return math.hypot(x, y), lat, lon, h
    return None


def bearing_index(dx, dy):
    """Index 0..7 of N, NE, E, SE, S, SW, W, NW for a local offset."""
    return int((math.degrees(math.atan2(dx, dy)) % 360 + 22.5) // 45) % 8
