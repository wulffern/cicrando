"""Batch candidate scan over pre-selected 28 km blocks (see .cache/scan_blocks.json).

Usage: .venv/bin/python scripts/scan_region.py [min_length] [day]
Writes one JSON per block to .cache/scan/ and skips blocks already done, so it can be resumed.
"""
import json, sys, time, logging
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.search import search
from backend.blocks import run_blocks
from backend.terrain import TO_LL

logging.basicConfig(level=logging.WARNING, format='%(asctime)s %(message)s')
B = 28000
min_length = float(sys.argv[1]) if len(sys.argv) > 1 else 500
day = sys.argv[2] if len(sys.argv) > 2 else '2026-03-15'
out = Path('.cache/scan'); out.mkdir(parents=True, exist_ok=True)
blocks = json.load(open('.cache/scan_blocks.json'))
keep = []
for b in blocks:
    lon, lat = TO_LL.transform(b['x'] + B / 2, b['y'] + B / 2)
    if 8.5 <= lon <= 12.6 and lat >= 62.2:
        keep.append(b)

def worker(b):
    return search(b['x'], b['y'], b['x'] + B, b['y'] + B, 20, 30, min_length, day, 9, 15, 4, 400, limit=300)

if __name__ == '__main__':
    run_blocks(sorted(keep, key=lambda b: b['dist_km']), worker, out, workers=4,
               describe=lambda r: f"{r['count']} candidates, roads={r['roads']}, forest={r['forest']}, missing={r['tiles_missing']}")
