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
    def tidy(line):
        # 5 decimals is ~1 m; elevation to 0.1 m (float32 values otherwise serialise with 13 junk digits).
        return None if line is None else [[round(p[0], 5), round(p[1], 5), *(round(v, 1) for v in p[2:])] for p in line]

    def thin(line, step=2):
        # Legs are sampled every 80 m at build; every second point (~160 m) is plenty for display and GPX.
        if not line or len(line) <= 3:
            return tidy(line)
        out = line[::step]
        if out[-1] != line[-1]:
            out.append(line[-1])
        return tidy(out)
    lines = {}
    for e in g['edges']:
        blk = block_of(e['to'] if e['kind'] == 'skin' else e['from'])
        lines.setdefault(blk, {})[f"{e['from']}>{e['to']}>{e['kind']}"] = thin(e.pop('line', None))
    for r in g['runs']:
        lines.setdefault(block_of(r['id']), {})[r['id']] = tidy(r.pop('line', None))
        for sid, a in (r.get('approach') or {}).items():
            lines[block_of(r['id'])][f"{r['id']}>{sid}>approach"] = tidy(a.pop('line', None))
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

        def get(blk):
            if blk not in cache:   # setdefault would re-read the file on every call
                cache[blk] = json.loads((ldir / f'{blk}.json').read_text()) if (ldir / f'{blk}.json').exists() else {}
            return cache[blk]
        for e in g['edges']:
            e['line'] = get(block_of(e['to'] if e['kind'] == 'skin' else e['from'])).get(f"{e['from']}>{e['to']}>{e['kind']}", [])
        for r in g['runs']:
            r['line'] = get(block_of(r['id'])).get(r['id'], [])
            for sid, a in (r.get('approach') or {}).items():
                a['line'] = get(block_of(r['id'])).get(f"{r['id']}>{sid}>approach", [])
    return g
