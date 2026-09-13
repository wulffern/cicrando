"""Run a per-block worker over a list of blocks in parallel, caching one JSON per block."""
from __future__ import annotations

import json
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path


def _run(args):
    worker, block, kwargs = args
    t0 = time.time()
    try:
        return block, worker(block, **kwargs), time.time() - t0, None
    except Exception as exc:  # reported, not raised: one bad block must not kill the scan
        return block, None, time.time() - t0, f'{type(exc).__name__}: {exc}'


def run_blocks(blocks, worker, out_dir: Path, workers=4, describe=lambda r: '', **kwargs):
    """Call worker(block, **kwargs) for every block without a cached result; returns list of result paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    todo = [b for b in blocks if not (out_dir / f"{b['x']}_{b['y']}.json").exists()]
    print(f'{len(blocks)} blocks, {len(todo)} to compute with {workers} workers', flush=True)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_run, (worker, b, kwargs)) for b in todo]
        for i, f in enumerate(as_completed(futures), 1):
            block, result, seconds, error = f.result()
            name = f"{block['x']}_{block['y']}"
            if error:
                print(f'{i}/{len(todo)} block {name} failed: {error}', flush=True)
                continue
            result['block'] = block
            (out_dir / f'{name}.json').write_text(json.dumps(result))
            print(f'{i}/{len(todo)} block {name}: {describe(result)}, {seconds:.0f}s', flush=True)
    return sorted(out_dir.glob('*.json'))
