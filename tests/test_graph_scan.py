import json
from pathlib import Path

from backend import graph_scan as scan
from backend.regions import Region
from backend.terrain import TO_LL


def spot(x, y, access='unknown'):
    lon, lat = TO_LL.transform(x, y)
    return dict(x=x, y=y, lon=lon, lat=lat, access=access, name=None, road=None, tags={})


def test_planning_filters_before_terrain_and_preserves_unknown(monkeypatch):
    region = Region(tuple(TO_LL.transform(200000, 6960000)), 'circle', 1)
    spots = [spot(200000 + i * 100, 6960000) for i in range(4)] + [spot(200500, 6960000, 'closed'), spot(220000, 6960000)]
    monkeypatch.setattr(scan, 'parking_spots', lambda *a, **k: spots)
    monkeypatch.setattr(scan, 'drive_minutes', lambda origin, points: [60, 120, 121, None])
    monkeypatch.setattr(scan, 'build', lambda *a, **k: (_ for _ in ()).throw(AssertionError('terrain during planning')))
    plan = scan.plan_scan(region, 2)
    assert len(plan['eligible_parkings']) == 2
    assert len(plan['unknown_drive_parkings']) == len(plan['over_limit_parkings']) == 1
    assert plan['terrain_blocks']
    assert plan['parking_count'] == 5  # Closed is discovered but not eligible.
    unlimited = scan.plan_scan(region)
    assert len(unlimited['eligible_parkings']) == 4
    monkeypatch.setattr(scan, 'parking_spots', lambda *a, **k: None)
    missing = scan.plan_scan(region, 2)
    assert missing['missing_parking_blocks'] and not missing['terrain_blocks']


def graph(parking_id='p1', lonlat=(9., 62.)):
    return dict(parkings=[dict(id=parking_id, lonlat=list(lonlat), access='unknown')],
                summits=[dict(id='s1', lonlat=[9.1, 62.1]), dict(id='unreachable', lonlat=[9.2, 62.2])],
                runs=[dict(id='r1', summits=['s1'])],
                edges=[{'from': parking_id, 'to': 's1', 'kind': 'skin', 'hours': 1},
                       {'from': 'r1', 'to': parking_id, 'kind': 'walk', 'hours': .5}], tiles_missing=0)


def test_assembly_deduplicates_and_filters_without_mutating_cache(tmp_path):
    a, b = tmp_path / 'a.json', tmp_path / 'b.json'
    a.write_text(json.dumps(graph()))
    b.write_text(json.dumps(graph('p2')))
    eligible = [dict(lon=9., lat=62., drive_min=70, access='plowed')]
    result = scan.assemble([a, b], eligible)
    assert len(result['parkings']) == 1 and result['parkings'][0]['drive_min'] == 70
    assert [s['id'] for s in result['summits']] == ['s1']
    assert len(result['runs']) == 1 and len(result['edges']) == 2
    assert result['edges'][1]['to'] == 'p1'
    assert 'drive_min' not in json.loads(a.read_text())['parkings'][0]
    assert not scan.assemble([a, b], [])['summits']


def test_distinct_origins_reuse_blocks_but_only_selected_paths_are_merged(tmp_path, monkeypatch):
    region = Region((9., 62.), extent_km=1)
    eligible = [dict(lon=9., lat=62., drive_min=30, access='unknown')]
    plan = dict(origin=list(region.origin), coverage=region.metadata(), max_drive_hours=2, access='open',
                routing=scan.ROUTING, terrain_blocks=[dict(x=192000, y=6956000)], eligible_parkings=eligible,
                missing_parking_blocks=[], unknown_drive_parkings=[], over_limit_parkings=[])
    out = scan.cache_directory(tmp_path, scan.ROUTING)
    out.mkdir(parents=True)
    selected = out / '192000_6956000.json'
    selected.write_text(json.dumps(graph()))
    unrelated = out / '220000_6956000.json'
    unrelated.write_text('invalid JSON must not be read')
    calls = []

    def cached(blocks, worker, directory, **kwargs):
        calls.append(directory)
        return [selected, unrelated]

    monkeypatch.setattr(scan, 'run_blocks', cached)
    monkeypatch.setattr(scan, 'enrich_names', lambda *a: None)
    first = scan.execute_scan(plan, 'First', tmp_path)
    second_plan = dict(plan, origin=[10., 63.], eligible_parkings=[dict(eligible[0], drive_min=90)])
    second = scan.execute_scan(second_plan, 'Second', tmp_path)
    assert calls[0] == calls[1]
    assert first['parkings'][0]['drive_min'] == 30 and second['parkings'][0]['drive_min'] == 90
    assert first['blocks'] == 1 and first['complete']
    assert scan.cache_directory(tmp_path, dict(scan.ROUTING, max_ascent=30)) != out
    monkeypatch.setattr(scan, 'run_blocks', lambda *a, **k: [])
    missing = scan.execute_scan(plan, 'Missing', tmp_path)
    assert not missing['complete'] and missing['missing_terrain_blocks'] == ['192000_6956000']


