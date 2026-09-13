import math

import pytest

from backend.regions import Region, intersecting_blocks, approach_blocks, BLOCK_M, GRID_ORIGIN
from backend.terrain import TO_LL
from scripts.graph_scan import parse_args


def test_circle_intersections_include_blocks_with_centres_outside_and_tangencies():
    x, y = GRID_ORIGIN
    blocks = intersecting_blocks(x, y, 100)
    assert {(b['x'], b['y']) for b in blocks} == {(x + dx, y + dy) for dx in (-BLOCK_M, 0) for dy in (-BLOCK_M, 0)}
    assert all(b['dist_km'] > .1 for b in blocks)
    # The circle touches the next block's west edge, even though its centre is far outside.
    blocks = intersecting_blocks(x + BLOCK_M / 2, y + BLOCK_M / 2, BLOCK_M / 2)
    assert (x + BLOCK_M, y) in {(b['x'], b['y']) for b in blocks}
    assert (x + BLOCK_M, y + BLOCK_M) not in {(b['x'], b['y']) for b in blocks}


def test_square_uses_full_side_and_negative_grid_coordinates():
    region = Region(tuple(TO_LL.transform(-10000, 7000000)), 'square', 20)
    x, y = region.centre
    assert region.contains(x + 9999, y + 9999)
    assert not region.contains(x + 10001, y)
    assert any(b['x'] < 0 for b in region.blocks())
    for b in region.blocks():
        assert (b['x'] - GRID_ORIGIN[0]) % BLOCK_M == 0
        assert (b['y'] - GRID_ORIGIN[1]) % BLOCK_M == 0
    circle = Region(region.origin, 'circle', 10)
    assert not circle.contains(x + 9999, y + 9999)


def test_approach_blocks_extend_beyond_parking_coverage():
    x, y = GRID_ORIGIN
    parkings = [dict(x=x + BLOCK_M - 10, y=y + BLOCK_M / 2)] * 2
    blocks = approach_blocks(parkings, 12)
    keys = [(b['x'], b['y']) for b in blocks]
    assert len(keys) == len(set(keys))
    assert (x + BLOCK_M, y) in keys


@pytest.mark.parametrize('origin,shape,extent', [((math.nan, 62), 'circle', 60), ((9, 91), 'circle', 60),
                                               ((9, 62), 'circle', 0), ((9, 62), 'square', math.inf)])
def test_invalid_regions(origin, shape, extent):
    with pytest.raises(ValueError):
        Region(origin, shape, extent)


def test_cli_legacy_and_named_forms():
    old = parse_args(['9.54917', '62.69398', 'Skarvatnet', '60'])
    new = parse_args(['--origin', '9.54917', '62.69398', '--name', 'Skarvatnet', '--radius-km', '60'])
    assert old.region == new.region
    square = parse_args(['--origin', '9', '62', '--name', 'Home', '--shape', 'square', '--side-km', '200', '--max-drive-hours', '2', '--plan-only'])
    assert square.region.half_extent == 100000 and square.max_drive_hours == 2 and square.plan_only


@pytest.mark.parametrize('extra', [['--shape', 'square'], ['--side-km', '200'], ['--max-drive-hours', 'nan'], ['--workers', '0']])
def test_cli_rejects_ambiguous_or_invalid_options(extra):
    with pytest.raises(SystemExit):
        parse_args(['--origin', '9', '62', '--name', 'Home'] + extra)
