# Randonnée terrain and sunlight planner

## Agreed goal and scope

Build a responsive browser app for desktop and iPhone that helps find and inspect ski faces, initially in mountain areas roughly 2–3 hours' drive from Trondheim. Trollheimen/Oppdal and Meråker are initial exploration areas. The driving radius is approximate; link starting points to driving directions rather than calculating a driving-time filter.

The default ski-face preference is strictly **20° < slope < 30°**. Gentler approaches are allowed and the entire drawn ascent is assessed separately. Support south-facing terrain for autumn/early-winter sunlight and north-facing terrain for spring shade, with date- and time-specific mountain shadows. Estimate whether a user-drawn or imported ascent takes 3–4 hours.

Terrain matching is not a snow-stability assessment. Keep steep terrain and avalanche runout context visible independently of preference matches. Do not label shaded, north-facing, or sub-30° terrain as safe.

## Data and feasibility

- Geonorge is the discovery catalogue: https://www.geonorge.no/en/for-developers/apis/
- Kartverket topographic tiles: https://www.kartverket.no/en/on-land/kart/bygge-inn-kart-pa-nett
- Terrain models: https://www.kartverket.no/en/api-and-data/terrengdata
- Use numerical elevation downloads, initially sampled at 10 m. Check selected faces against available 1 m terrain to expose smaller steep features.
- Derive slope and aspect in metric projected coordinates; calculate sunlight from solar position, face orientation, and surrounding terrain horizons.
- NVE slope layers: https://kart.nve.no/enterprise/rest/services/Bratthet/MapServer
- Full avalanche forecast API: https://api.nve.no/doc/snoeskredvarsel/
- Recreational runout context: verify the appropriate NVE layer, coverage, and legend.
- Weather: https://api.met.no/weatherapi/locationforecast/2.0/documentation
- Safety context: https://www.varsom.no/avalanches/about-avalanches/avalanche-terrain/

Verify service access, numerical output, local coverage, attribution/caching terms, and terrain quality. Missing coverage must remain unknown, with no synthetic-data fallback.

## User experience

0. Find candidates (added 2026-09-13): scan the current map view (≤30 × 30 km) for fall-line
   runs with long continuous skiing in the slope band. "Continuous" means run length along the
   fall line (default ≥500 m) inside 20–30°; short gentler benches are tolerated, anything steeper
   than the band ends the run. Rank by approach from the nearest road. Classify open / mixed /
   tree runs from forest polygons so tree-skiing candidates form their own set. Show run length,
   drop, mean/max slope, share ≥30°, aspect, approximate sun hours, and the line on the map.
0b. Summit tours (added 2026-09-13, `backend/toppturs.py`, `scripts/toppturs_scan.py`): summits =
   10 m local maxima ≥900 m with ≥150 m relief in 1.5 km; ascent = least-cost path from OSM roads
   with ≥35° impassable and 30–35° cost ×4 (gentlest line the terrain allows, not a checked route);
   descent = best 20–30° run starting within 800 m / 200 m below the summit; drive time from an
   origin via OSRM. First run: 13 blocks around Skarvatnet, 476 summits, 169 within 60 min.
   Not yet in the app UI — script + review page only.
1. Choose date and outing window; scrub a map time slider.
2. Set editable minimum/maximum slope and aspect. South and north presets each span ±45° by default.
3. Choose seek sunlight, seek shade, or aspect-only terrain matching. Display potential direct sunlight separately from forecast cloud cover.
4. Inspect terrain: elevation, slope distribution, aspect, resolution, and estimated sun windows. Preserve steep patches instead of classifying an entire face by its average slope.
5. Draw or import an ascent route. Show distance, accumulated ascent, terrain slope along the route, and estimated moving time. Flag sections >=30° independently of the face filter.
6. Save plans locally and export/import GPX. No account required; export/import provides device transfer.
7. Present the complete applicable avalanche forecast with source and validity dates. Keep unavailable, stale, and out-of-range forecasts explicit.

## Implementation decisions

- Frontend: TypeScript, React, MapLibre. Desktop side panel; mobile bottom sheet.
- Backend: Python API; NumPy and GDAL-backed Rasterio for terrain processing; tiled/cached numerical rasters.
- Solar calculations: terrain horizons beyond the visible map boundary, 10-minute sunlight sampling, Europe/Oslo timezone. Compare shadow horizons with a larger surrounding extent before accepting results.
- API capabilities: prepare terrain area, serve overlay imagery, inspect terrain and sunlight, analyze route, fetch/cache forecasts. Include terrain resolution and forecast validity metadata.
- Ascent estimate: `horizontal distance / 4 km/h + accumulated ascent / 400 m/h`. Both rates editable. Label moving-time estimate; breaks and snow conditions require additional allowance.
- No combined safety score.
- Candidate search: 10 m mosaic across tiles; D8 steepest descent; 3×3-smoothed slope for the band
  test, raw slope reported; tops = cells with ≥ min in-band run length and ≥70 % of the run in band,
  clustered with 8-connectivity; the longest run per cluster is traced and returned. Runs whose raw
  mean slope leaves the band are dropped (the D8 line hugs gully floors). Roads and forest from
  OpenStreetMap via Overpass (ODbL) — driveable highway classes; wood/forest polygons stitched from
  multipolygon relations, holes burned out. Approach = straight-line distance and gain from the
  nearest road node (lower bound; winter plowing and parking unknown). Sun hours per candidate use
  100 m horizons only. Known limits: no tree density/spacing (OSM says forest, not skiability);
  no slope-width measure; clusters may split one face into several entries.
