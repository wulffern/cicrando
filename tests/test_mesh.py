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
    leaf, crow, ccol, size, lcost = mesh.build_mesh(costs, slope, refine_deg=15)
    indptr, dst, w = mesh.build_graph(leaf, crow, ccol, lcost)
    src, tgt = (80, 5), (80, 155)                          # straight across the steep band
    d, pred = mesh.dijkstra(indptr, dst, w, int(leaf[src]), np.array([int(leaf[tgt])], dtype=np.int32))
    path = mesh.path_cells(pred, crow, ccol, size, int(leaf[tgt]))
    assert tuple(path[0]) == src and tuple(path[-1]) == tgt
    assert (slope[path[:, 0], path[:, 1]] < 35).all()        # never through the 40° core
    assert np.all(np.abs(np.diff(path, axis=0)).max(axis=1) == 1)   # 8-connected steps
    mcp = MCP_Geometric(costs, fully_connected=True)
    cum, _ = mcp.find_costs(starts=[src], ends=[tgt], find_all_ends=True)
    assert abs(d[int(leaf[tgt])] / 10 / cum[tgt] - 1) < 0.03     # within 3 % of the 10 m optimum
