"""Terrain-adaptive mesh for least-cost legs — h-refinement driven by slope.

Leaves are 10 m cells wherever any cell in the block is steep (≥ `refine_deg`) or impassable, and
merge into 20/40/80/160 m cells over gentle uniform ground. Hanging nodes are handled by letting
every leaf connect to every leaf it touches. Edge weight = centre distance × mean cost per metre,
the same semantics as skimage's MCP_Geometric on the fine grid. A compiled Dijkstra with early
termination answers one source at a time on the whole block, no windows.
"""
from __future__ import annotations

import heapq
import numpy as np
from numba import njit

LEVELS = (2, 4, 8, 16)   # block sizes in 10 m cells that may merge, coarsest last


def build_mesh(costs, slope, refine_deg=20.0):
    """Quadtree leaves. Returns (leaf id raster int32, centre rows, centre cols, sizes, leaf cost)."""
    rows, cols = costs.shape
    fine = ~np.isfinite(costs) | (np.nan_to_num(slope, nan=90.0) >= refine_deg)
    leaf = np.full((rows, cols), -1, dtype=np.int32)
    ids, crow, ccol, size, lcost = [], [], [], [], []
    # Coarsest first: a block merges if none of its cells must stay fine and it is not already claimed.
    for k in LEVELS[::-1]:
        r, c = rows // k * k, cols // k * k
        fb = fine[:r, :c].reshape(r // k, k, c // k, k).any(axis=(1, 3))
        taken = (leaf[:r, :c] >= 0).reshape(r // k, k, c // k, k).any(axis=(1, 3))
        ok = ~fb & ~taken
        br, bc = np.nonzero(ok)
        if not len(br):
            continue
        start = len(crow)
        new = np.arange(start, start + len(br), dtype=np.int32)
        blk = costs[:r, :c].reshape(r // k, k, c // k, k).mean(axis=(1, 3))
        crow.extend(br * k + (k - 1) / 2); ccol.extend(bc * k + (k - 1) / 2); size.extend([k] * len(br)); lcost.extend(blk[br, bc])
        # Paint the leaf ids into the raster.
        view = leaf[:r, :c].reshape(r // k, k, c // k, k)
        view[br, :, bc, :] = new[:, None, None]
    # Everything unclaimed is a 10 m leaf.
    fr, fc = np.nonzero(leaf < 0)
    start = len(crow)
    leaf[fr, fc] = np.arange(start, start + len(fr), dtype=np.int32)
    crow.extend(fr); ccol.extend(fc); size.extend([1] * len(fr)); lcost.extend(costs[fr, fc])
    return leaf, np.asarray(crow, dtype='float64'), np.asarray(ccol, dtype='float64'), np.asarray(size, dtype=np.int64), np.asarray(lcost, dtype='float32')


def build_graph(leaf, crow, ccol, lcost):
    """CSR adjacency over leaves: every pair of touching leaves (8-connected), weight in cost-metres."""
    rows, cols = leaf.shape
    pairs = []
    for dr, dc in ((0, 1), (1, 0), (1, 1), (1, -1)):
        a = leaf[max(0, -dr):rows - max(0, dr), max(0, -dc):cols - max(0, dc)]
        b = leaf[max(0, dr):rows - max(0, -dr), max(0, dc):cols - max(0, -dc)]
        m = a != b
        pairs.append(np.stack([a[m], b[m]], axis=1))
    p = np.concatenate(pairs).astype(np.int64)
    n = len(crow)
    key = np.unique(np.minimum(p[:, 0], p[:, 1]) * n + np.maximum(p[:, 0], p[:, 1]))   # undirected, deduplicated
    p = np.stack([key // n, key % n], axis=1)
    both = np.concatenate([p, p[:, ::-1]])
    dr = np.abs(crow[both[:, 0]] - crow[both[:, 1]]); dc = np.abs(ccol[both[:, 0]] - ccol[both[:, 1]])
    # Octile distance: the length of an 8-connected grid path, so coarse cells cannot undercut fine ones.
    dist = (np.maximum(dr, dc) + (np.sqrt(2) - 1) * np.minimum(dr, dc)) * 10.0
    w = (dist * (lcost[both[:, 0]] + lcost[both[:, 1]]) / 2).astype('float32')
    w[~np.isfinite(w)] = np.inf
    order = np.argsort(both[:, 0], kind='stable')
    src, dst, w = both[order, 0], both[order, 1], w[order]
    indptr = np.zeros(len(crow) + 1, dtype=np.int64)
    np.add.at(indptr, src + 1, 1); indptr = np.cumsum(indptr)
    return indptr, dst.astype(np.int32), w


@njit(cache=True)
def dijkstra(indptr, dst, w, source, targets):
    """Single-source Dijkstra stopping once every target is settled. Returns (dist, predecessor)."""
    n = len(indptr) - 1
    dist = np.full(n, np.inf, dtype=np.float64)
    pred = np.full(n, -1, dtype=np.int32)
    done = np.zeros(n, dtype=np.bool_)
    want = np.zeros(n, dtype=np.bool_)
    remaining = 0
    for t in targets:
        if not want[t]:
            want[t] = True; remaining += 1
    dist[source] = 0.0
    heap = [(0.0, np.int64(source))]
    while len(heap) > 0 and remaining > 0:
        d, u = heapq.heappop(heap)
        if done[u]:
            continue
        done[u] = True
        if want[u]:
            remaining -= 1
        for k in range(indptr[u], indptr[u + 1]):
            v = dst[k]
            nd = d + w[k]
            if nd < dist[v]:
                dist[v] = nd; pred[v] = u
                heapq.heappush(heap, (nd, np.int64(v)))
    return dist, pred


@njit(cache=True)
def _walk(chain, crow, ccol, size):
    """Cells visited along centre → exit → entry → centre segments, densified at one cell per step."""
    out = np.empty((len(chain) * 64 + 8, 2), dtype=np.int64)
    n = 0
    pr, pc = crow[chain[0]], ccol[chain[0]]
    out[0, 0] = int(round(pr)); out[0, 1] = int(round(pc)); n = 1
    for k in range(len(chain) - 1):
        a, b = chain[k], chain[k + 1]
        ha, hb = (size[a] - 1) / 2.0, (size[b] - 1) / 2.0
        # entry: cell of b nearest a's centre; exit: cell of a nearest that entry cell
        er = min(max(crow[a], crow[b] - hb), crow[b] + hb); ec = min(max(ccol[a], ccol[b] - hb), ccol[b] + hb)
        xr = min(max(er, crow[a] - ha), crow[a] + ha); xc = min(max(ec, ccol[a] - ha), ccol[a] + ha)
        for (qr, qc) in ((xr, xc), (er, ec), (crow[b], ccol[b])):
            steps = int(np.ceil(max(abs(qr - pr), abs(qc - pc))))
            for t in range(1, max(steps, 1) + 1):
                rr = pr + (qr - pr) * t / max(steps, 1); cc = pc + (qc - pc) * t / max(steps, 1)
                r_i, c_i = int(round(rr)), int(round(cc))
                if r_i != out[n - 1, 0] or c_i != out[n - 1, 1]:
                    if n >= out.shape[0]:
                        bigger = np.empty((out.shape[0] * 2, 2), dtype=np.int64); bigger[:n] = out[:n]; out = bigger
                    out[n, 0] = r_i; out[n, 1] = c_i; n += 1
            pr, pc = qr, qc
    return out[:n]


def path_cells(pred, crow, ccol, size, target):
    """Predecessor chain → 10 m cell path that never leaves the leaves it visits.

    Between two touching leaves the path goes centre → exit cell of the first leaf → entry cell of
    the second → centre, so a segment cannot clip a third (possibly steep) leaf at a hanging node.
    Inside a coarse leaf every cell is gentle, so straight segments there are safe.
    """
    chain = []
    v = target
    while v >= 0:
        chain.append(v); v = pred[v]
    chain.reverse()
    return _walk(np.array(chain, dtype=np.int64), crow, ccol, size)