- Deferred: automatic tour generation, calculated road-travel filtering, offline navigation, native apps, accounts, snow-stability prediction.

## Delivery and validation

1. Data proof: numerical pilot terrain, slope/aspect, hazard layer and attribution verification.
2. Sunlight proof: flat ground, north/south faces, ridge-shadowed valley, winter low sun, boundary effects; compare independent solar calculations and selected field observations.
3. Usable prototype: filters, slider, inspection, route drawing/import, forecasts, local saves/export.
4. Tests: strict slope boundaries, north-aspect wraparound, missing elevation, Oslo daylight saving, GPX round trips, stale/unavailable forecasts, incomplete route coverage.
5. Browser checks: desktop and iPhone Safari layouts and interactions; aim for filter changes visible within one second after terrain is loaded.

Success: find a promising face, understand expected sun exposure, and inspect a plausible 3–4-hour ascent with visible terrain/forecast limitations.

## Implementation findings (2026-09-13)

- Workspace started empty. User explicitly authorized implementation.
- The OGC example collection at `kartverket-ogc-api.azurewebsites.net` only covers a southern sample; do not use it as the national pilot source.
- Verified national numerical service: `https://hoydedata.no/arcgis/rest/services/NHM_DTM_25833/ImageServer`. Supports float32 TIFF export, EPSG:25833, and up to 4096×4096 pixels. Request `renderingRule={"rasterFunction":"None"}` to avoid rendered hillshade. Actual numerical raster retrieval still needs exercising.
- Implementation uses on-demand 4×4 km areas at 10 m resolution, a 100 m high-resolution border, and surrounding elevation at 100 m out to 40 km. Shadow grid is 40 m with 5° horizon bearings; disclose approximation. Compare 20 km vs 40 km horizon extent. These computational resolutions require validation.
- Verified recreational combined slope/runout tiles: `https://gis3.nve.no/arcgis/rest/services/wmts/Bratthet_med_utlop_2024/MapServer`. Web Mercator XYZ via `/tile/{z}/{y}/{x}`, advertised cache levels 5–16; `exportTilesAllowed=false`, so use live display, not bulk tile export. Legend and rendering still need checking.
- Verified full forecast response: `https://api01.nve.no/hydrology/forecast/avalanche/v6.3.2/api/AvalancheWarningByCoordinates/Detail/62.65/9.55/2/2026-04-15/2026-04-15`. Documentation Swagger routes returned errors, but this detail endpoint returned complete data.
- Default system Python is 3.14 with no compatible Rasterio wheel. Recreated `.venv` with installed Python 3.12; dependency installation is in progress.
- Default PATH Node is old (14.16). Investigate `/opt/homebrew/bin/node` or install a project-local modern Node runtime before running Vite/Playwright. Initial `npm install` completed under old npm with engine warnings; reinstall with modern npm if needed.

## Status (2026-09-13, second session)

Implemented and verified: backend against live Kartverket/NVE/MET (area load ~8 s, overlay 60 ms);
`src/App.tsx` + `src/style.css` (desktop side panel, mobile bottom sheet); 15 pytest + 7 vitest
unit tests; Playwright e2e for desktop and iPhone viewports (`e2e/app.spec.ts`, Chromium — the
WebKit build rejects a setting on this macOS); README with run commands. Project-local Node 22 in
`.tools/node`. Overlay palette moved to green/violet so it cannot be confused with NVE's yellow-red
steepness and blue runout tiles; analysis layer draws above the NVE layer.

Candidate search implemented (`backend/search.py`, `/api/search`, "Find candidates" section) with
unit tests for run propagation, ring stitching and forest rasterisation, and an e2e step. Verified
on Oppdal: 11 candidates in a 20 × 16 km extent; treeline from OSM forest lands at ~1000 m.
Fixed a latent job-polling bug that broke uncached area loads from the browser.

Region scan (`scripts/scan_region.py`, `review.py`, `review_page.py`): 30 blocks, 1,529 raw runs,
643 distinct faces; review page published. Overpass was unreliable (504/429) — road queries fall
back to mirrors and then to cached responses; forest moved to NIBIO AR5 WMS.

Open items: put summit-tour search in the app (API + UI); ascent path should also avoid runout
zones and consider NVE layers; sunlight field validation against independent solar calculations / observations
(delivery step 2 partly done via unit geometry tests only); 1 m terrain check of selected faces;
real-device iPhone Safari check (only emulated viewport so far); Claude-in-Chrome extension was not
connected this session.
