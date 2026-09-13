import numpy as np

from backend import search as s


def plane(n, deg, res=10):
    rows = np.arange(n)[:, None] * np.ones((1, n))
    return ((n - rows) * res * np.tan(np.radians(deg))).astype('float32')  # rises north, faces south


def test_fall_line_accumulates_in_band_length_and_stops_at_steep_terrain():
    z = plane(80, 25)
    z[50:, :] = plane(80, 35)[50:, :] + (z[49, 0] - plane(80, 35)[49, 0])  # steeper below row 50
    ok = np.ones(z.shape, bool); ok[50:, :] = False
    counted = ok.copy()
    (total_drop, total_len, band_drop, band_len), target = s.fall_line_drop(z, ok.ravel(), counted.ravel())
    # From the top row, the run should stop at row 49: 49 steps of 10 m at 25 degrees.
    expected_drop = 49 * 10 * np.tan(np.radians(25))
    assert np.isclose(band_drop[0, 40], expected_drop, atol=0.5)
    assert np.isclose(band_len[0, 40], 49 * 10 / np.cos(np.radians(25)), atol=1)
    assert band_drop[49, 40] == 0
    assert target[10, 40] == 11 * 80 + 40  # straight south


def test_gentle_interruption_counts_towards_total_but_not_band():
    z = plane(60, 25)
    ok = np.ones(z.shape, bool)
    counted = ok.copy(); counted[20:25, :] = False  # a five-cell gentle bench
    (total_drop, total_len, band_drop, band_len), _ = s.fall_line_drop(z, ok.ravel(), counted.ravel())
    assert total_len[0, 30] > band_len[0, 30] > 0
    assert np.isclose(total_len[0, 30] - band_len[0, 30], 5 * 10 / np.cos(np.radians(25)), atol=1)


def test_forest_tile_decodes_ar5_colours(monkeypatch, tmp_path):
    from io import BytesIO
    from PIL import Image
    img = np.zeros((1000, 1000, 4), dtype='uint8')
    img[:500, :, :3] = (128, 255, 8); img[:500, :, 3] = 255        # deciduous north half
    img[500:, :500, :3] = (125, 191, 110); img[500:, :500, 3] = 255  # conifer south-west
    img[500:, 500:, :3] = (207, 204, 145); img[500:, 500:, 3] = 255  # not treed
    buf = BytesIO(); Image.fromarray(img).save(buf, format='PNG')
    class R:
        content = buf.getvalue(); headers = {'content-type': 'image/png'}
        def raise_for_status(self): pass
    monkeypatch.setattr(s.httpx, 'get', lambda *a, **k: R())
    monkeypatch.setattr(s, 'CACHE', tmp_path)
    tile = s.forest_tile(0, 0)
    assert tile.shape == (400, 400)
    assert (tile[:200, :] == 2).all() and (tile[200:, :200] == 1).all() and (tile[200:, 200:] == 0).all()
    grid = s.forest_mask(0, 0, 4000, 4000, (400, 400))
    assert grid is not None and (grid == tile).all()
