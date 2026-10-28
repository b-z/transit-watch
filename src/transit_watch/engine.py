"""Transit geometry: extend the ray "Sun/Moon -> satellite" to the ground; its footprint over time is the centerline.

All vectors are ITRS (Earth-fixed, km). Bodies use geocentric apparent places, satellites use SGP4.
"""
import math
from dataclasses import dataclass, field

import numpy as np
from sgp4.api import WGS72, WGS84, Satrec
from skyfield.api import EarthSatellite, Loader, wgs84
from skyfield.framelib import itrs

A_WGS = 6378.137
B_WGS = 6356.752314245
BODY_RADIUS_KM = {"S": 696000.0, "M": 1737.4}

# Apparent-size convention (m), calibrated so that angular sizes match the figures transit-finder.com shows
SAT_SPAN_M = {25544: 134.0, 48274: 18.05, 20580: 14.45}


@dataclass
class Transit:
    sat: str
    norad: int
    target: str                 # "S" / "M"
    t_center: object            # skyfield Time at the centerline point nearest to home
    spot: tuple                 # (lat, lon) centerline point nearest to home
    dist_cl_km: float           # shortest distance from home to the centerline
    line: list                  # centerline [(lat, lon), ...]
    at_spot: dict = field(default_factory=dict)
    at_home: dict = field(default_factory=dict)


def _ray_ground(S, B, h_km=0.0):
    """S, B: (3, N) ITRS km. Returns the ground intersection G (3, N); nan where the ray misses."""
    u = S - B
    u /= np.linalg.norm(u, axis=0)
    a, b = A_WGS + h_km, B_WGS + h_km
    sc = np.array([[1.0], [1.0], [a / b]])
    s, v = S * sc, u * sc
    qa = (v * v).sum(0)
    qb = 2 * (s * v).sum(0)
    qc = (s * s).sum(0) - a * a
    disc = qb * qb - 4 * qa * qc
    lam = (-qb - np.sqrt(np.where(disc >= 0, disc, np.nan))) / (2 * qa)
    lam = np.where(lam > 0, lam, np.nan)
    return S + lam * u


def _up(G):
    """Ellipsoid normal (geodetic zenith)."""
    n = G / np.array([[A_WGS**2], [A_WGS**2], [B_WGS**2]])
    with np.errstate(invalid="ignore", divide="ignore"):
        return n / np.linalg.norm(n, axis=0)


def _xyz_to_latlon(G):
    lat, lon = [], []
    for x, y, z in G.T:
        p = math.hypot(x, y)
        e2 = 1 - (B_WGS / A_WGS) ** 2
        phi = math.atan2(z, p * (1 - e2))
        for _ in range(5):
            N = A_WGS / math.sqrt(1 - e2 * math.sin(phi) ** 2)
            h = p / math.cos(phi) - N
            phi = math.atan2(z, p * (1 - e2 * N / (N + h)))
        lat.append(math.degrees(phi))
        lon.append(math.degrees(math.atan2(y, x)))
    return np.array(lat), np.array(lon)


def _local_km(lat, lon, home):
    k = math.cos(math.radians(home[0]))
    return (np.asarray(lon) - home[1]) * k * 111.32, (np.asarray(lat) - home[0]) * 110.57


