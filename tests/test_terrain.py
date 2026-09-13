"""Backend unit tests. No network: rasters are built in memory."""
from datetime import timedelta
import numpy as np
import pytest

from backend import terrain as t


def test_slope_bounds_are_strict():
    slope = np.array([19.99, 20.0, 20.01, 29.99, 30.0, 30.01])
    aspect = np.full(6, 180.0)
    assert t.matches(slope, aspect).tolist() == [False, False, True, True, False, False]


def test_north_aspect_wraps_around():
    slope = np.full(6, 25.0)
    aspect = np.array([0, 45, 46, 314, 315, 359.9])
    assert t.matches(slope, aspect, bearing=0, width=45).tolist() == [True, True, False, False, True, True]


def test_derivatives_recover_plane_slope_and_downslope_aspect():
    res, n = 10, 50
    rows = np.arange(n)[:, None] * np.ones((1, n))
    z = (n - rows) * res * np.tan(np.radians(25))  # rises to the north -> faces south
    slope, aspect = t.derivatives(z, res)
    inner = slice(2, -2)
    assert np.allclose(slope[inner, inner], 25, atol=0.01)
    assert np.allclose(aspect[inner, inner], 180, atol=0.01)
    z_east = np.ones((n, 1)) * np.arange(n)[None, :] * res * np.tan(np.radians(25))  # rises east -> faces west
    _, aspect = t.derivatives(z_east, res)
    assert np.allclose(aspect[inner, inner], 270, atol=0.01)


def test_flat_ground_has_no_aspect():
    slope, aspect = t.derivatives(np.zeros((5, 5)), 10)
    assert np.all(slope == 0) and np.all(np.isnan(aspect))


def test_missing_elevation_propagates_as_unknown():
    z = np.ones((10, 10)) * 100.0
    z[4, 4] = np.nan
    slope, aspect = t.derivatives(z, 10)
    assert np.isnan(slope[3:6, 3:6]).any() and np.isfinite(slope[0, 0])
    raster = t.Raster(z, 0, 100, 10)
    assert np.isnan(raster.sample(45, 55))  # inside the missing cell
    assert np.isnan(raster.sample(-5, 55))  # outside the raster
    assert raster.sample(5, 95) == 100


def test_horizon_invalidates_on_missing_terrain():
    z = np.ones((20, 20)) * 100.0
    raster = t.Raster(z, 0, 200, 10)
    assert t.horizon(raster, 100, 100, 100.0, 0, [10, 20]) == pytest.approx(0)
    z[0, :] = np.nan
    assert np.isnan(t.horizon(raster, 100, 100, 100.0, 0, [10, 50, 95]))


def test_oslo_daylight_saving():
    assert t.local_time('2026-01-15', 12).utcoffset() == timedelta(hours=1)
    assert t.local_time('2026-07-15', 12).utcoffset() == timedelta(hours=2)
    # Solar noon near Oppdal (9.55E) is ~12:22 CET in winter and ~13:22 CEST in summer.
    for day, expected in (('2026-01-15', 12.37), ('2026-07-15', 13.37)):
        hours = np.arange(10, 16, 1 / 60)
        alts = [t.solar(62.64, 9.55, t.local_time(day, h))[1] for h in hours]
        assert hours[int(np.argmax(alts))] == pytest.approx(expected, abs=0.2)


def test_sun_grid_geometry():
    slope = np.full((400, 400), 25.0)
    aspect = np.full((400, 400), 180.0)
    aspect[:, :200] = 0  # west half faces north
    horizons = np.zeros((72, 100, 100), dtype='float32')
    horizons[:, :50, :] = 60  # north half sits behind a 60-degree wall
    area = t.Area('0_0', 0, 0, t.Raster(np.zeros((420, 420)), -100, 4100, 10), slope, aspect, horizons, 0.0, 9.55, 62.64, 0.0)
    grid = area.sun_grid(t.local_time('2026-01-15', 12.4))  # winter noon: sun ~5 deg high, due south
    assert (grid[200:, 200:] == 1).all()   # south-facing, open horizon
    assert (grid[:200, :] == 0).all()      # blocked by terrain
    assert (grid[200:, :200] == 0).all()   # 25 deg north face turned away from a 5 deg sun
    noon = area.sun_grid(t.local_time('2026-03-21', 12.4))  # sun ~27 deg: grazing light reaches the north face
    assert (noon[200:, :200] == 1).all()
    assert (area.sun_grid(t.local_time('2026-01-15', 0)) == 0).all()
    horizons[:, 60, 60] = np.nan
    assert (area.sun_grid(t.local_time('2026-03-21', 12.4))[240:244, 240:244] == -1).all()


def test_route_metrics_formula_and_steep_flags():
    def sampler(xs, ys):
        # 100 m of climb per km eastwards; 35 deg terrain for x in [500, 600] m from the start.
        heights = (xs - xs[0]) / 10
        slopes = np.where((xs - xs[0] >= 500) & (xs - xs[0] < 600), 35.0, 10.0)
        return heights, slopes
    lon0, lat0 = 9.55, 62.64
    x0, y0 = t.TO_UTM.transform(lon0, lat0)
    lon1, lat1 = t.TO_LL.transform(x0 + 4000, y0)
    r = t.route_metrics([(lon0, lat0), (lon1, lat1)], 4, 400, sampler)
    assert r['distance_km'] == pytest.approx(4.0, abs=0.01)
    assert r['ascent_m'] == pytest.approx(400, abs=1)
    assert r['hours'] == pytest.approx(2.0, abs=0.01)
    assert r['in_target'] is False and r['complete'] and r['coverage'] == 100
    assert r['steep_samples'] == 10 and r['max_slope'] == 35


def test_route_with_missing_terrain_withholds_estimate():
    def sampler(xs, ys):
        heights = np.zeros(len(xs)); heights[len(xs)//2:] = np.nan
        return heights, np.zeros(len(xs))
    r = t.route_metrics([(9.55, 62.64), (9.57, 62.64)], 4, 400, sampler)
    assert r['hours'] is None and r['ascent_m'] is None and r['in_target'] is None
    assert not r['complete'] and 40 < r['coverage'] < 60
    assert any(p['elevation'] is None for p in r['profile'])
