"""Graph files on disk: nodes and leg statistics in one JSON, geometry per block beside it.

`data/graph-<name>.json` stays a few MB; `data/graph-<name>.lines/<block>.json` holds leg and run
polylines keyed by "from>to>kind" (legs) or run id. `load()` reassembles the full graph in memory.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path


def block_of(node_id: str) -> str:
    return node_id.rsplit('_', 1)[0] if node_id.count('_') >= 2 else 'x'


def save(graph: dict, path: Path):
    path = Path(path)
    g = json.loads(json.dumps(graph))  # deep copy; pops below must not touch the caller's object
    lines = {}
    for e in g['edges']:
        blk = block_of(e['to'] if e['kind'] == 'skin' else e['from'])
        lines.setdefault(blk, {})[f"{e['from']}>{e['to']}>{e['kind']}"] = e.pop('line', None)
    for r in g['runs']:
        lines.setdefault(block_of(r['id']), {})[r['id']] = r.pop('line', None)
        for sid, a in (r.get('approach') or {}).items():
            lines[block_of(r['id'])][f"{r['id']}>{sid}>approach"] = a.pop('line', None)
    ldir = path.with_suffix('.lines')
    shutil.rmtree(ldir, ignore_errors=True); ldir.mkdir(parents=True)
    for blk, d in lines.items():
        (ldir / f'{blk}.json').write_text(json.dumps(d))
    g['lines_dir'] = ldir.name
    path.write_text(json.dumps(g, ensure_ascii=False))


def load(path: Path) -> dict:
    path = Path(path)
    g = json.loads(path.read_text())
    ldir = path.parent / g.get('lines_dir', path.with_suffix('.lines').name)
    if g.get('lines_dir') and ldir.exists():
        cache = {}
        get = lambda blk: cache.setdefault(blk, json.loads((ldir / f'{blk}.json').read_text()) if (ldir / f'{blk}.json').exists() else {})
        for e in g['edges']:
            e['line'] = get(block_of(e['to'] if e['kind'] == 'skin' else e['from'])).get(f"{e['from']}>{e['to']}>{e['kind']}", [])
        for r in g['runs']:
            r['line'] = get(block_of(r['id'])).get(r['id'], [])
            for sid, a in (r.get('approach') or {}).items():
                a['line'] = get(block_of(r['id'])).get(f"{r['id']}>{sid}>approach", [])
    return g
