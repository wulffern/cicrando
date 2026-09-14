"""Parking discovery must accept parking areas (ways with geometry) as well as nodes."""
from backend import loops


def test_parking_ways_use_geometry_centroid(monkeypatch, tmp_path):
    ring = [{'lat': 62.6920, 'lon': 9.0950}, {'lat': 62.6920, 'lon': 9.0960}, {'lat': 62.6932, 'lon': 9.0960}, {'lat': 62.6932, 'lon': 9.0950}]
    data = {'elements': [
        {'type': 'way', 'id': 1, 'bounds': {}, 'geometry': ring, 'tags': {'amenity': 'parking', 'name': 'Storli'}},
        {'type': 'node', 'id': 2, 'lat': 62.68, 'lon': 9.15, 'tags': {'amenity': 'parking', 'name': 'Bårdsgarden'}},
        {'type': 'way', 'id': 3, 'geometry': [{'lat': 62.6925, 'lon': 9.0940}, {'lat': 62.6925, 'lon': 9.0970}], 'tags': {'highway': 'secondary'}},
    ]}
    monkeypatch.setattr(loops, 'osm_access', lambda *a, **k: data)
    monkeypatch.setattr(loops, 'nvdb_unplowed', lambda *a, **k: loops.np.zeros((0, 2)))
    monkeypatch.setattr(loops, 'nvdb_parkings', lambda *a, **k: [])
    spots = loops.parking_spots(190000, 6960000, 194000, 6964000, pad=0)
    names = {s['name']: s for s in spots}
    assert set(names) == {'Storli', 'Bårdsgarden'}
    assert abs(names['Storli']['lat'] - 62.6926) < 1e-4 and abs(names['Storli']['lon'] - 9.0955) < 1e-4
    assert names['Storli']['access'] == 'plowed' and names['Storli']['road'] == 'secondary'


def test_town_car_parks_are_not_trailheads(monkeypatch):
    node = lambda i, lon, tags: {'type': 'node', 'id': i, 'lat': 62.68, 'lon': lon, 'tags': {'amenity': 'parking', **tags}}
    data = {'elements': [
        node(1, 9.10, {'name': 'Trailhead'}),
        node(2, 9.11, {'name': 'Private', 'access': 'private'}),
        node(3, 9.12, {'name': 'Shop', 'access': 'customers'}),
        node(4, 9.13, {'name': 'Garage', 'parking': 'multi-storey'}),
        node(5, 9.14, {'name': 'Street', 'parking': 'street_side'}),
        node(6, 9.15, {'name': 'Suburb'}),
        {'type': 'way', 'id': 7, 'geometry': [{'lat': 62.68, 'lon': 9.1499}, {'lat': 62.68, 'lon': 9.1501}], 'tags': {'highway': 'residential'}},
    ]}
    monkeypatch.setattr(loops, 'osm_access', lambda *a, **k: data)
    monkeypatch.setattr(loops, 'nvdb_unplowed', lambda *a, **k: loops.np.zeros((0, 2)))
    monkeypatch.setattr(loops, 'nvdb_parkings', lambda *a, **k: [])
    spots = loops.parking_spots(190000, 6960000, 194000, 6964000, pad=0)
    assert [s['name'] for s in spots] == ['Trailhead']


def test_access_chunk_bbox_covers_rotated_utm_rectangle(monkeypatch, tmp_path):
    # Skaret parking (9.55151, 62.67671) is 216 m inside the UTM chunk's west edge but west of
    # the SW corner's longitude; the query bbox must enclose all four corners.
    from backend.terrain import geo_bbox
    lon0, lat0, lon1, lat1 = geo_bbox(221000, 6957000, 234000, 6970000)
    assert lon0 <= 9.55151 <= lon1 and lat0 <= 62.67671 <= lat1
    seen = {}
    monkeypatch.setattr(loops, 'CACHE', tmp_path)
    monkeypatch.setattr(loops, 'overpass', lambda q, t: seen.setdefault('q', q) and {'elements': []})
    loops.osm_access_chunk(221000, 6957000, 234000, 6970000)
    assert f'({lat0:.4f},{lon0:.4f},{lat1:.4f},{lon1:.4f})' in seen['q']
