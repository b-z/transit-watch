"""Command line: `transit-watch init` writes the config, `transit-watch run` makes the forecast."""
import argparse
import copy
import sys

from . import __version__, config


def _ask(prompt, default, cast=str):
    while True:
        raw = input(f"{prompt} [{default}]: ").strip() if sys.stdin.isatty() else ""
        if not raw:
            return default
        try:
            return cast(raw)
        except ValueError:
            print("  invalid value, try again")


def cmd_init(a):
    cfg = copy.deepcopy(config.DEFAULTS)
    if config.DEFAULT_PATH.exists() and a.config is None and not a.force:
        cfg = config.load()
    loc, rules = cfg["location"], cfg["rules"]
    flags = {
        ("location", "latitude"): a.lat, ("location", "longitude"): a.lon, ("location", "elevation_m"): a.elevation,
        ("location", "timezone"): a.timezone, ("location", "name"): a.name, ("output", "language"): a.language,
        ("search", "days"): a.days, ("render", "fps"): a.fps,
    }
    for (sec, key), v in flags.items():
        if v is not None:
            cfg[sec][key] = v
    th = {"iss_sun_size": ("iss", "sun", "min_size_arcsec"), "iss_sun_km": ("iss", "sun", "max_distance_km"),
          "iss_moon_size": ("iss", "moon", "min_size_arcsec"), "iss_moon_km": ("iss", "moon", "max_distance_km"),
          "other_sun_size": ("other", "sun", "min_size_arcsec"), "other_sun_km": ("other", "sun", "max_distance_km"),
          "other_moon_size": ("other", "moon", "min_size_arcsec"), "other_moon_km": ("other", "moon", "max_distance_km"),
          "min_illumination": None}
    for name, path in th.items():
        v = getattr(a, name)
        if v is None:
            continue
        if path is None:
            rules["iss"]["moon"]["min_illumination"] = rules["other"]["moon"]["min_illumination"] = v
        else:
            rules[path[0]][path[1]][path[2]] = v

    interactive = sys.stdin.isatty() and not a.yes
    if interactive:
        print("transit-watch setup. Press Enter to keep the value in brackets.\n")
        loc["latitude"] = _ask("Latitude of home (decimal degrees, north positive)", loc["latitude"], float)
        loc["longitude"] = _ask("Longitude of home (decimal degrees, east positive)", loc["longitude"], float)
        loc["elevation_m"] = _ask("Elevation of home (m)", loc["elevation_m"], float)
        loc["timezone"] = _ask("Time zone (IANA name, e.g. Asia/Tokyo)", loc["timezone"])
        cfg["output"]["language"] = _ask("Report language (en / zh / ja)", cfg["output"]["language"])
        print("\nThresholds. Size = apparent size of the station; distance = centerline distance from home.")
        for who, label in (("iss", "ISS"), ("other", "other spacecraft")):
            for body in ("sun", "moon"):
                r = rules[who][body]
                r["min_size_arcsec"] = _ask(f"{label} / {body}: minimum size (arcsec)", r["min_size_arcsec"], float)
                r["max_distance_km"] = _ask(f"{label} / {body}: maximum distance (km)", r["max_distance_km"], float)
        illum = _ask("Moon: minimum illuminated fraction (0-1)", rules["iss"]["moon"]["min_illumination"], float)
        rules["iss"]["moon"]["min_illumination"] = rules["other"]["moon"]["min_illumination"] = illum
    if loc["latitude"] is None or loc["longitude"] is None:
        sys.exit("Latitude and longitude are required: pass --lat and --lon, or run init in a terminal.")
    path = config.save(cfg, a.config)
    print(f"Saved {path}")


def cmd_run(a):
    from .report import run
    cfg = config.load(a.config)
    if a.days:
        cfg["search"]["days"] = a.days
    if a.model:
        cfg["model"]["mode"] = a.model
    if a.language:
        cfg["output"]["language"] = a.language
    report, out = run(cfg, render_images=False if a.no_images else None,
                      log=(lambda *_: None) if a.quiet else (lambda m: print(m, file=sys.stderr)))
    print(report)
    print(f"\nSaved to {out}", file=sys.stderr)


def main(argv=None):
    p = argparse.ArgumentParser(prog="transit-watch", description=__doc__)
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--config", help=f"config file (default {config.DEFAULT_PATH})")
    sub = p.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("init", help="create or update the config")
    i.add_argument("--lat", type=float)
    i.add_argument("--lon", type=float)
    i.add_argument("--elevation", type=float, help="home elevation in meters")
    i.add_argument("--timezone", help="IANA time zone, e.g. Asia/Tokyo")
    i.add_argument("--name", help="what to call the home location in reports")
    i.add_argument("--language", choices=["en", "zh", "ja"])
    i.add_argument("--days", type=int, help="how many days ahead to search")
    i.add_argument("--fps", type=float, help="camera frame rate for the disk preview")
    for who in ("iss", "other"):
        for body in ("sun", "moon"):
            i.add_argument(f"--{who}-{body}-size", type=float, metavar="ARCSEC")
            i.add_argument(f"--{who}-{body}-km", type=float, metavar="KM")
    i.add_argument("--min-illumination", type=float, help="Moon, 0-1")
    i.add_argument("--yes", "-y", action="store_true", help="do not prompt")
    i.add_argument("--force", action="store_true", help="start from defaults instead of the existing config")
    i.set_defaults(func=cmd_init)

    r = sub.add_parser("run", help="compute the forecast and write the report")
    r.add_argument("--days", type=int)
    r.add_argument("--model", choices=["strict", "transit-finder"])
    r.add_argument("--language", choices=["en", "zh", "ja"])
    r.add_argument("--no-images", action="store_true")
    r.add_argument("--quiet", action="store_true")
    r.set_defaults(func=cmd_run)

    a = p.parse_args(argv)
    a.func(a)


if __name__ == "__main__":
    main()
