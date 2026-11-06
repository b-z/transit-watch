"""Downloads and caches: TLEs (CelesTrak), Earth orientation (IERS finals), JPL ephemeris (via skyfield)."""
import os
import sys
import time
import urllib.request
from pathlib import Path

DATA_DIR = Path(os.environ.get("TRANSIT_WATCH_DATA", Path.home() / ".cache" / "transit-watch"))
USER_AGENT = "transit-watch (+https://github.com/b-z/transit-watch)"


def fetch(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(req, timeout=timeout).read()


def refresh(path, max_age_h, download):
    """Re-download when older than max_age_h; keep the old copy if the download fails."""
    if path.exists() and time.time() - path.stat().st_mtime < max_age_h * 3600:
        return path
    try:
        path.write_bytes(download())
    except Exception as e:
        if not path.exists():
            raise
        print(f"[warning] could not update {path.name}, using the copy from {time.ctime(path.stat().st_mtime)}: {e}",
              file=sys.stderr)
    return path


ISS_OEM = "https://nasa-public-data.s3.amazonaws.com/iss-coords/current/ISS_OEM/ISS.OEM_J2K_EPH.txt"


def iss_oem(data_dir=DATA_DIR):
    """NASA JSC's current ISS ephemeris (re-issued every few days, ~15 days ahead), or None if unavailable."""
    try:
        return refresh(Path(data_dir) / "iss-oem.txt", 12, lambda: fetch(ISS_OEM, 120)).read_text()
    except Exception as e:
        print(f"[warning] no NASA ISS ephemeris, using the TLE: {e}", file=sys.stderr)
        return None


def prepare(norad_ids, data_dir=DATA_DIR):
    """Make sure TLEs and IERS data are fresh. Returns the TLE text."""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    ids = ",".join(map(str, norad_ids))
    # CelesTrak asks clients not to fetch the same object more than once every 2 hours.
    tle = refresh(data_dir / f"tle-{ids.replace(',', '-')}.txt", 2, lambda: b"".join(
        fetch(f"https://celestrak.org/NORAD/elements/gp.php?CATNR={n}&FORMAT=tle") for n in norad_ids))
    refresh(data_dir / "finals2000A.all", 24 * 7, lambda: fetch("https://maia.usno.navy.mil/ser7/finals2000A.all", 120))
    return tle.read_text()
