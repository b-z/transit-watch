"""Configuration: defaults, loading and writing ~/.config/transit-watch/config.toml."""
import copy
import os
import tomllib
from pathlib import Path

DEFAULT_PATH = Path(os.environ.get("TRANSIT_WATCH_CONFIG", Path.home() / ".config" / "transit-watch" / "config.toml"))

DEFAULTS = {
    "location": {
        "name": "Home",
        "latitude": None,
        "longitude": None,
        "elevation_m": 0.0,
        "timezone": "UTC",
    },
    "search": {
        "days": 14,
        "min_altitude_deg": 15.0,
        # NORAD catalog numbers. The first one is treated as "the ISS" in the rules below.
        "satellites": [25544, 48274, 20580],
    },
    "rules": {
        "iss": {
            "sun": {"min_size_arcsec": 50.0, "max_distance_km": 40.0},
            "moon": {"min_size_arcsec": 30.0, "max_distance_km": 160.0, "min_illumination": 0.6},
        },
        "other": {
            "sun": {"min_size_arcsec": 8.0, "max_distance_km": 40.0},
            "moon": {"min_size_arcsec": 6.0, "max_distance_km": 160.0, "min_illumination": 0.6},
        },
    },
    "grades": {"excellent_arcsec": 60.0, "good_arcsec": 50.0, "fair_arcsec": 30.0},
    "model": {
        # strict: IERS UT1, nutation, aberration. transit-finder: reproduces transit-finder.com.
        "mode": "strict",
        "compare_transit_finder": True,
    },
    "spot": {
        # Pick the nearest point of the centerline that is on land. auto = GSI in Japan, Open-Meteo elsewhere.
        "land_provider": "auto",
        "max_search_km": 80.0,
    },
    "weather": {"enabled": True},
    "render": {"enabled": True, "fps": 20.0, "chrome": "", "tiles": "auto"},
    "output": {"dir": "~/transit-watch/reports", "language": "en"},
}


def _merge(base, extra):
    out = copy.deepcopy(base)
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load(path=None):
    path = Path(path or DEFAULT_PATH).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"No config at {path}. Run `transit-watch init` first.")
    cfg = _merge(DEFAULTS, tomllib.loads(path.read_text()))
    loc = cfg["location"]
    if loc["latitude"] is None or loc["longitude"] is None:
        raise ValueError(f"{path}: location.latitude and location.longitude are required.")
    return cfg


def _toml_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, list):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def dumps(cfg, prefix=""):
    """Minimal TOML writer for the nested dict above (tables of scalars and lists)."""
    scalars = [(k, v) for k, v in cfg.items() if not isinstance(v, dict)]
    tables = [(k, v) for k, v in cfg.items() if isinstance(v, dict)]
    lines = []
    if prefix and scalars:
        lines.append(f"[{prefix}]")
    lines += [f"{k} = {_toml_value(v)}" for k, v in scalars if v is not None]
    if scalars:
        lines.append("")
    for k, v in tables:
        lines.append(dumps(v, f"{prefix}.{k}" if prefix else k))
    return "\n".join(lines)


def save(cfg, path=None):
    path = Path(path or DEFAULT_PATH).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# transit-watch configuration. See README for every option.\n\n" + dumps(cfg))
    return path
