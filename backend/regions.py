"""Metric scan coverage on the legacy 28 km UTM lattice; no elevation downloads."""
from dataclasses import dataclass
import math

from .terrain import TO_UTM

BLOCK_M = 28000
GRID_ORIGIN = (24000, 12000)  # Preserves the existing 164000/192000/... block coordinates.


@dataclass(frozen=True)
class Region:
    origin: tuple[float, float]
    shape: str = 'circle'
    extent_km: float = 60  # Radius for a circle, full side length for a square.

    def __post_init__(self):
        lon, lat = self.origin
        if not (math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 < lat < 90):
            raise ValueError('Origin must be finite longitude/latitude coordinates')
        if self.shape not in ('circle', 'square') or not math.isfinite(self.extent_km) or self.extent_km <= 0:
            raise ValueError('Choose a circle or square with a positive finite extent')
        if not all(map(math.isfinite, self.centre)):
            raise ValueError('Origin cannot be projected into UTM zone 33')

    @property
    def centre(self):
        return TO_UTM.transform(*self.origin)

    @property
    def half_extent(self):
        return self.extent_km * (1000 if self.shape == 'circle' else 500)

    def contains(self, x, y):
        ox, oy = self.centre
        dx, dy = abs(x - ox), abs(y - oy)
        return math.hypot(dx, dy) <= self.half_extent if self.shape == 'circle' else max(dx, dy) <= self.half_extent

    def blocks(self):
        return intersecting_blocks(*self.centre, self.half_extent, self.shape)

    def metadata(self):
        return dict(shape=self.shape, **{('radius_km' if self.shape == 'circle' else 'side_km'): self.extent_km},
                    crs='EPSG:25833', origin=list(self.origin))


def intersecting_blocks(x, y, radius, shape='circle'):
    """Include boundary intersections, not just block centres. Radius is square half-side."""
    gx, gy = GRID_ORIGIN
    # Include the block on either side when a bound lies exactly on a grid line.
    ix0, iy0 = math.ceil((x - radius - gx) / BLOCK_M) - 1, math.ceil((y - radius - gy) / BLOCK_M) - 1
    ix1, iy1 = math.floor((x + radius - gx) / BLOCK_M), math.floor((y + radius - gy) / BLOCK_M)
    blocks = []
    for iy in range(iy0, iy1 + 1):
        for ix in range(ix0, ix1 + 1):
            west, south = gx + ix * BLOCK_M, gy + iy * BLOCK_M
            dx = max(west - x, 0, x - west - BLOCK_M)
            dy = max(south - y, 0, y - south - BLOCK_M)
            if shape == 'circle' and math.hypot(dx, dy) > radius:
                continue
            blocks.append(dict(x=west, y=south, dist_km=math.hypot(west + BLOCK_M / 2 - x, south + BLOCK_M / 2 - y) / 1000))
    return sorted(blocks, key=lambda b: (b['dist_km'], b['x'], b['y']))


def approach_blocks(parkings, reach_km=12):
    blocks = {}
    for p in parkings:
        for b in intersecting_blocks(p['x'], p['y'], reach_km * 1000):
            blocks[b['x'], b['y']] = b
    return sorted(blocks.values(), key=lambda b: (b['x'], b['y']))


class Corridor(Region):
    """Coverage within `extent_km` of one or more driving routes (OSRM geometry, cached)."""

    def __init__(self, origin, legs, extent_km=15, name='corridor'):
        object.__setattr__(self, 'origin', tuple(origin)); object.__setattr__(self, 'shape', 'corridor'); object.__setattr__(self, 'extent_km', extent_km)
        object.__setattr__(self, 'legs', [[tuple(p) for p in leg] for leg in legs]); object.__setattr__(self, 'name', name)
        object.__setattr__(self, '_xy', self._route_points())

    def __post_init__(self):
        pass

    def _route_points(self):
        import json, hashlib
        from pathlib import Path
        import httpx
        import numpy as np
        pts = []
        for leg in self.legs:
            key = hashlib.sha256(json.dumps(leg).encode()).hexdigest()[:16]
            cache = Path('.cache') / f'osrm_route_{key}.json'
            if cache.exists():
                coords = json.loads(cache.read_text())
            else:
                path = ';'.join(f'{lon:.5f},{lat:.5f}' for lon, lat in leg)
                r = httpx.get(f'https://router.project-osrm.org/route/v1/driving/{path}', params=dict(overview='full', geometries='geojson'),
                              timeout=60, headers={'User-Agent': 'cicrando/0.1 terrain planner'})
                r.raise_for_status()
                coords = r.json()['routes'][0]['geometry']['coordinates']
                cache.parent.mkdir(parents=True, exist_ok=True); cache.write_text(json.dumps(coords))
            pts.extend(coords)
        lon, lat = np.array(pts).T
        x, y = TO_UTM.transform(lon, lat)
        return np.column_stack([x, y])

    @property
    def half_extent(self):
        return self.extent_km * 1000

    def contains(self, x, y):
        import numpy as np
        return bool(np.hypot(self._xy[:, 0] - x, self._xy[:, 1] - y).min() <= self.half_extent)

    def blocks(self):
        import numpy as np
        gx, gy = GRID_ORIGIN
        found = {}
        for x, y in self._xy[::5]:
            for b in intersecting_blocks(float(x), float(y), self.half_extent, 'square'):
                found[b['x'], b['y']] = b
        ox, oy = self.centre
        out = []
        for b in found.values():
            cx, cy = b['x'] + BLOCK_M / 2, b['y'] + BLOCK_M / 2
            dx = np.maximum(0, np.maximum(b['x'] - self._xy[:, 0], self._xy[:, 0] - b['x'] - BLOCK_M))
            dy = np.maximum(0, np.maximum(b['y'] - self._xy[:, 1], self._xy[:, 1] - b['y'] - BLOCK_M))
            if np.hypot(dx, dy).min() <= self.half_extent:
                out.append(dict(x=b['x'], y=b['y'], dist_km=math.hypot(cx - ox, cy - oy) / 1000))
        return sorted(out, key=lambda b: (b['dist_km'], b['x'], b['y']))

    def metadata(self):
        return dict(shape='corridor', buffer_km=self.extent_km, legs=self.legs, crs='EPSG:25833', origin=list(self.origin), name=self.name)