class Engine:
    gravity = "wgs72"           # TLEs are fitted with WGS72 constants

    def __init__(self, tle_text, ephemeris="de421.bsp", data_dir=".", body_mode="apparent"):
        self.body_mode = body_mode
        loader = Loader(data_dir, verbose=False)
        # UT1 from IERS finals: skyfield's built-in table goes stale (0.14 s ~ 50 m on the ground in 2026-10)
        self.ts = loader.timescale(builtin=False)
        self.eph = loader(ephemeris)
        self.earth = self.eph["earth"]
        self.bodies = {"S": self.eph["sun"], "M": self.eph["moon"]}
        lines = [l.rstrip() for l in tle_text.strip().splitlines() if l.strip()]
        g = {"wgs72": WGS72, "wgs84": WGS84}[self.gravity]
        self.sats = []
        for i in range(0, len(lines), 3):
            s = EarthSatellite.from_satrec(Satrec.twoline2rv(lines[i + 1], lines[i + 2], g), self.ts)
            s.name = lines[i].strip()
            self.sats.append(s)

    # -- positions --
    def _sat_itrs(self, sat, t):
        return sat.at(t).frame_xyz(itrs).km

    def _body_itrs(self, key, t):
        if self.body_mode == "geometric":
            return (self.bodies[key].at(t) - self.earth.at(t)).frame_xyz(itrs).km
        a = self.earth.at(t).observe(self.bodies[key])
        return (a.apparent() if self.body_mode == "apparent" else a).frame_xyz(itrs).km

    def find(self, home, t0, t1, travel_km=160, min_alt=10, coarse_s=4.0, fine_s=0.05, elev_m=0):
        H = wgs84.latlon(home[0], home[1], elev_m).itrs_xyz.km.reshape(3, 1)
        n = int((t1 - t0) * 86400 / coarse_s)
        tc = self.ts.tt_jd(t0.tt + np.arange(n) * coarse_s / 86400)
        body_c = {k: self._body_itrs(k, tc) for k in self.bodies}
        out = []
        for sat in self.sats:
            Sc = self._sat_itrs(sat, tc)
            for key in self.bodies:
                G = _ray_ground(Sc, body_c[key], elev_m / 1000)
                ok = ~np.isnan(G[0])
                los = Sc - G
                sin_alt = (los * _up(np.nan_to_num(G))).sum(0) / np.linalg.norm(los, axis=0)
                ok &= sin_alt > math.sin(math.radians(min_alt))
                # generous radius: the footprint can travel far between two coarse samples
                d = np.linalg.norm(G - H, axis=0)
                hit = ok & (d < travel_km + 400)
                for run in _runs(np.flatnonzero(hit)):
                    tr = self._refine(sat, key, home, H, tc[run[0]].tt - 2 * coarse_s / 86400,
                                      tc[run[-1]].tt + 2 * coarse_s / 86400, fine_s, min_alt, elev_m)
                    if tr and tr.dist_cl_km <= travel_km:
                        out.append(tr)
        return sorted(out, key=lambda x: x.t_center.tt)

    def _refine(self, sat, key, home, H, jd0, jd1, step_s, min_alt, elev_m):
        n = max(2, int((jd1 - jd0) * 86400 / step_s))
        t = self.ts.tt_jd(np.linspace(jd0, jd1, n))
        S, B = self._sat_itrs(sat, t), self._body_itrs(key, t)
        G = _ray_ground(S, B, elev_m / 1000)
        los = S - G
        sin_alt = (los * _up(np.nan_to_num(G))).sum(0) / np.linalg.norm(los, axis=0)
        good = ~np.isnan(G[0]) & (sin_alt > math.sin(math.radians(min_alt)))
        if good.sum() < 2:
            return None
        idx = np.flatnonzero(good)
        lat, lon = _xyz_to_latlon(G[:, idx])
        x, y = _local_km(lat, lon, home)
        # point of the centerline nearest to home (segment projection)
        best = None
        for i in range(len(x) - 1):
            dx, dy = x[i + 1] - x[i], y[i + 1] - y[i]
            L2 = dx * dx + dy * dy or 1e-12
            u = min(1, max(0, -(x[i] * dx + y[i] * dy) / L2))
            d = math.hypot(x[i] + u * dx, y[i] + u * dy)
            if best is None or d < best[0]:
                best = (d, i, u)
        d, i, u = best
        jd_c = t.tt[idx[i]] + u * (t.tt[idx[i + 1]] - t.tt[idx[i]])
        spot = (lat[i] + u * (lat[i + 1] - lat[i]), lon[i] + u * (lon[i + 1] - lon[i]))
        tc = self.ts.tt_jd(jd_c)
        norad = sat.model.satnum
        tr = Transit(sat.name, norad, key, tc, spot, d, list(zip(lat.tolist(), lon.tolist())))
        tr.at_spot = self.view(sat, key, spot, tc, elev_m)
        tr.at_home = self.view_min_sep(sat, key, home, t, elev_m)
        return tr

    # -- observables --
    def view(self, sat, key, latlon, t, elev_m=0):
        """Geometry seen from latlon at time t."""
        obs = wgs84.latlon(latlon[0], latlon[1], elev_m)
        span = SAT_SPAN_M.get(sat.model.satnum, 20.0) / 1000
        dt = 0.05 / 86400
        tt = self.ts.tt_jd([t.tt - dt, t.tt, t.tt + dt])
        so = (sat - obs).at(tt)
        bo = (self.earth + obs).at(tt).observe(self.bodies[key]).apparent()
        alt, az, rng = so.altaz()
        s_vec = so.frame_xyz(itrs).km
        b_vec = bo.frame_xyz(itrs).km
        s_hat = s_vec / np.linalg.norm(s_vec, axis=0)
        b_hat = b_vec / np.linalg.norm(b_vec, axis=0)
        body_dist = np.linalg.norm(b_vec[:, 1])
        body_ang = 2 * math.asin(BODY_RADIUS_KM[key] / body_dist)       # rad
        sep = math.acos(min(1, float(np.dot(s_hat[:, 1], b_hat[:, 1]))))
        # apparent motion relative to the body, projected on a zenith-up frame
        rel = (s_hat[:, 2] - b_hat[:, 2]) - (s_hat[:, 0] - b_hat[:, 0])
        up_geo = obs.itrs_xyz.km / np.linalg.norm(obs.itrs_xyz.km)
        c = b_hat[:, 1]
        upv = up_geo - np.dot(up_geo, c) * c
        upv /= np.linalg.norm(upv)
        right = np.cross(c, upv)
        mx, my = float(np.dot(rel, right)), float(np.dot(rel, upv))
        omega = math.hypot(mx, my) / 0.1                                  # rad/s
        R = rng.km[1]
        return {
            "range_km": R,
            "size_arcsec": math.degrees(span / R) * 3600,
            "alt": alt.degrees[1], "az": az.degrees[1],
            "sep_arcmin": math.degrees(sep) * 60,
            "body_arcmin": math.degrees(body_ang) * 60,
            "omega_arcmin_s": math.degrees(omega) * 60,
            "duration_s": body_ang / omega if omega else None,
            "motion_dir": math.degrees(math.atan2(-mx, my)),
            "width_km": self.band_width(sat, key, latlon, t, R, body_ang, elev_m),
        }

    def view_min_sep(self, sat, key, latlon, t_arr, elev_m=0):
        """Closest approach to the body as seen from latlon within t_arr."""
        obs = wgs84.latlon(latlon[0], latlon[1], elev_m)
        so = (sat - obs).at(t_arr)
        bo = (self.earth + obs).at(t_arr).observe(self.bodies[key]).apparent()
        sep = so.separation_from(bo).degrees
        i = int(np.nanargmin(sep))
        alt, az, rng = so.altaz()
        span = SAT_SPAN_M.get(sat.model.satnum, 20.0) / 1000
        return {"t": t_arr[i], "sep_arcmin": sep[i] * 60, "alt": alt.degrees[i], "az": az.degrees[i],
                "range_km": rng.km[i], "size_arcsec": math.degrees(span / rng.km[i]) * 3600}

    def band_width(self, sat, key, latlon, t, R, body_ang, elev_m):
        """Width of the visibility path: the cone from the satellite spanning the body's disk, cut by the ground, measured across the centerline."""
        S = self._sat_itrs(sat, t).reshape(3, 1)
        B = self._body_itrs(key, t).reshape(3, 1)
        d = (S - B)[:, 0]
        d /= np.linalg.norm(d)
        e1 = np.cross(d, [0, 0, 1.0]); e1 /= np.linalg.norm(e1)
        e2 = np.cross(d, e1)
        th = np.linspace(0, 2 * math.pi, 360, endpoint=False)
        half = body_ang / 2
        dirs = (math.cos(half) * d[:, None] + math.sin(half) * (np.outer(e1, np.cos(th)) + np.outer(e2, np.sin(th))))
        Bfake = S - dirs * 1e6
        G = _ray_ground(np.repeat(S, len(th), 1), Bfake, elev_m / 1000)
        G = G[:, ~np.isnan(G[0])]
        if G.shape[1] < 10:
            return None
        # centerline direction from footprints 0.2 s apart
        dt = 0.2 / 86400
        tt = self.ts.tt_jd([t.tt - dt, t.tt + dt])
        Gc = _ray_ground(self._sat_itrs(sat, tt), self._body_itrs(key, tt), elev_m / 1000)
        along = Gc[:, 1] - Gc[:, 0]
        up = _up(Gc.mean(1, keepdims=True))[:, 0]
        along -= np.dot(along, up) * up
        along /= np.linalg.norm(along)
        perp = np.cross(up, along)
        proj = perp @ G
        return float(proj.max() - proj.min())


