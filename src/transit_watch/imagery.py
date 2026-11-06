"""Real pictures of the disk for the previews: the Sun from SDO/HMI, the Moon from NASA SVS Dial-a-Moon.

SDO/HMI quick-look continuum images (1024 px) have solar north up; the Dial-a-Moon frames (730 px, hourly, with
the right phase and libration) have celestial north up. Each is turned so that the zenith is up for the
observer: the angle comes from projecting the solar rotation axis (or the celestial pole) and the local vertical
on the sky at the body. Past events get the SDO image of that quarter hour (so the sunspots in a photo line up);
future ones the latest image (spots move ~13°/day with the solar rotation).
"""
import base64
import datetime as dt
import json

import numpy as np
from skyfield.api import wgs84

from . import data

SDO_LATEST = "https://sdo.gsfc.nasa.gov/assets/img/latest/latest_1024_HMIIC.jpg"
SDO_BROWSE = "https://sdo.gsfc.nasa.gov/assets/img/browse/{d:%Y/%m/%d}/{d:%Y%m%d_%H%M%S}_1024_HMIIC.jpg"
MOON_API = "https://svs.gsfc.nasa.gov/api/dialamoon/{d:%Y-%m-%dT%H:%M}"
# Disk centre (px), scale (px per arcsec) and image size (px) of each source, fitted on sample frames
SDO_GEOM = (512.2, 512.7, 0.4917, 1024)
SVS_GEOM = (364.5, 364.5, 0.3492, 730)
# Solar rotation axis (IAU), ICRF
_RA, _DEC = np.radians(286.13), np.radians(63.87)
SOLAR_POLE = np.array([np.cos(_DEC) * np.cos(_RA), np.cos(_DEC) * np.sin(_RA), np.sin(_DEC)])


def north_angle(eng, key, t, latlon, h_m, pole):
    """Angle (deg, clockwise on the sky) from the zenith direction to `pole` projected at the body's position."""
    obs = wgs84.latlon(latlon[0], latlon[1], h_m)
    los = (eng.earth + obs).at(t).observe(eng.bodies[key]).apparent().position.km
    los = los / np.linalg.norm(los)
    z = wgs84.latlon(latlon[0], latlon[1], h_m + 1000).at(t).position.km - obs.at(t).position.km
    up = z - (z @ los) * los
    up /= np.linalg.norm(up)
    right = np.cross(los, up)
    p = pole - (pole @ los) * los
    return float(np.degrees(np.arctan2(p @ right, p @ up)))


def _cached(name, url, max_age_h):
    d = data.DATA_DIR / "imagery"
    d.mkdir(parents=True, exist_ok=True)
    return data.refresh(d / name, max_age_h, lambda: data.fetch(url)).read_bytes()


def sun_image(when):
    """JPEG bytes of the solar disk nearest `when` (UTC datetime); the latest one for the future."""
    now = dt.datetime.now(dt.timezone.utc)
    if when > now - dt.timedelta(hours=1):
        return _cached("sdo-latest.jpg", SDO_LATEST, 6)
    q = when.replace(minute=when.minute // 15 * 15, second=0, microsecond=0)
    for k in (0, 1, -1, 2, -2):            # quick-looks are every 15 min, with the odd gap
        d = q + dt.timedelta(minutes=15 * k)
        try:
            return _cached(f"sdo-{d:%Y%m%d-%H%M}.jpg", SDO_BROWSE.format(d=d), 24 * 365)
        except Exception:
            continue
    return _cached("sdo-latest.jpg", SDO_LATEST, 6)


def moon_image(when):
    d = (when + dt.timedelta(minutes=30)).replace(minute=0, second=0, microsecond=0)   # frames are hourly
    meta = json.loads(_cached(f"moon-{d:%Y%m%d-%H}.json", MOON_API.format(d=d), 24 * 365))
    url = meta["image"]["url"].replace("http://", "https://")
    return _cached(f"moon-{d:%Y%m%d-%H}.jpg", url, 24 * 365)


def for_event(eng, e, latlon, h_m):
    """{'src': data URI, 'cx', 'cy', 'scale', 'w', 'rot'} for the disk preview, or None if no picture is available."""
    try:
        when = e["t"].utc_datetime()
        if e["target"] == "S":
            jpg, (cx, cy, sc, w) = sun_image(when), SDO_GEOM
            rot = north_angle(eng, "S", e["t"], latlon, h_m, SOLAR_POLE)
        else:
            jpg, (cx, cy, sc, w) = moon_image(when), SVS_GEOM
            rot = north_angle(eng, "M", e["t"], latlon, h_m, np.array([0.0, 0.0, 1.0]))
    except Exception as err:            # pictures are decoration: never fail a report over them
        print(f"[warning] no disk image for {e.get('id', '')}: {err}")
        return None
    return {"src": "data:image/jpeg;base64," + base64.b64encode(jpg).decode(), "cx": cx, "cy": cy, "scale": sc, "w": w,
            "rot": round(rot, 2)}
