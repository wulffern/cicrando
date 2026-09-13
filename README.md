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

## How the code works

The interactive app computes terrain overlays and analyzes routes on demand. The static tour
planner reads a graph generated ahead of time; it does not run terrain searches in the browser.

| Code | Responsibility |
|---|---|
| [src/App.tsx](src/App.tsx), [src/Map.tsx](src/Map.tsx) | React controls, route editing, and MapLibre terrain/route layers. |
| [backend/app.py](backend/app.py) | FastAPI endpoints for areas, overlays, inspection, candidate-search jobs, route analysis, and conditions. |
| [backend/terrain.py](backend/terrain.py) | Elevation tiles, coordinate transforms, slope/aspect, horizons, sunlight, and route sampling. |
| [backend/search.py](backend/search.py) | Stitch tiles into a mosaic, propagate fall-line runs, and load roads and forest data. |
| [backend/loops.py](backend/loops.py) | Parking access classification and candidate descents from summits. |
| [backend/toppturs.py](backend/toppturs.py) | Summit detection, ascent costs, path statistics, drive times, and the separate single-tour scanner. |
| [backend/mesh.py](backend/mesh.py) | Adaptive terrain leaves, their adjacency graph, connected components, Dijkstra, and path reconstruction. |
| [backend/graph.py](backend/graph.py) | Combine parkings, summits, runs, and skin/walk legs into a tour graph. |
| [backend/regions.py](backend/regions.py), [backend/graph_scan.py](backend/graph_scan.py) | Circle/square coverage, early parking/drive filtering, reusable block selection, and origin-specific graph assembly. |
| [backend/blocks.py](backend/blocks.py), [scripts/graph_scan.py](scripts/graph_scan.py) | Worker processes and the graph-scan command line. |
| [site/route.html](site/route.html), [scripts/build_site.py](scripts/build_site.py) | Static loop planner and assembly of the published `docs/` site. |

In the interactive app, preparing an area loads elevation and computes terrain and horizon data.
The overlay and inspection endpoints combine that data with the requested date, time, slope, and
aspect. Candidate searches run as jobs that the browser polls. Route analysis samples the user's
line against terrain and estimates movement time; it is separate from the least-cost graph builder.

### Building a tour graph

`graph_scan.py` generates 28 × 28 km blocks intersecting the requested circle or square on the
existing UTM lattice; no `.cache/scan_blocks.json` is required for graph scans. It discovers
parkings within that shape, filters winter access and one-way driving times, and selects terrain
blocks near eligible parkings before loading elevation. Each terrain block gets a 12 km
routing margin on every side, giving a 52 × 52 km mosaic: 5,200 × 5,200 cells at 10 m resolution.
The margin allows approaches to leave the block's central area without immediately hitting a
search boundary. Terrain coordinates use metres in UTM zone 33N (EPSG:25833).

For each block, `graph.build()`:

1. Loads elevation, derives slope/aspect, and loads forest and parking information.
2. Detects summits inside the central block. Fall-line propagation and `run_candidates()` identify
   descents and merge nearby duplicate runs.
3. Collects every parking, summit, and run-bottom endpoint before constructing the routing mesh.
4. Routes parking → summit and run-bottom → summit skin legs, plus run-bottom → parking walk legs.
   Default straight-line candidate limits are 12 km for summit legs and 8 km for return walks.
   Return walks are retained only when their computed ascent is at most 400 m.
5. Computes path statistics and exports geometry. Summits reference their descents, so the static
   planner can assemble parking → summit → run → parking loops.

Those distance limits select endpoint pairs; they are not maximum walked distances. The terrain
edge cost is symmetric, but gain/loss and the meaning of a published leg depend on direction.
Large scratch rasters used for run discovery are released before the routing graph is allocated.

### Terrain costs and adaptive leaves

[ascent_costs()](backend/toppturs.py) assigns a cost per horizontal metre from the full 10 m slope
raster. With the default `lower=20` and `max_ascent=35`:

| Slope | Cost multiplier |
|---|---:|
| Below 20° | 1.0 |
| 20° to below 25° | 1.3 |
| 25° to below 30° | 1.8 |
| 30° to below 35° | 4.0 |
| 35° or more, or unknown | Impassable |

The routing objective minimizes this weighted horizontal distance. Elevation gain, forest cover,
and estimated hours are calculated afterward; they are not extra terms in Dijkstra's objective.

`mesh.build_mesh()` partitions the raster into aligned square leaves. It tries 16 × 16 cells first,
then 8 × 8, 4 × 4, and 2 × 2; unclaimed cells remain individual 10 m leaves. A square can merge only
when all its cells are below the 15° refinement threshold, have the same finite routing cost,
contain no pinned endpoint, and have not already been claimed by a larger leaf.

This leaves steep terrain, unknown/blocked cells, and endpoints at 10 m, while gentle ground can
use 20, 40, 80, or 160 m leaves. Cost-class boundaries are preserved even if the slope-cost
configuration changes. Every raster cell stores its leaf ID. Each leaf also stores its size,
uniform cost, and geometric centre; the integer cell at the floor of that centre is its routing
anchor. Pinning endpoints prevents a short leg from making an artificial trip to a coarse centre.