def _runs(idx):
    if len(idx) == 0:
        return []
    splits = np.flatnonzero(np.diff(idx) > 1) + 1
    return np.split(idx, splits)


# ---------- transit-finder mode: reproduces the conventions of transit-finder.com ----------

def _gmst_meeus(jd_utc):
    a = jd_utc - 2451545.0
    b = a / 36525
    return np.radians((280.46061837 + 360.98564736629 * a + 3.87933e-4 * b * b - b ** 3 / 3.871e7) % 360)


def _prec1976(jd):
    T = (jd - 2451545.0) / 36525
    z1 = np.radians((2306.2181 * T + 1.09468 * T * T + 0.018203 * T ** 3) / 3600)
    th = np.radians((2004.3109 * T - 0.42665 * T * T - 0.041833 * T ** 3) / 3600)
    z = np.radians((2306.2181 * T + 0.30188 * T * T + 0.017998 * T ** 3) / 3600)
    cz1, sz1, ct, st, cz, sz = np.cos(z1), np.sin(z1), np.cos(th), np.sin(th), np.cos(z), np.sin(z)
    return np.array([[cz1 * ct * cz - sz1 * sz, -sz1 * ct * cz - cz1 * sz, -st * cz],
                     [cz1 * ct * sz + sz1 * cz, -sz1 * ct * sz + cz1 * cz, -st * sz],
                     [cz1 * st, -sz1 * st, ct]])


