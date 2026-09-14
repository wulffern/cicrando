"""Tour graph along driving corridors from Trondheim. Usage: corridor_scan.py NAME [max_drive_hours] [buffer_km]"""
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.graph_scan import plan_scan, execute_scan
from backend.regions import Corridor

TRONDHEIM = (10.3951, 63.4305)
LEGS = [
    [TRONDHEIM, (9.6910, 62.5940), (9.5492, 62.6940), (8.5600, 62.6780), (8.9700, 62.9760), TRONDHEIM],   # Oppdal – Skarvatnet – Sunndalsøra – Surnadal loop
    [TRONDHEIM, (11.7480, 63.4160), (11.9500, 63.4500)],                                                   # E14 to Meråker / Teveldal
    [TRONDHEIM, (11.4950, 64.0150), (12.3800, 64.2460), (12.3100, 64.4620)],                               # E6 north: Steinkjer – Snåsa – Grong
]
if __name__ == '__main__':
    name = sys.argv[1] if len(sys.argv) > 1 else 'Trondheim'
    max_drive = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0
    buffer_km = float(sys.argv[3]) if len(sys.argv) > 3 else 15
    region = Corridor(TRONDHEIM, LEGS, buffer_km, name)
    print(f'{len(region._xy)} route points, {len(region.blocks())} coverage blocks', flush=True)
    plan = plan_scan(region, max_drive_hours=max_drive, access='open')
    print(f"{plan['parking_count']} parkings in corridor, {len(plan['eligible_parkings'])} eligible (≤{max_drive} h), {len(plan['terrain_blocks'])} terrain blocks", flush=True)
    graph = execute_scan(plan, name, workers=2)
    out = Path(f'data/graph-{name.lower()}-{time.strftime("%Y-%m-%d")}.json')
    from backend.store import save
    save(graph, out)
    print('wrote', out, {k: len(graph[k]) for k in ('parkings', 'summits', 'runs', 'edges')}, 'complete:', graph['complete'], flush=True)