`Router` accepts all endpoints at construction. Ad-hoc calls with new endpoints inside coarse
leaves trigger a rebuild that refines those locations, so batch callers should provide endpoints
up front.

### Connecting leaves and assigning edge weights

A coarse leaf connects to **every traversable leaf it touches**, including smaller leaves along
its sides and leaves touching only at a corner. This handles hanging nodes without requiring
neighbouring leaves to have the same size. Blocked leaves have no graph edges. Corner contact
uses the same 8-neighbour convention as the fine-grid reference: blocked orthogonal neighbours
do not prohibit a diagonal step between two traversable cells.

`build_graph()` scans a one-cell ring around each leaf, deduplicates its neighbour IDs, and builds
compressed sparse row (CSR) arrays in two passes: count neighbours and compute offsets, then fill
`dst` and `w`. Each undirected connection has one entry in each direction. This avoids creating
and sorting full-raster edge-pair arrays. Destinations and weights use int32 and float32;
CSR offsets use int64.

For each pair of touching leaves, `_portal()` chooses adjacent exit/entry cells on their shared
boundary. Where their row or column ranges overlap, it uses the floor of the overlap midpoint.
The corresponding walk is:

```text
anchor A → exit cell in A → entry cell in B → anchor B
```

For row/column displacements measured in cells, octile distance in metres is:

```text
D(dr, dc) = 10 × (max(|dr|, |dc|) + (sqrt(2) − 1) × min(|dr|, |dc|))
```

The edge charges the anchor-to-exit distance at A's cost, the crossing at the mean of A and B's
costs, and the entry-to-anchor distance at B's cost. This matches the reconstructed grid walk's
cost, up to float32 edge rounding. For two fine cells it reduces to the MCP_Geometric neighbour
cost. It does not charge half of a long coarse-to-fine connection at the fine cell's cost.

### Searching, reconstructing, and exporting paths

`mesh.components()` labels the connected components once. `Router.legs()` removes targets outside
the source's component before running Dijkstra; an unreachable target therefore cannot force a
search of the entire reachable area. Each run bottom searches for summit and parking destinations
together. Duplicate target leaves count only once toward the stopping condition.

The Numba Dijkstra uses a heap of `(distance, leaf ID)` entries, float64 accumulated distances,
and int32 predecessors. Settled flags discard stale heap entries. Search stops immediately when
all requested targets have been settled. The compiled search releases the GIL; graph scans
currently parallelize blocks with **two worker processes**, not threads within a block.

`path_cells()` follows predecessors and reconstructs the same anchor/exit/entry segments used by
the edge weights. Each segment inside a square stays inside that leaf, and the boundary crossing
joins neighbouring cells. The result is an 8-connected 10 m path with exact source and target
cells. A same-leaf path is drawn directly; identical endpoints produce a single cell.

`path_stats()` reads elevation, slope, and forest data along this full path. It reports 3D length,
ascent/descent, maximum and mean slope, steep-cell shares, forest share, and movement time. Slope
and forest shares are fractions of visited cells. Time defaults to length ÷ 4 km/h plus gain ÷
400 m/h.

`graph.line()` retains every change of grid direction and at least every eighth cell for routing
legs. It removes only collinear intermediate cells, so simplification does not cut across bends.
Coordinates are exported with seven decimal places. Statistics are calculated before this
geometry reduction.

### Accuracy and performance limits

The mesh retains 10 m terrain samples and impassability checks in steep ground. It does **not**
guarantee the same globally optimal route as a full-grid search: forcing gentle-ground paths
through leaf anchors can change route choice, gain, slope statistics, and which return walks pass
the gain limit. The 15° threshold is a conservative setting, not a bound on path-cost error. The
merge rule does not currently bound elevation range or curvature, so a gentle ridge or shoulder
can lie inside a large leaf. Routing also remains bounded by the padded block.

The September 2026 validation of the revised implementation measured:

| Check | Result |
|---|---|
| Synthetic 1,600 × 1,600 grid, 8 sources × 32 targets | 8.03 s before → 5.01 s after, including mesh/graph construction and searches |
| Peak process memory for that synthetic benchmark | 1.70 GB before → 0.41 GB after |
| Cached real block `192000_6956000`, including its routing margin | 115 s, 2.90 GB peak process memory, 1,985 legs, no missing tiles |
| Reconstructed exported geometry for those 1,985 legs | No impassable cells or maximum-slope mismatches |
| 12 real legs compared with fine-grid searches in path bounding boxes plus a 1 km margin | Median cost excess 0.61%; maximum 2.82% |

These are local measurements, not performance or accuracy guarantees for other terrain. The
cropped comparisons do not establish a global error bound. The real-block memory measurement
fits the approximate 3 GB per-worker target, but other blocks can have different refinement and
search-frontier sizes. Synthetic timings exclude initial JIT compilation; memory includes process
peak RSS and construction temporaries.

Reproduce the synthetic comparison in separate processes:

