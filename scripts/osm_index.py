"""Download a Geofabrik extract and build the local parking/road index. Usage: osm_index.py norway|sweden [pbf]"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.osm_extract import GEOFABRIK, OSM_DIR, build_index

if __name__ == '__main__':
    name = sys.argv[1]
    pbf = Path(sys.argv[2]) if len(sys.argv) > 2 else OSM_DIR / f'{name}-latest.osm.pbf'
    if not pbf.exists():
        import httpx
        OSM_DIR.mkdir(parents=True, exist_ok=True)
        print('downloading', GEOFABRIK[name], flush=True)
        with httpx.stream('GET', GEOFABRIK[name], follow_redirects=True, timeout=None) as r, open(pbf, 'wb') as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
    print('indexing', pbf, flush=True)
    n_park, n_pts = build_index(pbf, name)
    print(f'{name}: {n_park} parkings, {n_pts} road points -> {OSM_DIR}', flush=True)
