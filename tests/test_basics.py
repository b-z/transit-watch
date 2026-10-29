import math

import numpy as np

from transit_watch import config, geo
from transit_watch.engine import _ray_ground, _xyz_to_latlon
from transit_watch.render import screen_deg


def test_ray_straight_down_hits_subpoint():
    # satellite 400 km above (35N, 140E), body far away straight overhead -> footprint is the subpoint
    lat, lon = math.radians(35), math.radians(140)
    up = np.array([math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat)])
    S = (up * 6771).reshape(3, 1)
    B = (up * 1e9).reshape(3, 1)
    G = _ray_ground(S, B)
    la, lo = _xyz_to_latlon(G)
    assert abs(lo[0] - 140) < 1e-6
    assert abs(la[0] - 35.19) < 0.05          # geocentric 35° is ~35.19° geodetic


def test_ray_pointing_away_misses():
    S = np.array([[7000.0], [0], [0]])
    B = np.array([[-1e9], [0], [0]])          # body behind the Earth
    G = _ray_ground(S, B)
    assert np.isnan(G[0, 0]) or np.linalg.norm(G[:, 0]) < 6400


def test_screen_deg_zenith_is_up():
    assert abs(screen_deg(0) - (-90)) < 1e-9   # SVG y grows downwards, so "up" is -90°
    assert abs((screen_deg(90) - 180) % 360) < 1e-9    # counter-clockwise from zenith -> left


def test_config_roundtrip(tmp_path):
    cfg = config._merge(config.DEFAULTS, {"location": {"latitude": 35.0, "longitude": 139.0, "timezone": "Asia/Tokyo"}})
    p = config.save(cfg, tmp_path / "c.toml")
    back = config.load(p)
    assert back["location"]["latitude"] == 35.0
    assert back["rules"]["iss"]["moon"]["min_illumination"] == 0.6
    assert back["search"]["satellites"] == [25544, 48274, 20580]


def test_local_xy_roundtrip():
    o = (35.0, 139.0)
    (x, y), = geo.local_xy([(35.1, 139.2)], o)
    assert geo.from_local(x, y, o) == (35.1, 139.2) or np.allclose(geo.from_local(x, y, o), (35.1, 139.2))
    assert geo.bearing_index(1, 1) == 1 and geo.bearing_index(0, -1) == 4


def test_land_spot_independent_of_sampling(monkeypatch):
    """The chosen spot must not move along the line just because the line was sampled at other instants."""
    from transit_watch import geo
    home = (35.0, 139.0)
    monkeypatch.setattr(geo, "elevation_lookup", lambda provider, lat, lon: 10.0 if lon > 139.05 else None)

    def line(offset_km, step_km):
        pts, s = [], -100 + offset_km
        while s < 100:
            pts.append(geo.from_local(s, 2.0 + 0.1 * s, home))
            s += step_km
        return pts

    a = geo.nearest_land_on_line(line(0.0, 0.37), home)
    b = geo.nearest_land_on_line(line(0.21, 0.29), home)
    assert a and b
    (x, y), = geo.local_xy([a[1:3]], b[1:3])
    assert math.hypot(x, y) < 0.01                        # within 10 m
