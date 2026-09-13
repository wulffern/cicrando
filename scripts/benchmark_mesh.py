"""Reproducible synthetic mesh benchmark (run each implementation in a fresh process).

    .venv/bin/python scripts/benchmark_mesh.py --size 1600
    git show 9a4e7a1:backend/mesh.py > /tmp/mesh_baseline.py
    .venv/bin/python scripts/benchmark_mesh.py --size 1600 --baseline /tmp/mesh_baseline.py

Reports warm-JIT timings and process peak RSS, including construction temporaries. This is a
controlled regression benchmark, not a substitute for offline real-terrain block measurements.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import resource
import sys
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import mesh
from backend.toppturs import ascent_costs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--size', type=int, default=1600)
    parser.add_argument('--baseline', type=Path)
    args = parser.parse_args()
    implementation = mesh
    if args.baseline:
        spec = importlib.util.spec_from_file_location('mesh_baseline', args.baseline)
        implementation = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = implementation
        spec.loader.exec_module(implementation)

    r, c = np.indices((args.size, args.size), dtype=np.float32)
    slope = (18 + 12 * np.sin(r / 83) * np.cos(c / 117)).astype(np.float32)
    slope[(r.astype(int) % 311 < 8) & (c.astype(int) % 197 < 80)] = 40
    del r, c
    costs = ascent_costs(slope, 35)
    rng = np.random.default_rng(23)
    valid = np.argwhere(np.isfinite(costs))
    endpoints = valid[rng.choice(len(valid), 40, replace=False)]
    del valid

    warm = np.full((32, 32), 8., dtype=np.float32)
    leaf, cr, cc, sizes, lc = implementation.build_mesh(warm / 8, warm, 15)
    indptr, dst, weights = implementation.build_graph(leaf, cr, cc, lc)
    implementation.dijkstra(indptr, dst, weights, 0, np.array([0], dtype=np.int32))
    if not args.baseline:
        implementation.components(indptr, dst)

    start = time.perf_counter()
    kwargs = {} if args.baseline else {'endpoints': endpoints}
    leaf, cr, cc, sizes, lc = implementation.build_mesh(costs, slope, 15, **kwargs)
    meshed = time.perf_counter()
    indptr, dst, weights = implementation.build_graph(leaf, cr, cc, lc)
    graphed = time.perf_counter()
    if not args.baseline:
        labels = implementation.components(indptr, dst)
    connected = time.perf_counter()
    reachable = 0
    for cell in endpoints[:8]:
        source = int(leaf[tuple(cell)])
        targets = np.array([leaf[tuple(c)] for c in endpoints[8:]], dtype=np.int32)
        if not args.baseline:
            targets = targets[labels[targets] == labels[source]]
        dist, _ = implementation.dijkstra(indptr, dst, weights, source, targets)
        reachable += int(np.isfinite(dist[targets]).sum())
    searched = time.perf_counter()
    rss_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == 'darwin' else 1024)
    print(json.dumps(dict(implementation=str(args.baseline or 'current'), cells=args.size ** 2,
                          leaves=len(cr), directed_edges=len(dst), mesh_s=meshed - start,
                          graph_s=graphed - meshed, components_s=connected - graphed,
                          eight_sources_s=searched - connected, reachable=reachable,
                          peak_rss_MB=rss_bytes / 1e6), indent=2))


if __name__ == '__main__':
    main()
