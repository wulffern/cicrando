import httpx
import pytest
from fastapi.testclient import TestClient

from backend import app as backend


@pytest.fixture
def client():
    backend.jobs.clear()
    backend.forecast_cache.clear()
    return TestClient(backend.app)


def test_unprepared_area_is_not_loaded(client):
    r = client.get('/api/areas/220000_6956000/overlay.png', params=dict(day='2026-01-01'))
    assert r.status_code == 404
    assert client.get('/api/areas/abc/overlay.png', params=dict(day='2026-01-01')).status_code == 422


def test_overlay_rejects_inverted_slope_bounds(client):
    backend.jobs['x'] = {'status': 'ready', 'area_id': '220000_6956000'}
    r = client.get('/api/areas/220000_6956000/overlay.png', params=dict(day='2026-01-01', lower=30, upper=20))
    assert r.status_code == 422


def test_route_validation(client):
    assert client.post('/api/route', json={'points': [[9.5, 62.6]]}).status_code == 422
    assert client.post('/api/route', json={'points': [[0, 0], [1, 1]]}).status_code == 422
    assert client.post('/api/route', json={'points': [[7.1, 62.1], [12.9, 64.4]]}).status_code == 422  # > 200 km


def test_conditions_report_unavailable_sources(client, monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError('offline')
    monkeypatch.setattr(backend.httpx, 'get', boom)
    r = client.get('/api/conditions', params=dict(lon=9.55, lat=62.64, day='2026-02-01'))
    assert r.status_code == 200
    body = r.json()
    assert body['avalanche'] is None and body['weather'] is None
    assert set(body['errors']) == {'avalanche', 'weather'}


def test_conditions_cache_and_stale_forecast_passthrough(client, monkeypatch):
    calls = []
    class R:
        status_code = 200; headers = {}
        def __init__(self, v): self.v = v
        def raise_for_status(self): pass
        def json(self): return self.v
    def fake(url, params=None, headers=None, **k):
        calls.append(url)
        return R([{'RegionName': 'Trollheimen', 'ValidFrom': '2026-02-01T00:00:00', 'ValidTo': '2026-02-01T23:59:59', 'DangerLevel': '2'}] if 'nve' in url else {'properties': {'timeseries': []}})
    monkeypatch.setattr(backend.httpx, 'get', fake)
    for _ in range(2):
        body = client.get('/api/conditions', params=dict(lon=9.55, lat=62.64, day='2026-02-01')).json()
    assert body['avalanche'][0]['ValidTo'].startswith('2026-02-01')  # validity is passed through untouched for the client to judge
    assert len(calls) == 2  # second call served from cache
