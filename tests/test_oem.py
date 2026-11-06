import datetime as dt

import numpy as np
from sgp4.api import WGS72, Satrec
from skyfield.api import EarthSatellite, load

from transit_watch.oem import AU_KM, _B, OEMSatellite

L1 = "1 25544U 98067A   26107.16713328  .00006923  00000-0  13461-3 0  9995"
L2 = "2 25544  51.6328 242.0950 0006548 316.4598  43.5873 15.48795320562296"


def _fake_oem(sat, ts, start, hours=6, step_s=240):
    """An OEM file whose states are the TLE's own (GCRS -> EME2000), to test parsing and interpolation."""
    lines = ["CCSDS_OEM_VERS = 2.0", "CREATION_DATE  = 2026-04-13T21:01:25.913", "", "META_START",
             "REF_FRAME            = EME2000", "TIME_SYSTEM          = UTC", "META_STOP", ""]
    for k in range(int(hours * 3600 / step_s) + 1):
        when = start + dt.timedelta(seconds=k * step_s)
        g = sat.at(ts.from_datetime(when))
        r, v = _B @ g.position.km, _B @ g.velocity.km_per_s
        lines.append(f"{when:%Y-%m-%dT%H:%M:%S}.000 " + " ".join(f"{x:.9f}" for x in (*r, *v)))
    return "\n".join(lines)


def test_oem_interpolates_to_the_states_it_was_built_from():
    ts = load.timescale(builtin=True)
    sat = EarthSatellite.from_satrec(Satrec.twoline2rv(L1, L2, WGS72), ts)
    sat.name = "ISS"
    start = dt.datetime(2026, 4, 17, 0, 0, tzinfo=dt.timezone.utc)
    oem = OEMSatellite(_fake_oem(sat, ts, start), sat, ts)
    # off-grid instants, scalar and array
    t = ts.from_datetime(start + dt.timedelta(hours=3, seconds=17.3))
    assert np.linalg.norm(oem.at(t).position.km - sat.at(t).position.km) < 0.001          # < 1 m
    ta = ts.utc(2026, 4, 17, 1, 0, np.arange(0, 3600, 37.7))
    d = np.linalg.norm(oem.at(ta).position.km - sat.at(ta).position.km, axis=0)
    assert d.max() < 0.001
    assert np.allclose(oem.at(ta).velocity.km_per_s, sat.at(ta).velocity.km_per_s, atol=1e-5)


def test_oem_falls_back_to_tle_outside_its_span():
    ts = load.timescale(builtin=True)
    sat = EarthSatellite.from_satrec(Satrec.twoline2rv(L1, L2, WGS72), ts)
    sat.name = "ISS"
    start = dt.datetime(2026, 4, 17, 0, 0, tzinfo=dt.timezone.utc)
    text = _fake_oem(sat, ts, start, hours=2).replace(" ", "  ", 0)
    # shift every state by 1 km in x so OEM and TLE are distinguishable
    shifted = "\n".join(l if not l[:4].isdigit() else
                        (lambda p: " ".join([p[0], f"{float(p[1]) + 1.0:.9f}", *p[2:]]))(l.split())
                        for l in text.splitlines())
    oem = OEMSatellite(shifted, sat, ts)
    inside = ts.from_datetime(start + dt.timedelta(minutes=50))
    outside = ts.from_datetime(start + dt.timedelta(hours=5))
    assert abs(np.linalg.norm(oem.at(inside).position.km - sat.at(inside).position.km) - 1.0) < 1e-3
    assert np.linalg.norm(oem.at(outside).position.km - sat.at(outside).position.km) < 1e-9
    assert oem.covers(inside) and not oem.covers(outside)
    assert AU_KM > 1e8
