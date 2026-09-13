"""Adaptive mesh: refinement where steep, leaf coverage, and Dijkstra agreeing with the fine grid."""
import numpy as np
from skimage.graph import MCP_Geometric

from backend import mesh
from backend.toppturs import ascent_costs


def terrain():
    rng = np.random.default_rng(0)
    slope = np.full((160, 160), 8.0)                       # gentle everywhere
    slope[60:100, 40:120] = 24 + 8 * rng.random((40, 80))  # a steep band (24–32°) with
    slope[75:85, 70:90] = 40                               # an impassable core
    return slope, ascent_costs(slope, 35)


def test_mesh_refines_where_steep_and_covers_everything():
    slope, costs = terrain()
    leaf, crow, ccol, size, lcost = mesh.build_mesh(costs, slope, refine_deg=15)
    assert (leaf >= 0).all()
    assert (size[leaf[60:100, 40:120]] == 1).all()          # 10 m wherever ≥15°
    assert size.max() == 16 and (size == 16).sum() > 20      # gentle ground merges to 160 m
    assert len(crow) < 0.4 * slope.size
    assert np.isfinite(lcost).sum() == len(lcost) - np.isinf(lcost).sum()


def test_dijkstra_matches_fine_grid_cost_and_avoids_impassable():
    slope, costs = terrain()
    src, tgt = (80, 5), (80, 155)                          # straight across the steep band
    leaf, crow, ccol, size, lcost = mesh.build_mesh(costs, slope, refine_deg=15, endpoints=[src, tgt])
    indptr, dst, w = mesh.build_graph(leaf, crow, ccol, lcost, size)
    d, pred = mesh.dijkstra(indptr, dst, w, int(leaf[src]), np.array([int(leaf[tgt])], dtype=np.int32))
    path = mesh.path_cells(pred, crow, ccol, size, int(leaf[tgt]), src, tgt)
    assert tuple(path[0]) == src and tuple(path[-1]) == tgt
    assert (slope[path[:, 0], path[:, 1]] < 35).all()        # never through the 40° core
    assert np.all(np.abs(np.diff(path, axis=0)).max(axis=1) == 1)   # 8-connected steps
    # Cost of the walked path on the 10 m grid (same metric as MCP_Geometric) vs the fine optimum.
    steps = np.hypot(*np.diff(path, axis=0).T)
    cell_cost = costs[path[:, 0], path[:, 1]]
    walked = float(np.sum(steps * (cell_cost[:-1] + cell_cost[1:]) / 2))
    np.testing.assert_allclose(d[leaf[tgt]], walked * 10, rtol=1e-6)
    mcp = MCP_Geometric(costs, fully_connected=True)
    cum, _ = mcp.find_costs(starts=[src], ends=[tgt], find_all_ends=True)
    assert abs(walked / cum[tgt] - 1) < 0.03     # within 3 % of the 10 m optimum


def walked_cost(path, costs):
    values = costs[path[:, 0], path[:, 1]]
    return float(np.sum(np.hypot(*np.diff(path, axis=0).T) * (values[:-1] + values[1:]) / 2) * 10)


def test_same_leaf_paths_are_direct_including_identical_endpoints():
    slope = np.full((16, 16), 8.)
    leaf, cr, cc, size, _ = mesh.build_mesh(ascent_costs(slope, 35), slope)
    for source, target in [((0, 0), (0, 1)), ((0, 0), (0, 0)), ((15, 0), (0, 15))]:
        path = mesh.path_cells(np.array([-1], dtype=np.int32), cr, cc, size, 0, source, target)
        assert tuple(path[0]) == source and tuple(path[-1]) == target
        assert len(path) == max(abs(source[0] - target[0]), abs(source[1] - target[1])) + 1


def test_endpoint_pinning_and_cost_classes_prevent_merging():
    slope = np.full((33, 37), 8.)
    slope[:16, :8] = 12  # Different cost class with configurable lower=10.
    costs = ascent_costs(slope, 35, lower=10)
    endpoints = [(0, 15), (0, 16), (32, 36)]
    leaf, cr, cc, sizes, lc = mesh.build_mesh(costs, slope, endpoints=endpoints)
    assert all(sizes[leaf[c]] == 1 for c in endpoints)
    assert np.array_equal(lc[leaf], costs)
    for a, size in enumerate(sizes):
        r, c = np.where(leaf == a)
        assert len(r) == int(size) ** 2
        assert r.max() - r.min() + 1 == size
        assert c.max() - c.min() + 1 == size


