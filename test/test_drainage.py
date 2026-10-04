"""Unit tests for the drainage of a DEM window and the drain-through-the-wall test.

All checks run on a synthetic V-shaped valley that falls toward higher row
numbers, with its channel along one column, so the direction of flow and the
side of a dam on which its reservoir lies are known.
"""

from __future__ import annotations

import numpy as np
import pytest

from eaves.pipeline.drainage import (
    capacity_pool,
    downstream_cells,
    drains_through_wall,
    outlet_position,
    share_draining_near,
)

NROWS, NCOLS = 200, 61
CHANNEL = 30
DAM_ROW = 80
PIXEL_AREA = 900.0
WATER_DEPTH = 6.0
WALL_LENGTH_M = 300.0


@pytest.fixture
def valley():
    rows, cols = np.mgrid[0:NROWS, 0:NCOLS]
    return (NROWS - rows) * 0.5 + np.abs(cols - CHANNEL) * 1.0


def _pool(valley, upstream):
    """Cells below the water level at the dam, on one side of the dam row."""
    rows = np.mgrid[0:NROWS, 0:NCOLS][0]
    wet = valley <= valley[DAM_ROW, CHANNEL] + WATER_DEPTH
    return wet & (rows < DAM_ROW) if upstream else wet & (rows > DAM_ROW)


def test_every_cell_drains_downhill(valley):
    downstream = downstream_cells(valley)
    cells = np.flatnonzero(downstream >= 0)
    assert cells.size > 0.9 * valley.size
    assert np.all(valley.ravel()[downstream[cells]] <= valley.ravel()[cells])


def test_channel_drains_along_the_valley(valley):
    downstream = downstream_cells(valley)
    cell = DAM_ROW * NCOLS + CHANNEL
    for _ in range(20):
        cell = downstream[cell]
    row, col = divmod(int(cell), NCOLS)
    assert row == DAM_ROW + 20
    assert col == CHANNEL


def test_voids_and_window_edge_carry_no_downstream_cell(valley):
    dem = valley.copy()
    dem[100:103, 10:13] = np.nan
    downstream = downstream_cells(dem).reshape(dem.shape)
    assert np.all(downstream[100:103, 10:13] == -1)
    assert np.all(downstream[0, :] == -1)
    assert np.all(downstream[-1, :] == -1)


def test_upstream_pool_drains_out_at_the_wall(valley):
    pool = _pool(valley, upstream=True)
    assert share_draining_near(pool, valley, DAM_ROW, CHANNEL, reach_px=5.0) > 0.9


def test_downstream_pool_drains_out_far_from_the_wall(valley):
    pool = _pool(valley, upstream=False)
    assert share_draining_near(pool, valley, DAM_ROW, CHANNEL, reach_px=40.0) < 0.1


def test_upstream_pool_drains_out_at_its_dam_end(valley):
    assert outlet_position(_pool(valley, upstream=True), valley, DAM_ROW, CHANNEL) < 0.2


def test_downstream_pool_drains_out_at_its_far_end(valley):
    assert outlet_position(_pool(valley, upstream=False), valley, DAM_ROW, CHANNEL) > 0.9


def test_capacity_pool_holds_the_capacity(valley):
    fill = _pool(valley, upstream=True)
    depth_full = (valley[fill].max() - valley[fill]).sum() * PIXEL_AREA
    pool = capacity_pool(fill, valley, 0.25 * depth_full, PIXEL_AREA)
    assert pool.sum() < fill.sum()
    assert not np.any(pool & ~fill)
    volume = (valley[pool].max() - valley[pool]).sum() * PIXEL_AREA
    assert volume <= 0.25 * depth_full
    assert volume > 0.15 * depth_full


def test_capacity_pool_keeps_a_fill_that_holds_less_than_the_capacity(valley):
    fill = _pool(valley, upstream=True)
    assert np.array_equal(capacity_pool(fill, valley, 1e12, PIXEL_AREA), fill)


def test_fill_is_accepted_only_on_the_upstream_side(valley):
    capacity = 5e5
    assert drains_through_wall(_pool(valley, True), valley, DAM_ROW, CHANNEL, WALL_LENGTH_M, capacity, PIXEL_AREA)
    assert not drains_through_wall(_pool(valley, False), valley, DAM_ROW, CHANNEL, WALL_LENGTH_M, capacity, PIXEL_AREA)


def test_pool_too_small_to_judge_passes(valley):
    tiny = np.zeros_like(valley, dtype=bool)
    tiny[DAM_ROW + 50:DAM_ROW + 53, CHANNEL - 1:CHANNEL + 2] = True
    assert drains_through_wall(tiny, valley, DAM_ROW, CHANNEL, WALL_LENGTH_M, 1e9, PIXEL_AREA)


def test_short_pool_below_the_dam_is_rejected(valley):
    # A pool shorter than the reach of the wall lies wholly within it, so only its outlet position tells the side
    rows = np.mgrid[0:NROWS, 0:NCOLS][0]
    last = DAM_ROW + 12
    short = (valley <= valley[last, CHANNEL] + 4.0) & (rows > DAM_ROW) & (rows <= last)
    assert short.sum() >= 30
    assert share_draining_near(short, valley, DAM_ROW, CHANNEL, reach_px=38.0) == 1.0
    assert outlet_position(short, valley, DAM_ROW, CHANNEL) > 0.65
    assert not drains_through_wall(short, valley, DAM_ROW, CHANNEL, WALL_LENGTH_M, 1e12, PIXEL_AREA)