def _rz_neg(theta, v):
    c, s = np.cos(theta), np.sin(theta)
    return np.array([c * v[0] + s * v[1], -s * v[0] + c * v[1], v[2]])


class TFCompatEngine(Engine):
    """SGP4 (WGS84) TEME rotated to Earth-fixed with GMST(UTC); Sun/Moon geometric JPL positions looked up at the
    UTC instant (the Moon lags ~69 s), IAU 1976 precession only, no nutation or aberration. Matched all 24
    transit-finder.com centerlines to ~1 m in an October 2026 comparison."""
    gravity = "wgs84"

    @staticmethod
    def _utc_jd(t):
        return np.atleast_1d(t.tt) - 69.184 / 86400      # TT-UTC, unchanged since 2017

    def _sat_itrs(self, sat, t):
        jd = self._utc_jd(t)
        w = np.floor(jd)
        _, r, _ = sat.model.sgp4_array(w, jd - w)
        out = _rz_neg(_gmst_meeus(jd), np.array(r).T)
        return out if np.ndim(t.tt) else out[:, 0]

    def _body_itrs(self, key, t):
        jd = self._utc_jd(t)
        t_wrong = self.ts.tt_jd(jd)
        v = (self.bodies[key].at(t_wrong) - self.earth.at(t_wrong)).xyz.km.reshape(3, -1)
        v = np.einsum("ijn,jn->in", _prec1976(jd), v)
        out = _rz_neg(_gmst_meeus(jd), v)
        return out if np.ndim(t.tt) else out[:, 0]
