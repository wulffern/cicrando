"""Terrain-adaptive mesh for least-cost legs — h-refinement driven by slope.

Leaves remain fine on steep or impassable ground, at routing endpoints, and across cost classes.
Every touching traversable leaf is connected. Edges follow integer cell anchors and shared boundary
portals; their weights equal the cost of the projected 8-connected walk. This remains an
approximation of the full-grid optimum because gentle terrain is routed through leaf anchors.
"""
from __future__ import annotations

import heapq
import numpy as np
from numba import njit

LEVELS = (2, 4, 8, 16)   # block sizes in 10 m cells that may merge, coarsest last


def build_mesh(costs, slope, refine_deg=15.0, endpoints=()):
    """Return leaf IDs, geometric centres, sizes, and uniform leaf costs.

    Endpoints are forced to single-cell leaves so search costs include their exact positions.
    Integer routing anchors are the floor of each geometric centre.
    """
    rows, cols = costs.shape
    fine = ~np.isfinite(costs) | (np.nan_to_num(slope, nan=90.0) >= refine_deg)
    for r, c in endpoints:
        fine[r, c] = True
    leaf = np.full((rows, cols), -1, dtype=np.int32)
    crow, ccol, size, lcost = [], [], [], []
    count = 0
    # Coarsest first: a block merges if none of its cells must stay fine and it is not already claimed.
    for k in LEVELS[::-1]:
        r, c = rows // k * k, cols // k * k
        fb = fine[:r, :c].reshape(r // k, k, c // k, k).any(axis=(1, 3))
        taken = (leaf[:r, :c] >= 0).reshape(r // k, k, c // k, k).any(axis=(1, 3))
        cb = costs[:r, :c].reshape(r // k, k, c // k, k)
        uniform = cb.min(axis=(1, 3)) == cb.max(axis=(1, 3))
        ok = ~fb & ~taken & uniform
        br, bc = np.nonzero(ok)
        if not len(br):
            continue
        start = count
        count += len(br)
        new = np.arange(start, start + len(br), dtype=np.int32)
        crow.append(br * k + (k - 1) / 2)
        ccol.append(bc * k + (k - 1) / 2)
        size.append(np.full(len(br), k, dtype=np.uint8))
        lcost.append(costs[br * k, bc * k])
        # Paint the leaf ids into the raster.
        view = leaf[:r, :c].reshape(r // k, k, c // k, k)
        view[br, :, bc, :] = new[:, None, None]
    # Everything unclaimed is a 10 m leaf.
    fr, fc = np.nonzero(leaf < 0)
    start = count
    leaf[fr, fc] = np.arange(start, start + len(fr), dtype=np.int32)
    crow.append(fr.astype(np.float64)); ccol.append(fc.astype(np.float64))
    size.append(np.ones(len(fr), dtype=np.uint8)); lcost.append(costs[fr, fc])
    return leaf, np.concatenate(crow), np.concatenate(ccol), np.concatenate(size), np.concatenate(lcost).astype(np.float32, copy=False)


@njit(cache=True)
def _leaf_sizes(leaf, n):
    counts = np.zeros(n, dtype=np.int32)
    for r in range(leaf.shape[0]):
        for c in range(leaf.shape[1]):
            counts[leaf[r, c]] += 1
    return np.sqrt(counts).astype(np.uint8)


@njit(cache=True, inline='always')
def _axis_portal(ac, ah, bc, bh):
    alo, ahi, blo, bhi = int(ac - ah), int(ac + ah), int(bc - bh), int(bc + bh)
    if ahi < blo:
        return ahi, blo
    if bhi < alo:
        return alo, bhi
    middle = (max(alo, blo) + min(ahi, bhi)) // 2
    return middle, middle


@njit(cache=True, inline='always')
def _portal(a, b, crow, ccol, size):
    ha, hb = (int(size[a]) - 1) / 2, (int(size[b]) - 1) / 2
    xr, er = _axis_portal(crow[a], ha, crow[b], hb)
    xc, ec = _axis_portal(ccol[a], ha, ccol[b], hb)
    return xr, xc, er, ec


@njit(cache=True, inline='always')
def _octile(r, c):
    r, c = abs(r), abs(c)
    return 10 * (max(r, c) + (np.sqrt(2) - 1) * min(r, c))


@njit(cache=True)
def _neighbours(leaf, a, crow, ccol, size, lcost, buf):
    # The one-cell ring contains every 8-neighbour contact, including corners and hanging nodes.
    h = (int(size[a]) - 1) / 2
    r0, r1 = int(crow[a] - h), int(crow[a] + h)
    c0, c1 = int(ccol[a] - h), int(ccol[a] + h)
    n = 0
    for r in range(max(0, r0 - 1), min(leaf.shape[0], r1 + 2)):
        for c in range(max(0, c0 - 1), min(leaf.shape[1], c1 + 2)):
            if r0 <= r <= r1 and c0 <= c <= c1:
                continue
            b = leaf[r, c]
            if not np.isfinite(lcost[b]):
                continue
            seen = False
            for j in range(n):
                if buf[j] == b:
                    seen = True
                    break
            if not seen:
                buf[n] = b
                n += 1
    return n


@njit(cache=True, nogil=True)
def _build_graph(leaf, crow, ccol, size, lcost):
    n = len(crow)
    indptr = np.zeros(n + 1, dtype=np.int64)
    # Maximum ring size for the largest permitted square leaf.
    buf = np.empty(4 * int(size.max()) + 4, dtype=np.int32)
    for a in range(n):
        count = 0
        if np.isfinite(lcost[a]):
            count = _neighbours(leaf, a, crow, ccol, size, lcost, buf)
        indptr[a + 1] = indptr[a] + count
    dst = np.empty(indptr[-1], dtype=np.int32)
    w = np.empty(indptr[-1], dtype=np.float32)
    for a in range(n):
        if indptr[a] == indptr[a + 1]:
            continue
        count = _neighbours(leaf, a, crow, ccol, size, lcost, buf)
        for j in range(count):
            b = buf[j]
            xr, xc, er, ec = _portal(a, b, crow, ccol, size)
            weight = (_octile(xr - int(crow[a]), xc - int(ccol[a])) * lcost[a]
                      + _octile(er - xr, ec - xc) * (lcost[a] + lcost[b]) / 2
                      + _octile(int(crow[b]) - er, int(ccol[b]) - ec) * lcost[b])
            dst[indptr[a] + j] = b
            w[indptr[a] + j] = weight
    return indptr, dst, w


def build_graph(leaf, crow, ccol, lcost, size=None):
    """Build finite, symmetric CSR edges without full-grid edge arrays or a global sort."""
    if size is None:
        size = _leaf_sizes(leaf, len(crow))
    return _build_graph(leaf, crow, ccol, size, lcost)


@njit(cache=True, nogil=True)
def components(indptr, dst):
    """Component IDs for the finite-edge graph, using O(number of leaves) workspace."""
    n = len(indptr) - 1
    labels = np.full(n, -1, dtype=np.int32)
    stack = np.empty(n, dtype=np.int32)
    for root in range(n):
        if labels[root] >= 0:
            continue
        labels[root] = root
        stack[0] = root
        used = 1
        while used:
            used -= 1
            a = stack[used]
            for j in range(indptr[a], indptr[a + 1]):
                b = dst[j]
                if labels[b] < 0:
                    labels[b] = root
                    stack[used] = b
                    used += 1
    return labels


@njit(cache=True, nogil=True)
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
            if remaining == 0:
                break
        for k in range(indptr[u], indptr[u + 1]):
            v = dst[k]
            nd = d + w[k]
            if nd < dist[v]:
                dist[v] = nd; pred[v] = u
                heapq.heappush(heap, (nd, np.int64(v)))
    return dist, pred


@njit(cache=True)
def _walk(chain, crow, ccol, size, sr, sc, tr, tc):
    """Cells along integer anchor → exit → entry → anchor segments."""
    out = np.empty((max(8, len(chain) * 2), 2), dtype=np.int64)
    n = 0
    pr, pc = float(sr), float(sc)                       # start at the real source cell, not the leaf centre
    out[0, 0] = sr; out[0, 1] = sc; n = 1
    for k in range(len(chain) - 1):
        a, b = chain[k], chain[k + 1]
        xr, xc, er, ec = _portal(a, b, crow, ccol, size)
        last = (k == len(chain) - 2)
        for (qr, qc) in ((xr, xc), (er, ec), (int(tr), int(tc)) if last else (int(crow[b]), int(ccol[b]))):
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


def path_cells(pred, crow, ccol, size, target, start_cell=None, end_cell=None):
    """Predecessor chain → 10 m cell path that never leaves the leaves it visits.

    Between two touching leaves the path goes anchor → exit cell of the first leaf → entry cell of
    the second → anchor, so a segment cannot clip a third (possibly steep) leaf at a hanging node.
    Inside a coarse leaf every cell is gentle, so straight segments there are safe.
    To match Dijkstra's cost exactly, explicit endpoints must be pinned when building the mesh.
    """
    chain = []
    v = target
    while v >= 0:
        chain.append(v); v = pred[v]
    chain.reverse()
    sr, sc = start_cell if start_cell is not None else (int(crow[chain[0]]), int(ccol[chain[0]]))
    tr, tc = end_cell if end_cell is not None else (int(crow[chain[-1]]), int(ccol[chain[-1]]))
    if len(chain) == 1:
        steps = max(abs(tr - sr), abs(tc - sc))
        return np.rint(np.linspace((sr, sc), (tr, tc), steps + 1)).astype(np.int64)
    return _walk(np.array(chain, dtype=np.int64), crow, ccol, size, sr, sc, tr, tc)
