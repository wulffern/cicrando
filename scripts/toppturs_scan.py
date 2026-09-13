"""Summit-tour scan around an origin. Usage: toppturs_scan.py LON LAT MAX_DRIVE_MIN [radius_km]

Runs backend.toppturs over the 28 km scan blocks within the radius, routes each ascent start with
OSRM from the origin, names summits via Kartverket, and writes .cache/toppturs.json.
"""
import json, sys, time, logging
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.toppturs import toppturs, drive_minutes
from backend.blocks import run_blocks
from backend.terrain import TO_UTM, TO_LL
import httpx

logging.basicConfig(level=logging.WARNING, format='%(asctime)s %(message)s')
lon, lat, max_drive = float(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3])
radius = float(sys.argv[4]) if len(sys.argv) > 4 else 60
B = 28000
ox, oy = TO_UTM.transform(lon, lat)
blocks = [b for b in json.load(open('.cache/scan_blocks.json')) if np.hypot(b['x'] + B / 2 - ox, b['y'] + B / 2 - oy) / 1000 <= radius]
out = Path('.cache/toppturs')

def worker(b):
    return toppturs(b['x'], b['y'], b['x'] + B, b['y'] + B)

if __name__ == '__main__':
    run_blocks(sorted(blocks, key=lambda b: b['dist_km']), worker, out, workers=3,
               describe=lambda r: f"{len(r['tours'])} summits, {sum(1 for t in r['tours'] if t['descent'])} with descent")

if __name__ == '__main__':
    tours = [t for p in out.glob('*.json') for t in json.loads(p.read_text())['tours']]
    routable = [t for t in tours if t['ascent']]
    print(f'{len(tours)} summits, {len(routable)} with an ascent line', flush=True)
    minutes = drive_minutes((lon, lat), [tuple(t['ascent']['start']) for t in routable])
    for t, m in zip(routable, minutes):
        t['drive_min'] = m
    kept = [t for t in routable if t['drive_min'] is not None and t['drive_min'] <= max_drive]
    print(f'{len(kept)} within {max_drive:.0f} min drive', flush=True)
    names = Path('.cache/placenames.json'); cache = json.loads(names.read_text()) if names.exists() else {}
    for t in kept:
        key = 'peak:' + ','.join(f'{v:.4f}' for v in t['summit'])
        if key not in cache:
            x, y = TO_UTM.transform(*t['summit'])
            try:
                r = httpx.get('https://api.kartverket.no/stedsnavn/v1/punkt', params=dict(nord=round(y), ost=round(x), koordsys=25833, radius=600, utkoordsys=4258, treffPerSide=20), timeout=20)
                hits = r.json().get('navn', []) if r.status_code == 200 else []
            except (httpx.HTTPError, ValueError):
                hits = []
            peaks = [h for h in hits if h['navneobjekttype'] in ('Fjell', 'Topp', 'Berg', 'Nut', 'Egg', 'Kam', 'Koll', 'Haug', 'Høyde', 'Ås', 'Rygg', 'Fjellkant', 'Hei')]
            cache[key] = dict(name=peaks[0]['stedsnavn'][0]['skrivemåte'] if peaks else None, kind=peaks[0]['navneobjekttype'] if peaks else None,
                              dist=round(peaks[0]['meterFraPunkt']) if peaks else None)
            names.write_text(json.dumps(cache, ensure_ascii=False)); time.sleep(0.2)
        t.update(cache[key])
    kept.sort(key=lambda t: -(t['descent']['band_length_m'] if t['descent'] else 0))
    Path('.cache/toppturs.json').write_text(json.dumps(dict(origin=[lon, lat], max_drive=max_drive, generated=time.strftime('%Y-%m-%d %H:%M'), blocks=len(blocks), summits=len(tours), tours=kept), ensure_ascii=False))
    print('done', flush=True)