```sh
.venv/bin/python scripts/benchmark_mesh.py --size 1600
git show 9a4e7a1:backend/mesh.py > /tmp/mesh_baseline.py
.venv/bin/python scripts/benchmark_mesh.py --size 1600 --baseline /tmp/mesh_baseline.py
```

[tests/test_mesh.py](tests/test_mesh.py) covers refinement and cost classes, exact endpoints,
hanging-node adjacency, symmetry and unique edges, graph-versus-walked costs, disconnected and
duplicate targets, agreement with MCP on fully refined terrain, and exported obstacle detours.

## Scanning, caches, and rebuilding

Start with an origin, a geographic parking search area, and an optional one-way driving limit:

```sh
# Two hours' drive; parking search in a 200 km square centred on Skarvatnet.
.venv/bin/python scripts/graph_scan.py \
  --origin 9.54917 62.69398 --name Skarvatnet \
  --max-drive-hours 2 --shape square --side-km 200

# Circle instead; select terrain within 20 km of qualifying parkings.
.venv/bin/python scripts/graph_scan.py \
  --origin 9.54917 62.69398 --name Skarvatnet \
  --max-drive-hours 2 --radius-km 60 --terrain-buffer-km 20

# Preview parkings, unknown driving times, and requested blocks without terrain computation.
RANDO_OFFLINE=1 .venv/bin/python scripts/graph_scan.py \
  --origin 9.54917 62.69398 --name Skarvatnet --radius-km 60 \
  --max-drive-hours 2 --plan-only

# The positional form still works (circle radius in kilometres).
.venv/bin/python scripts/graph_scan.py 9.54917 62.69398 Skarvatnet 60
.venv/bin/python scripts/build_site.py
```

Circle extent is a **radius**; square extent is its **full side length**, aligned to UTM axes.
The circle/square bounds parking discovery, not the complete ski route. Blocks touching the
boundary are included, and eligible parkings can lead to summits outside the geographic shape.
A driving-time limit applies to parking destinations within this declared coverage; it does not
claim to find every destination reachable in that time outside the shape. Automatic isochrones
remain a future extension.

`--access open` is the default: plowed and unknown winter access are included, closed access is
excluded. Use `--access plowed` for classified plowed access only, or `--access all` to include
closed access explicitly. Driving times are road-routing estimates and do not certify winter
access. Unknown/unavailable driving times are excluded when a time limit is present and reported
in metadata; without a time limit they remain eligible with `drive_min: null`.

`--terrain-buffer-km` defaults to 12 and must be at least the 12 km summit-approach limit. A 20 km
buffer selects more blocks around eligible parkings; it does not increase the individual ski-leg
limit or the 52 km padded size of each terrain block. This avoids building every map in a large
square. Selection is at 28 km block granularity, so some terrain outside the buffer is still loaded.
We use reachable parkings rather than only main roads, preserving trailheads on smaller roads.
Unmapped parkings cannot seed a scan; main-road-only coverage is not implemented.

Vendor caches under `.cache/` include elevation tiles, AR5 forest PNGs, Overpass responses,
parking-access data, drive times, and place names. `RANDO_OFFLINE=1` makes the graph pipeline use
cached vendor data only, including summit names. Missing terrain remains unknown/impassable;
unknown names stay unset and can be retried online. The preview may make parking and routing
requests unless offline mode is enabled. It does not download elevation or allocate terrain meshes.

Complete terrain graphs are cached at `.cache/graph-v3/<settings-hash>/<x>_<y>.json`. The hash
includes algorithm/terrain identifiers, routing settings, and local winter-road overrides. Origin,
drive-time limit, access preference, geographic shape, and terrain-selection buffer are excluded:
changing them reuses overlapping block graphs. Update the algorithm/terrain identifier or invalidate
blocks when their underlying data changes. `--cache-root` relocates graph and name caches; backend
vendor loaders retain their separately configured cache locations.

Assembly reads only this scan's selected block files, remaps duplicate parking IDs, qualifies
parkings for the current origin, and retains graph nodes reachable from those parkings (including
summit-to-run links). Per-origin driving times and filtering never overwrite the reusable block
JSON. Failed terrain blocks, missing parking blocks, and unknown drive times appear in the output;
`complete` is false for known missing inputs affecting the query. This flag does not guarantee that
OSM lists every parking or that fallback vendor caches cover the entire area.

The default output is `data/graph-<name>-<date>.json`; use `--output` to keep multiple queries with
the same name/date. `--workers` defaults to two. The site builder copies datasets into `docs/` and
updates its dataset index. Rebuilding code alone does not update published JSON; review and commit
the generated site files to publish through GitHub Pages.

Other scan pipelines are `scripts/scan_region.py` → `review.py` → `review_page.py` for ski faces,
and `scripts/toppturs_scan.py LON LAT MAX_MIN` → `toppturs_page.py` / `toppturs_gpx.py` for the
separate single-tour datasets. Fall-line propagation uses pointer jumping; the shared block runner
defaults to four workers, while the graph scanner explicitly uses two.

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
