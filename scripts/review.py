"""Merge block scans into a ranked review list with place names.

Usage: .venv/bin/python scripts/review.py [top_n] [max_approach_hours]
Reads .cache/scan/*.json, writes .cache/review.json and .cache/review.geojson.
Score = in-band run length / (1 + approach hours): long continuous skiing, short approach.
"""
import json, sys, time
from pathlib import Path
import httpx
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.terrain import TO_UTM

top_n = int(sys.argv[1]) if len(sys.argv) > 1 else 100
max_hours = float(sys.argv[2]) if len(sys.argv) > 2 else 2.5
names_cache = Path('.cache/placenames.json')
names = json.loads(names_cache.read_text()) if names_cache.exists() else {}

def place(lon, lat):
    key = f'{lon:.3f},{lat:.3f}'
    if key not in names:
        x, y = TO_UTM.transform(lon, lat)
        try:
            r = httpx.get('https://api.kartverket.no/stedsnavn/v1/punkt', params=dict(nord=round(y), ost=round(x), koordsys=25833, radius=3000, utkoordsys=4258, treffPerSide=30), timeout=20)
            r.raise_for_status()
            hits = r.json().get('navn', [])
        except (httpx.HTTPError, ValueError):
            hits = []
        peaks = [h for h in hits if h['navneobjekttype'] in ('Fjell', 'Topp', 'Berg', 'Ås', 'Fjellområde', 'Hei', 'Rygg', 'Nut', 'Egg', 'Kam', 'Koll', 'Haug', 'Høyde', 'Fjellkant', 'Botn')]
        lis = [h for h in hits if h['navneobjekttype'] in ('Li', 'Dal', 'Skar', 'Botn', 'Bre', 'Vann', 'Innsjø', 'Elv', 'Bekk', 'Seter', 'Grend', 'Bygd', 'Tettsted')]
        fmt = lambda h: f"{h['stedsnavn'][0]['skrivemåte']} ({h['navneobjekttype'].lower()}, {round(h['meterFraPunkt']/100)/10} km)"
        names[key] = dict(peak=fmt(peaks[0]) if peaks else None, near=fmt(lis[0]) if lis else (fmt(hits[0]) if hits else None))
        names_cache.write_text(json.dumps(names, ensure_ascii=False))
        time.sleep(0.2)
    return names[key]

cands, blocks = [], 0
for path in sorted(Path('.cache/scan').glob('*.json')):
    r = json.loads(path.read_text()); blocks += 1
    for c in r['candidates']:
        c['block'] = r['block']; c['block_dist_km'] = r['block']['dist_km']
        cands.append(c)
print(f'{blocks} blocks, {len(cands)} raw candidates')
# Score, then greedy dedupe: drop any candidate whose top lies within 400 m of a better one.
for c in cands:
    h = c['approach']['hours'] if c['approach'] and c['approach']['hours'] is not None else None
    c['score'] = round(c['band_length_m'] / (1 + h), 0) if h is not None else None
eligible = [c for c in cands if c['score'] is not None and c['approach']['hours'] <= max_hours]
eligible.sort(key=lambda c: -c['score'])
kept, tops = [], []
for c in eligible:
    x, y = TO_UTM.transform(*c['top'])
    if tops and np.min(np.hypot(np.array(tops)[:, 0] - x, np.array(tops)[:, 1] - y)) < 400:
        continue
    kept.append(c); tops.append((x, y))
print(f'{len(eligible)} eligible (approach ≤ {max_hours} h), {len(kept)} after dedupe; taking {top_n}')
top = kept[:top_n]
for i, c in enumerate(top, 1):
    c['rank'] = i
    c.update(place(*c['center']))
Path('.cache/review.json').write_text(json.dumps(dict(generated=time.strftime('%Y-%m-%d %H:%M'), blocks=blocks, raw=len(cands), eligible=len(eligible), deduped=len(kept), max_hours=max_hours, candidates=top), ensure_ascii=False))
features = [dict(type='Feature', properties=dict(rank=c['rank'], peak=c['peak'], near=c['near'], band_length_m=c['band_length_m'], drop=c['drop'], aspect=c['aspect'], terrain=c['terrain'], approach_h=c['approach']['hours'], score=c['score']), geometry=dict(type='LineString', coordinates=c['line'])) for c in top]
Path('.cache/review.geojson').write_text(json.dumps(dict(type='FeatureCollection', features=features)))
for c in top[:15]:
    print(c['rank'], c['score'], c['band_length_m'], 'm', round(c['drop'] or 0), 'm drop', round(c['aspect'] or 0), '°', c['terrain'], 'appr', c['approach']['hours'], 'h', c['peak'], '|', c['near'])
