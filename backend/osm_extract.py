"""Parkings and roads from Geofabrik OSM extracts (.osm.pbf) instead of live Overpass queries.

`build_index(pbf, name)` makes one compact per-country index under .cache/osm (one pass, needs
RAM for the node location cache — a few GB for Norway); `access(west, south, east, north)` then
answers UTM bbox queries from every index present, returning elements in the Overpass response
shape that `loops.parking_spots` already understands. Same OSM data (ODbL), but a snapshot: no
rate limits, no mirrors, works offline; refresh by re-downloading the extract.
"""
from __future__ import annotations

import gzip
import json
import logging
from pathlib import Path

import numpy as np

from .terrain import geo_bbox

logger = logging.getLogger('rando.osm')
OSM_DIR = Path('.cache/osm')
ROAD_CLASSES = ('motorway', 'trunk', 'primary', 'secondary', 'tertiary', 'unclassified', 'residential', 'service', 'track')
WINTER_TAGS = ('winter_service', 'seasonal', 'snowplowing')
PARKING_TAGS = ('amenity', 'name', 'access', 'fee', 'parking', 'capacity', 'winter_service', 'description')
GEOFABRIK = {'norway': 'https://download.geofabrik.de/europe/norway-latest.osm.pbf',
             'sweden': 'https://download.geofabrik.de/europe/sweden-latest.osm.pbf'}


def build_index(pbf: Path, name: str, out_dir: Path = OSM_DIR):
    """One pass over the extract: parking nodes/areas and driveable or winter-tagged road points."""
    import osmium
    parkings, lon, lat, cls, closed, way = [], [], [], [], [], []

    class Collector(osmium.SimpleHandler):
        def node(self, n):
            if n.tags.get('amenity') == 'parking':
                parkings.append(dict(type='node', id=n.id, lat=n.location.lat, lon=n.location.lon,
                                     tags={t.k: t.v for t in n.tags if t.k in PARKING_TAGS}))

        def way(self, w):
            t = w.tags
            hw = t.get('highway')
            pts = [(n.location.lon, n.location.lat) for n in w.nodes if n.location.valid()]
            if not pts:
                return
            if t.get('amenity') == 'parking':
                parkings.append(dict(type='way', id=w.id, geometry=[{'lat': y, 'lon': x} for x, y in pts],
                                     center={'lat': sum(p[1] for p in pts) / len(pts), 'lon': sum(p[0] for p in pts) / len(pts)},
                                     tags={x.k: x.v for x in t if x.k in PARKING_TAGS}))
            elif hw and (hw in ROAD_CLASSES or any(k in t for k in WINTER_TAGS)):
                shut = t.get('winter_service') == 'no' or t.get('snowplowing') == 'no' or t.get('seasonal') in ('summer', 'yes')
                code = ROAD_CLASSES.index(hw) if hw in ROAD_CLASSES else 255
                for x, y in pts:
                    lon.append(x); lat.append(y); cls.append(code); closed.append(shut); way.append(w.id)

    Collector().apply_file(str(pbf), locations=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out_dir / f'{name}-roads.npz', lon=np.array(lon, 'float32'), lat=np.array(lat, 'float32'),
                        cls=np.array(cls, 'uint8'), closed=np.array(closed, bool), way=np.array(way, 'int64'))
    with gzip.open(out_dir / f'{name}-parkings.json.gz', 'wt') as f:
        json.dump(parkings, f)
    logger.info('%s: %d parkings, %d road points', name, len(parkings), len(lon))
    return len(parkings), len(lon)


_INDEX = {}


def _load(name, out_dir):
    if name not in _INDEX:
        roads = np.load(out_dir / f'{name}-roads.npz')
        with gzip.open(out_dir / f'{name}-parkings.json.gz', 'rt') as f:
            parkings = json.load(f)
        p_lon = np.array([p['lon'] if 'lon' in p else p['center']['lon'] for p in parkings])
        p_lat = np.array([p['lat'] if 'lat' in p else p['center']['lat'] for p in parkings])
        _INDEX[name] = dict(roads={k: roads[k] for k in roads.files}, parkings=parkings, p_lon=p_lon, p_lat=p_lat)
    return _INDEX[name]


def available(out_dir: Path = OSM_DIR):
    return sorted(p.name[:-len('-roads.npz')] for p in out_dir.glob('*-roads.npz') if (out_dir / f'{p.name[:-len("-roads.npz")]}-parkings.json.gz').exists())


def access(west, south, east, north, out_dir: Path = OSM_DIR):
    """Overpass-shaped {'elements': [...]} for a UTM bbox from every index present; None when there is none."""
    names = available(out_dir)
    if not names:
        return None
    lon0, lat0, lon1, lat1 = geo_bbox(west, south, east, north)
    elements = []
    for name in names:
        idx = _load(name, out_dir)
        hit = (idx['p_lon'] >= lon0) & (idx['p_lon'] <= lon1) & (idx['p_lat'] >= lat0) & (idx['p_lat'] <= lat1)
        elements.extend(idx['parkings'][i] for i in np.flatnonzero(hit))
        r = idx['roads']
        hit = (r['lon'] >= lon0) & (r['lon'] <= lon1) & (r['lat'] >= lat0) & (r['lat'] <= lat1)
        sel = np.flatnonzero(hit)
        if not len(sel):
            continue
        order = sel[np.argsort(r['way'][sel], kind='stable')]
        ways, starts = np.unique(r['way'][order], return_index=True)
        for wid, chunk in zip(ways, np.split(order, starts[1:])):
            code = int(r['cls'][chunk[0]])
            tags = {'highway': ROAD_CLASSES[code] if code < len(ROAD_CLASSES) else 'path'}
            if r['closed'][chunk[0]]:
                tags['winter_service'] = 'no'
            elements.append(dict(type='way', id=int(wid), tags=tags,
                                 geometry=[{'lat': float(r['lat'][i]), 'lon': float(r['lon'][i])} for i in chunk]))
    return {'elements': elements}
