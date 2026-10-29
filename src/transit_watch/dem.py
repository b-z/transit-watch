"""Ground elevation in Japan from the GSI elevation tiles (標高タイル, PNG-encoded), the same source and the same
order the interactive map uses: DEM1A (1 m mesh, airborne laser) where it exists, then DEM5A (5 m, laser), DEM5B
(5 m, photogrammetry), DEM10B (10 m). Heights are above the geoid (Tokyo Peil). Tiles are cached on disk.
https://maps.gsi.go.jp/development/demtile.html"""
import math
import struct
import time
import urllib.error
import urllib.request
import zlib

from .data import DATA_DIR, USER_AGENT

LAYERS = (("dem1a_png", 17, "DEM1A"), ("dem5a_png", 15, "DEM5A"), ("dem5b_png", 15, "DEM5B"), ("dem_png", 14, "DEM10B"))
NA = 1 << 23
MAX_AGE_DAYS = 180
_tiles = {}


def _png_rgb(data):
    """Rows of (r, g, b) bytes from an 8-bit, non-interlaced RGB PNG (the format GSI serves)."""
    pos, idat, w = 8, b"", None
    while pos < len(data):
        n, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        if kind == b"IHDR":
            w, h, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", body)
            if (depth, ctype, interlace) != (8, 2, 0):
                raise ValueError("unexpected PNG format")
        elif kind == b"IDAT":
            idat += body
        pos += 12 + n
    raw, stride, rows, prev = zlib.decompress(idat), w * 3, [], bytearray(w * 3)
    for y in range(h):
        f, line = raw[y * (stride + 1)], bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - 3] if i >= 3 else 0
            b = prev[i]
            c = prev[i - 3] if i >= 3 else 0
            if f == 1:
                line[i] = (line[i] + a) & 255
            elif f == 2:
                line[i] = (line[i] + b) & 255
            elif f == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append(bytes(line))
        prev = line
    return rows


def _tile(layer, z, x, y):
    key = (layer, z, x, y)
    if key in _tiles:
        return _tiles[key]
    path = DATA_DIR / "dem" / layer / str(z) / str(x) / f"{y}.png"
    missing = path.with_suffix(".none")
    fresh = lambda p: p.exists() and time.time() - p.stat().st_mtime < MAX_AGE_DAYS * 86400
    rows = None
    if fresh(missing):
        pass
    elif fresh(path):
        rows = _png_rgb(path.read_bytes())
    else:
        url = f"https://cyberjapandata.gsi.go.jp/xyz/{layer}/{z}/{x}/{y}.png"
        for wait in (0, 2, 5):
            time.sleep(wait)
            try:
                data = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}),
                                              timeout=20).read()
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                rows = _png_rgb(data)
                break
            except urllib.error.HTTPError as e:
                if e.code == 404:              # no data for this tile in this layer
                    missing.parent.mkdir(parents=True, exist_ok=True)
                    missing.touch()
                    break
            except Exception:
                continue
    _tiles[key] = rows
    return rows


def _pixel(rows, px, py):
    o = px * 3
    v = rows[py][o] << 16 | rows[py][o + 1] << 8 | rows[py][o + 2]
    return None if v == NA else (v if v < NA else v - (1 << 24)) * 0.01


def height(lat, lon):
    """(elevation in m, source layer), bilinear between the four nearest cells; None over the sea / outside Japan."""
    for layer, z, name in LAYERS:
        n = 2 ** z
        fx = (lon + 180) / 360 * n * 256 - 0.5           # pixel centres sit at +0.5
        r = math.radians(lat)
        fy = (1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2 * n * 256 - 0.5
        x0, y0 = math.floor(fx), math.floor(fy)
        u, v = fx - x0, fy - y0
        vals = []
        for dy in (0, 1):
            for dx in (0, 1):
                gx, gy = x0 + dx, y0 + dy
                rows = _tile(layer, z, gx // 256, gy // 256)
                vals.append(None if rows is None else _pixel(rows, gx % 256, gy % 256))
        if all(h is None for h in vals):
            continue
        if any(h is None for h in vals):                 # coast or data edge: nearest valid cell
            w = [((1 - u) if i % 2 == 0 else u) * ((1 - v) if i < 2 else v) for i in range(4)]
            return max((wi, h) for wi, h in zip(w, vals) if h is not None)[1], name
        return (vals[0] * (1 - u) + vals[1] * u) * (1 - v) + (vals[2] * (1 - u) + vals[3] * u) * v, name
    return None
