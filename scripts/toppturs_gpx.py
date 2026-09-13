"""Write GPX tracks (up + down) for every tour in .cache/toppturs.json.

Usage: toppturs_gpx.py OUT_DIR  → OUT_DIR/<nn>-<name>.gpx and OUT_DIR/all-toppturer.gpx
Elevations are sampled from the cached 10 m terrain. The "Up" track is the least-cost ascent line
(gentlest terrain, not a checked route); "Down" is the fall-line run, joined to the summit by a
straight connector when the run starts away from the top.
"""
import json, re, sys
from pathlib import Path
from xml.sax.saxutils import escape
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.terrain import TO_UTM, fetch_raster

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
data = json.loads(Path('.cache/toppturs.json').read_text())
tiles = {}

def elevation(lon, lat):
    x, y = TO_UTM.transform(lon, lat)
    key = (int(x // 4000) * 4000, int(y // 4000) * 4000)
    if key not in tiles:
        try:
            tiles[key] = fetch_raster(key[0] - 100, key[1] - 100, 4200, 10)
        except Exception:
            tiles[key] = None
    r = tiles[key]
    if r is None:
        return None
    z = float(r.sample(x, y))
    return None if np.isnan(z) else z

def pt(tag, lon, lat, name=None):
    z = elevation(lon, lat)
    inner = (f'<ele>{z:.0f}</ele>' if z is not None else '') + (f'<name>{escape(name)}</name>' if name else '')
    return f'<{tag} lat="{lat:.6f}" lon="{lon:.6f}">{inner}</{tag}>'

def track(name, points, desc):
    return f'<trk><name>{escape(name)}</name><desc>{escape(desc)}</desc><trkseg>' + ''.join(pt('trkpt', lon, lat) for lon, lat in points) + '</trkseg></trk>'

def tour_gpx(t, i):
    a, d = t['ascent'], t['descent']
    label = f"{t['name'] or 'Unnamed summit'} {round(t['elevation'])} m"
    up = a['line']
    parts = [pt('wpt', *a['start'], name=f'Car · {label}'), pt('wpt', *t['summit'], name=label)]
    parts.append(track(f'Up · {label}', up, f"least-cost ascent: +{a['gain_m']} m over {a['length_m']} m, max {a['max_slope']:.0f}°, {a['share_over_30']}% on 30–35°, ≈{a['hours']} h at 4 km/h + 400 m/h. Terrain possibility, not a checked route."))
    if d:
        down = [t['summit']] + d['line'] if d['start_offset_m'] > 60 else d['line']
        parts.append(pt('wpt', *d['end'], name=f'Run end · {label}'))
        parts.append(track(f'Down · {label}', down, f"fall-line run: {d['band_length_m']} m of 20–30°, {d['drop']:.0f} m drop, aspect {d['aspect']:.0f}°, max {d['max_slope']:.0f}°, {d['steep_share']}% ≥30°; ends {d['end_to_car_km']} km from the car."))
    return parts

def wrap(name, parts):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" creator="Rando toppturs" xmlns="http://www.topografix.com/GPX/1/1">'
            f'<metadata><name>{escape(name)}</name><desc>Generated {escape(data["generated"])} from Kartverket 10 m terrain. Ascent lines are least-cost terrain paths under 35°, not verified routes. Not a snow-stability assessment.</desc></metadata>'
            + ''.join(parts) + '</gpx>')

everything = []
for i, t in enumerate(data['tours'], 1):
    parts = tour_gpx(t, i)
    everything.extend(parts)
    slug = re.sub(r'[^\w]+', '-', (t['name'] or 'unnamed').lower()).strip('-')
    (out / f'{i:03d}-{slug}-{round(t["elevation"])}m.gpx').write_text(wrap(f'{i:03d} {t["name"] or "Unnamed"} {round(t["elevation"])} m', parts), encoding='utf-8')
(out / 'all-toppturer.gpx').write_text(wrap('Skarvatnet toppturer (all)', everything), encoding='utf-8')
print(len(data['tours']), 'tours written to', out)
