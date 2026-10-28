"""Hourly cloud and rain forecast from Open-Meteo (https://open-meteo.com, CC BY 4.0)."""
import datetime as dt
import json
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

from .data import USER_AGENT


def forecast(lat, lon, when, tz_name):
    """when: aware datetime. Returns a dict with cloud cover, rain chance and a verdict key, or {"error": ...}."""
    local = when.astimezone(ZoneInfo(tz_name))
    q = urllib.parse.urlencode({
        "latitude": round(lat, 3), "longitude": round(lon, 3), "timezone": tz_name,
        "hourly": "cloud_cover,cloud_cover_low,cloud_cover_mid,cloud_cover_high,precipitation_probability,weather_code",
        "start_date": local.date().isoformat(), "end_date": local.date().isoformat(),
    })
    try:
        req = urllib.request.Request("https://api.open-meteo.com/v1/forecast?" + q, headers={"User-Agent": USER_AGENT})
        h = json.load(urllib.request.urlopen(req, timeout=30))["hourly"]
    except Exception as e:
        return {"error": str(e)[:80]}
    key = (local + dt.timedelta(minutes=30)).strftime("%Y-%m-%dT%H:00")
    i = h["time"].index(key) if key in h["time"] else local.hour
    w = {k: h[k][i] for k in h if k != "time"}
    if w["cloud_cover"] is None:
        return {"error": "beyond forecast range"}
    if (w["precipitation_probability"] or 0) >= 50 or (w["weather_code"] or 0) >= 51:
        w["verdict"] = "rain"
    elif w["cloud_cover"] >= 90 and (w["cloud_cover_low"] or 0) >= 60:
        w["verdict"] = "overcast"
    elif w["cloud_cover"] >= 30:
        w["verdict"] = "cloudy"
    else:
        w["verdict"] = "clear"
    return w
