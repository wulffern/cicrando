# Rando — ski terrain and sunlight planner

Browser app (desktop + iPhone) for finding and inspecting ski faces around Trondheim: slope/aspect
matching on Kartverket 10 m terrain, date- and time-specific mountain shadows, ascent-route timing,
NVE steepness/runout tiles, and the full NVE avalanche forecast plus MET weather.

Terrain matches describe shape and light only — never snow stability.

## Run

Python 3.12 (Rasterio has no wheel for 3.14) and Node ≥ 20. A project-local Node lives in
`.tools/node` if the system Node is old.

```sh
export PATH="$PWD/.tools/node/bin:$PATH"       # only if system node < 20
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
npm install

.venv/bin/uvicorn backend.app:app --port 8000   # API, terminal 1
npm run dev                                     # Vite on http://localhost:5173, terminal 2
```

`npm run dev` binds `0.0.0.0`, so an iPhone on the same Wi-Fi can open `http://<mac-ip>:5173`.
For a single-process build: `npm run build` then run uvicorn alone — it serves `dist/` on :8000.

First load of an area fetches ~4 MB of elevation from hoydedata.no and computes horizons (~8 s);
results are cached in `.cache/terrain`.

## Test

```sh
.venv/bin/python -m pytest -q          # backend: slope bounds, aspect wraparound, missing terrain, DST, routes, forecasts
npm test                               # frontend: GPX round trip, plan/preference validation
npx playwright test                    # end-to-end (desktop + iPhone viewport); needs both servers running and internet
```

## Static site (GitHub Pages)

`docs/` is a static site published by `.github/workflows/pages.yml`: a tour viewer (`index.html`,
MapLibre + Kartverket + NVE tiles reading `docs/data/*.json`), per-tour GPX under `docs/gpx/`, and
the review pages. Rebuild after a new scan with `.venv/bin/python scripts/build_site.py` and commit.

Topptur planner (`docs/route.html`): searchable summit list; each summit shows its best loop —
parking → skin up → ski → back to the same car — with alternative parkings/runs, from a precomputed graph (`scripts/graph_scan.py LON LAT NAME` → `data/graph-<name>-<date>.json`): least-cost
skin/walk legs on 10 m terrain, fall-line runs, OSM parkings with winter-access class (OSM/NVDB tags,
road class, `data/winter_roads.json` overrides), OSRM drive times. GPX export, shareable links.

Vendor data is cached under `.cache/` by default — elevation tiles, AR5 forest PNGs, Overpass
responses (roads, parkings, access tags), NVDB winter classes, OSRM drive times and place names — so a
rerun never re-downloads what it has. `RANDO_OFFLINE=1` forbids network calls entirely and works
from the cache alone (uncached tiles then fail loudly; uncached roads/forest/drive times stay unknown).

Least-cost legs use a terrain-adaptive mesh (`backend/mesh.py`): 10 m cells wherever slope ≥15° or
impassable, merged 20–160 m cells over gentle uniform ground (≈30 % of the cells remain), hanging
nodes joined to every touching leaf, octile edge lengths, and a compiled Dijkstra (numba) that stops
when all targets are settled. Paths are walked back onto 10 m cells so every statistic (max slope,
share ≥30°) is read from the full-resolution grid. Against a full 10 m search: costs within ~1 %,
same number of legs, ~3× faster per block.

Performance: fall-line propagation uses pointer jumping (≈30× faster than one pass per cell) and the
scan scripts run 4 blocks in parallel (`backend/blocks.py`); a full 13-block graph rebuild takes ~5 min
with tiles cached. Cached blocks are skipped, so reruns are incremental.

Scan pipeline: `scripts/scan_region.py` (faces) → `review.py` → `review_page.py`;
`scripts/toppturs_scan.py LON LAT MAX_MIN` (summit tours) → `toppturs_page.py`, `toppturs_gpx.py`.

## Data sources

| Purpose | Service |
|---|---|
| Elevation (numerical, EPSG:25833) | `https://hoydedata.no/arcgis/rest/services/NHM_DTM_25833/ImageServer` |
| Background map | Kartverket `cache.kartverket.no` topo WMTS |
| Steepness + runout | NVE `Bratthet_med_utlop_2024` tiles (yellow→dark red steepness classes from 27°, blue runout) |
| Avalanche forecast | `api01.nve.no/hydrology/forecast/avalanche/v6.3.2` — `AvalancheWarningByCoordinates/Detail` |
| Roads | OpenStreetMap via Overpass (ODbL) — driveable `highway` classes |
| Forest and tree species | NIBIO AR5 `Treslag` WMS (`wms.nibio.no/cgi-bin/ar5`), decoded from legend colours |
| Weather | MET `locationforecast/2.0/compact` (cached ≥15 min, `If-Modified-Since`) |

## Candidate search

"Find candidates" scans the current map view (≤30 × 30 km) for fall-line runs with at least N m
(default 500) of continuous skiing inside the slope band, ranks them by straight-line approach from
the nearest OpenStreetMap road, and labels each run open / mixed / trees, with the dominant tree type (birch vs spruce) from NIBIO AR5.
First scan of a region downloads its 10 m tiles (~1 s each) and queries Overpass; results are cached.

## Method and known approximations

- 4 × 4 km areas at 10 m; slope/aspect from `np.gradient` in UTM 33, aspect corrected for meridian convergence.
- Horizons: 40 m grid, 5° bearings, rays to 40 km using 100 m terrain outside the tile. The area
  panel reports how much the 20→40 km extension changed horizons (2.5° at Storhornet).
- Sun sampled every 10 min, Europe/Oslo, refraction ignored. Cloud cover is shown separately from geometry.
- Moving time = distance ÷ 4 km/h + ascent ÷ 400 m/h (both editable). Route sampled every ≤10 m;
  sections ≥30° are flagged regardless of preferences. Missing terrain withholds the estimate.
- Forecasts are shown with validity dates; past, out-of-range and unavailable states are explicit.
- No synthetic terrain: missing coverage stays "unknown".