def test_csr_matches_fine_contacts_and_walked_weights_at_every_transition():
    rng = np.random.default_rng(10)
    slope = np.full((65, 79), 8.)
    slope[16:27, 9:21] = rng.choice([16., 24., 32., 40., np.nan], (11, 12))
    slope[40:45, 45:49] = 32
    costs = ascent_costs(slope, 35)
    leaf, cr, cc, sizes, lc = mesh.build_mesh(costs, slope)
    assert set(sizes) == {1, 2, 4, 8, 16}
    indptr, dst, weights = mesh.build_graph(leaf, cr, cc, lc, sizes)
    expected = set()
    for r in range(slope.shape[0]):
        for c in range(slope.shape[1]):
            for dr, dc in [(0, 1), (1, 0), (1, 1), (1, -1)]:
                rr, co = r + dr, c + dc
                if not (0 <= rr < slope.shape[0] and 0 <= co < slope.shape[1]):
                    continue
                a, b = int(leaf[r, c]), int(leaf[rr, co])
                if a != b and np.isfinite(lc[a]) and np.isfinite(lc[b]):
                    expected.update(((a, b), (b, a)))
    actual = {}
    for a in range(len(cr)):
        neighbours = dst[indptr[a]:indptr[a + 1]]
        assert len(neighbours) == len(set(neighbours))
        for j in range(indptr[a], indptr[a + 1]):
            b = int(dst[j])
            actual[a, b] = weights[j]
            path = mesh._walk(np.array([a, b]), cr, cc, sizes, int(cr[a]), int(cc[a]), int(cr[b]), int(cc[b]))
            assert np.isin(leaf[path[:, 0], path[:, 1]], [a, b]).all()
            assert np.isfinite(costs[path[:, 0], path[:, 1]]).all()
            assert (np.abs(np.diff(path, axis=0)).max(axis=1) == 1).all()
            np.testing.assert_allclose(weights[j], walked_cost(path, costs), rtol=1e-6)
    assert set(actual) == expected
    for (a, b), w in actual.items():
        assert w == actual[b, a]
    # Exercise intermediate anchors too, not just endpoint-to-endpoint edges.
    for _ in range(200):
        a, b = list(actual)[rng.integers(len(actual))]
        t = int(rng.choice(dst[indptr[b]:indptr[b + 1]]))
        path = mesh._walk(np.array([a, b, t]), cr, cc, sizes, int(cr[a]), int(cc[a]), int(cr[t]), int(cc[t]))
        assert np.isin(leaf[path[:, 0], path[:, 1]], [a, b, t]).all()
        assert (np.abs(np.diff(path, axis=0)).max(axis=1) == 1).all()
        np.testing.assert_allclose(walked_cost(path, costs), actual[a, b] + actual[b, t], rtol=1e-6)


def test_fully_refined_dijkstra_matches_mcp_with_disconnected_targets():
    rng = np.random.default_rng(9)
    slope = rng.choice([16., 24., 27., 32.], (17, 23))
    slope[:, 11] = 40
    costs = ascent_costs(slope, 35)
    leaf, cr, cc, size, lc = mesh.build_mesh(costs, slope)
    indptr, dst, w = mesh.build_graph(leaf, cr, cc, lc, size)
    targets = [(0, 0), (0, 10), (16, 10), (16, 22)]
    ids = np.array([leaf[c] for c in targets] * 2, dtype=np.int32)
    dist, pred = mesh.dijkstra(indptr, dst, w, int(leaf[0, 0]), ids)
    cumulative, _ = MCP_Geometric(costs, sampling=(10, 10)).find_costs([(0, 0)])
    for c in targets:
        np.testing.assert_allclose(dist[leaf[c]], cumulative[c], rtol=1e-6)
    labels = mesh.components(indptr, dst)
    assert labels[leaf[0, 0]] == labels[leaf[16, 10]]
    assert labels[leaf[0, 0]] != labels[leaf[16, 22]]
    empty, _ = mesh.dijkstra(indptr, dst, w, int(leaf[0, 0]), np.array([], dtype=np.int32))
    assert np.isfinite(empty).sum() == 1
    self_dist, _ = mesh.dijkstra(indptr, dst, w, int(leaf[0, 0]), np.array([leaf[0, 0]], dtype=np.int32))
    assert np.isfinite(self_dist).sum() == 1  # No expansion after the final target.


def test_router_pins_close_endpoints_and_filters_unreachable_targets(monkeypatch):
    from backend.graph import Router
    slope = np.full((32, 48), 8.)
    slope[:, 32] = 40
    costs = ascent_costs(slope, 35)
    z = np.zeros_like(slope)
    endpoints = [(0, 0), (0, 1), (0, 15), (0, 16), (0, 40)]
    router = Router(costs, slope, endpoints=endpoints)
    original = mesh.dijkstra
    calls = []

    def checked(*args):
        calls.append(args[-1])
        assert router.leaf[0, 40] not in args[-1]
        return original(*args)

    monkeypatch.setattr(mesh, 'dijkstra', checked)
    for source, target, expected in [((0, 0), (0, 0), 0), ((0, 0), (0, 1), 10), ((0, 15), (0, 16), 10)]:
        result = router.legs(source, [('near', target), ('far', (0, 40))], z, slope, None, 200000, 7000000, 4, 400)
        assert len(result) == 1 and result[0][0] == 'near'
        assert result[0][1]['length_m'] == expected
    assert len(calls) == 3
    # Ad-hoc callers may introduce endpoints after construction.
    result = router.legs((15, 15), [('new', (15, 16))], z, slope, None, 200000, 7000000, 4, 400)
    assert result[0][1]['length_m'] == 10


def test_published_line_retains_obstacle_detour_after_coordinate_rounding():
    from backend.graph import line
    from backend.terrain import TO_UTM
    path = np.array([(0, 0), (0, 1), (0, 2), (0, 3), (1, 4), (1, 5), (1, 6), (1, 7), (0, 8)])
    serialized = np.array(line(path, 200000, 7000000, 8))
    x, y = TO_UTM.transform(serialized[:, 0], serialized[:, 1])
    cells = np.column_stack(((7000000 - y - 5) / 10, (x - 200000 - 5) / 10))
    np.testing.assert_allclose(cells, np.rint(cells), atol=.002)
    visited = []
    for a, b in zip(cells[:-1], cells[1:]):
        visited.extend(np.rint(np.linspace(a, b, 101)).astype(int).tolist())
    assert [0, 4] not in visited
    assert set(map(tuple, visited)) == set(map(tuple, path))
