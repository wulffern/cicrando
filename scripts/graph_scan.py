"""Build origin-specific tour graphs inside circle/square parking coverage.

Legacy: graph_scan.py LON LAT NAME [radius_km]
Named:  graph_scan.py --origin LON LAT --name NAME --max-drive-hours 2 --shape square --side-km 200
"""
import argparse
import json
import logging
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.graph_scan import plan_scan, execute_scan
from backend.regions import Region


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('legacy', nargs='*', metavar='LON LAT NAME [RADIUS_KM]')
    parser.add_argument('--origin', nargs=2, type=float, metavar=('LON', 'LAT'))
    parser.add_argument('--name')
    parser.add_argument('--shape', choices=('circle', 'square'), default='circle')
    parser.add_argument('--radius-km', type=float)
    parser.add_argument('--side-km', type=float)
    parser.add_argument('--max-drive-hours', type=float)
    parser.add_argument('--access', choices=('open', 'plowed', 'all'), default='open',
                        help='open includes plowed and unknown; all also includes closed')
    parser.add_argument('--terrain-buffer-km', type=float, default=12, help='Terrain selection radius around eligible parkings (at least 12 km); does not change ski-leg limits')
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--cache-root', type=Path, default=Path('.cache'), help='Graph and name cache root; vendor caches keep their configured locations')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--plan-only', action='store_true', help='Discover parkings and driving times, then print a plan without building terrain')
    args = parser.parse_args(argv)
    if args.legacy:
        if args.origin or args.name or args.radius_km is not None or args.side_km is not None or args.shape != 'circle' or len(args.legacy) not in (3, 4):
            parser.error('Use either LON LAT NAME [radius_km] or named origin/shape options')
        try:
            args.origin = [float(v) for v in args.legacy[:2]]
            args.radius_km = float(args.legacy[3]) if len(args.legacy) == 4 else 60
        except ValueError:
            parser.error('Coordinates and radius must be numbers')
        args.name = args.legacy[2]
    if args.origin is None or not args.name:
        parser.error('--origin and --name are required')
    if args.workers <= 0:
        parser.error('--workers must be positive')
    if args.shape == 'square':
        if args.side_km is None or args.radius_km is not None:
            parser.error('Square coverage requires --side-km and does not accept --radius-km')
        extent = args.side_km
    else:
        if args.side_km is not None:
            parser.error('Circle coverage uses --radius-km')
        extent = 60 if args.radius_km is None else args.radius_km
    try:
        args.region = Region(tuple(args.origin), args.shape, extent)
        import math
        if not math.isfinite(args.terrain_buffer_km) or args.terrain_buffer_km < 12:
            raise ValueError('Terrain buffer must be finite and at least 12 km')
        if args.max_drive_hours is not None:
            if not math.isfinite(args.max_drive_hours) or args.max_drive_hours <= 0:
                raise ValueError('Maximum driving hours must be positive and finite')
    except ValueError as exc:
        parser.error(str(exc))
    return args


def main(argv=None):
    args = parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format='%(asctime)s %(message)s')
    plan = plan_scan(args.region, args.max_drive_hours, args.access, terrain_buffer_km=args.terrain_buffer_km)
    if args.plan_only:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return
    print(f"{len(plan['eligible_parkings'])} eligible parkings; {len(plan['terrain_blocks'])} terrain blocks; "
          f"{len(plan['unknown_drive_parkings'])} unknown drive times; {len(plan['missing_parking_blocks'])} missing parking blocks", flush=True)
    graph = execute_scan(plan, args.name, args.cache_root, args.workers)
    slug = re.sub(r'[^\w-]+', '-', args.name.lower()).strip('-') or 'origin'
    output = args.output or Path('data') / f"graph-{slug}-{graph['generated'][:10]}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(graph, ensure_ascii=False))
    print(f"{output}: {len(graph['summits'])} summits, {len(graph['edges'])} legs; complete={graph['complete']}")


if __name__ == '__main__':
    main()
