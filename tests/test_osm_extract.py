"""Geofabrik extract index: parkings and roads answer bbox queries in the Overpass element shape."""
import numpy as np
import osmium

from backend import osm_extract, loops


def write_pbf(path):
    w = osmium.SimpleWriter(str(path))
    # Skaret-like parking node, a parking area (way), a residential road and a track with winter_service=no.
    w.add_node(osmium.osm.mutable.Node(id=1, location=(9.55151, 62.67671), tags={'amenity': 'parking', 'name': 'Skaret', 'parking': 'surface'}))
    for i, (lon, lat) in enumerate([(9.560, 62.680), (9.561, 62.680), (9.561, 62.681), (9.560, 62.681)], start=10):
        w.add_node(osmium.osm.mutable.Node(id=i, location=(lon, lat)))
    w.add_way(osmium.osm.mutable.Way(id=100, nodes=[10, 11, 12, 13, 10], tags={'amenity': 'parking', 'name': 'Remma'}))
    for i, (lon, lat) in enumerate([(9.550, 62.676), (9.552, 62.677)], start=20):
        w.add_node(osmium.osm.mutable.Node(id=i, location=(lon, lat)))
    w.add_way(osmium.osm.mutable.Way(id=200, nodes=[20, 21], tags={'highway': 'service'}))
    for i, (lon, lat) in enumerate([(9.70, 62.70), (9.71, 62.70)], start=30):
        w.add_node(osmium.osm.mutable.Node(id=i, location=(lon, lat)))
    w.add_way(osmium.osm.mutable.Way(id=300, nodes=[30, 31], tags={'highway': 'track', 'winter_service': 'no'}))
    w.add_node(osmium.osm.mutable.Node(id=40, location=(12.0, 63.0), tags={'amenity': 'parking', 'name': 'Far away'}))
    w.close()


def test_index_and_bbox_query_feed_parking_spots(tmp_path, monkeypatch):
    pbf = tmp_path / 'tiny.osm.pbf'
    write_pbf(pbf)
    n_park, n_pts = osm_extract.build_index(pbf, 'tiny', tmp_path)
    assert n_park == 3 and n_pts == 4
    assert osm_extract.available(tmp_path) == ['tiny']
    # The Skaret chunk from the Overpass bbox bug: the UTM box must include the node at 9.55151.
    data = osm_extract.access(221000, 6957000, 234000, 6970000, tmp_path)
    names = sorted(e['tags'].get('name') for e in data['elements'] if e['tags'].get('amenity') == 'parking')
    assert names == ['Remma', 'Skaret']
    roads = [e for e in data['elements'] if 'highway' in e['tags']]
    assert sorted(r['id'] for r in roads) == [200, 300] and all(len(r['geometry']) == 2 for r in roads)
    # The closed track keeps its winter tag so the classifier can mark nearby parkings closed.
    assert any(r['tags'] == {'highway': 'track', 'winter_service': 'no'} for r in roads)
    monkeypatch.setattr(loops, 'osm_access', lambda w, s, e, n: osm_extract.access(w, s, e, n, tmp_path))
    monkeypatch.setattr(loops, 'nvdb_unplowed', lambda *a, **k: np.zeros((0, 2)))
    monkeypatch.setattr(loops, 'nvdb_parkings', lambda *a, **k: [])
    spots = loops.parking_spots(221000, 6957000, 234000, 6970000, pad=0)
    by = {s['name']: s for s in spots}
    assert by['Skaret']['road'] == 'service' and by['Skaret']['access'] == 'unknown'
    assert abs(by['Remma']['lat'] - 62.6805) < 1e-3


def test_no_index_means_none(tmp_path):
    assert osm_extract.access(0, 0, 1000, 1000, tmp_path) is None
