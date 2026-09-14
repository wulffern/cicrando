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
    spots = loops.parking_spots(190000, 6960000, 194000, 6964000, pad=0)
    names = {s['name']: s for s in spots}
    assert set(names) == {'Storli', 'Bårdsgarden'}
    assert abs(names['Storli']['lat'] - 62.6926) < 1e-4 and abs(names['Storli']['lon'] - 9.0955) < 1e-4
    assert names['Storli']['access'] == 'plowed' and names['Storli']['road'] == 'secondary'
