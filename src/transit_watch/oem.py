"""NASA's ISS ephemeris (CCSDS OEM) as a skyfield satellite, with the TLE as fallback outside its span.

NASA JSC (FOD/TOPO) publishes the ISS's predicted state vectors every few days: 4-minute EME2000 states for
the next ~15 days, including planned reboosts. A TLE is a mean-element fit for SGP4 and is typically off by a
few hundred metres, which moves a centerline by about as much: on 2026-04-17 the TLE put the line 270 m away
from where a photograph showed it, while the OEM predicted from three days earlier agreed to ~40 m.
"""
import datetime as dt

import numpy as np
from skyfield.vectorlib import VectorFunction

AU_KM = 149597870.700
ORDER = 8          # Lagrange points (CCSDS recommends 5-9 for 4-minute ISS states)

# Frame bias GCRS -> J2000 (IERS Conventions 2010, eq. 5.33): x_J2000 = B x_GCRS
_MAS = np.pi / 180 / 3600e3
_DA, _XI, _ETA = -14.6 * _MAS, -16.617 * _MAS, -6.8192 * _MAS
_B = np.array([[1.0, _DA, -_XI], [-_DA, 1.0, -_ETA], [_XI, _ETA, 1.0]])


def parse(text):
    """Segments of (utc datetimes, positions km, velocities km/s) plus the creation date."""
    segments, cur, created = [], None, None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("CREATION_DATE"):
            created = dt.datetime.fromisoformat(s.split("=", 1)[1].strip()).replace(tzinfo=dt.timezone.utc)
        elif s == "META_START":
            cur = ([], [], [])
            segments.append(cur)
        elif cur is not None and s[:1].isdigit() and "T" in s.split()[0]:
            p = s.split()
            if len(p) < 7:
                continue
            cur[0].append(dt.datetime.fromisoformat(p[0]).replace(tzinfo=dt.timezone.utc))
            cur[1].append([float(v) for v in p[1:4]])
            cur[2].append([float(v) for v in p[4:7]])
    out = [(t, np.array(r), np.array(v)) for t, r, v in segments if len(t) >= ORDER]
    if not out:
        raise ValueError("no OEM state vectors found")
    return out, created


class OEMSatellite(VectorFunction):
    """Geocentric (GCRS) position of the satellite: OEM where it covers the time, else the fallback (TLE)."""
    center = 399

    def __init__(self, text, fallback, ts):
        self.fallback = fallback
        self.target = fallback.target
        self.name, self.model, self.epoch = fallback.name, fallback.model, fallback.epoch
        segs, self.created = parse(text)
        self.segments = []
        for t, r, v in segs:
            tt = ts.from_datetimes(t).tt
            self.segments.append((tt, r @ _B, v @ _B))      # row vectors: x_GCRS = B^T x_J2000
        self.start = min(s[0][0] for s in self.segments)
        self.stop = max(s[0][-1] for s in self.segments)

    @property
    def target_name(self):
        return f"{self.name} (NASA OEM)"

    def covers(self, t):
        tt = np.asarray(t.tt)
        return (tt >= self.start) & (tt <= self.stop)

    def _at(self, t):
        p, v, _, err = self.fallback._at(t)
        tt = np.atleast_1d(np.asarray(t.tt, dtype=float))
        pos, vel = np.array(p, dtype=float, ndmin=2), np.array(v, dtype=float, ndmin=2)
        scalar = np.ndim(t.tt) == 0
        if scalar:
            pos, vel = pos.reshape(3, 1), vel.reshape(3, 1)
        for nodes, r, vv in self.segments:
            m = (tt >= nodes[0]) & (tt <= nodes[-1])
            if not m.any():
                continue
            x = tt[m]
            i = np.clip(np.searchsorted(nodes, x) - ORDER // 2, 0, len(nodes) - ORDER)
            win = i[:, None] + np.arange(ORDER)
            sec = (nodes[win] - x[:, None]) * 86400.0                 # node times relative to t, seconds
            w = np.ones_like(sec)
            for j in range(ORDER):
                for k in range(ORDER):
                    if j != k:
                        w[:, j] *= (0 - sec[:, k]) / (sec[:, j] - sec[:, k])
            pos[:, m] = np.einsum("nj,njk->kn", w, r[win]) / AU_KM
            vel[:, m] = np.einsum("nj,njk->kn", w, vv[win]) / AU_KM * 86400.0
        if scalar:
            pos, vel = pos[:, 0], vel[:, 0]
        return pos, vel, None, err