def test_offline_names_never_call_network(tmp_path, monkeypatch):
    monkeypatch.setenv('RANDO_OFFLINE', '1')
    monkeypatch.setattr(scan.httpx, 'get', lambda *a, **k: (_ for _ in ()).throw(AssertionError('network')))
    summits = [dict(lonlat=[9., 62.])]
    scan.enrich_names(summits, tmp_path)
    assert summits[0]['name'] is None
    (tmp_path / 'placenames.json').write_text(json.dumps({'peak:9.0000,62.0000': {'name': 'Cached peak'}}))
    scan.enrich_names(summits, tmp_path)
    assert summits[0]['name'] == 'Cached peak'


def test_cli_mocked_end_to_end(tmp_path, monkeypatch):
    from scripts import graph_scan as cli
    region = Region((9., 62.), extent_km=1)
    x, y = region.centre
    p = spot(x, y)
    monkeypatch.setattr(scan, 'parking_spots', lambda *a, **k: [p])
    monkeypatch.setattr(scan, 'drive_minutes', lambda *a: [45])
    monkeypatch.setattr(scan, 'enrich_names', lambda *a: None)

    def build_fake(blocks, worker, out, **kwargs):
        out.mkdir(parents=True, exist_ok=True)
        paths = []
        for block in blocks:
            path = out / f"{block['x']}_{block['y']}.json"
            path.write_text(json.dumps(graph(lonlat=scan.parking_key(p['lon'], p['lat']))))
            paths.append(path)
        return paths

    monkeypatch.setattr(scan, 'run_blocks', build_fake)
    output = tmp_path / 'result.json'
    cli.main(['--origin', '9', '62', '--name', 'Test', '--radius-km', '1', '--max-drive-hours', '1',
              '--cache-root', str(tmp_path), '--output', str(output)])
    result = json.loads(output.read_text())
    assert result['complete'] and result['max_drive_hours'] == 1
    assert result['origin'] == [9., 62.] and result['coverage']['radius_km'] == 1
    assert len(result['parkings']) == 1 and result['parkings'][0]['drive_min'] == 45


def test_terrain_buffer_expands_selection_without_changing_cached_routing(monkeypatch, tmp_path):
    region = Region(tuple(TO_LL.transform(200000, 6960000)), extent_km=1)
    monkeypatch.setattr(scan, 'parking_spots', lambda *a, **k: [spot(*region.centre)])
    monkeypatch.setattr(scan, 'drive_minutes', lambda *a: [30])
    standard = scan.plan_scan(region, 2)
    wider = scan.plan_scan(region, 2, terrain_buffer_km=20)
    keys = lambda p: {(b['x'], b['y']) for b in p['terrain_blocks']}
    assert keys(standard) < keys(wider)
    assert standard['routing'] == wider['routing']
    assert wider['routing']['reach_km'] == 12 and wider['routing']['margin'] == 12000
    assert scan.cache_directory(tmp_path, standard['routing']) == scan.cache_directory(tmp_path, wider['routing'])
    plowed = scan.plan_scan(region, 2, access='plowed')
    assert not plowed['eligible_parkings'] and not plowed['terrain_blocks']
