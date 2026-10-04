"""Drainage of a DEM window and the test that a pool drains out through its wall.

A reservoir is the water that leaves through its dam. The window is flooded
from its edge inward in order of elevation, which gives every cell the neighbor
it drains to. A flood fill counts as the reservoir of a dam when most of the
pool it holds at catalog capacity leaves that pool next to the wall, and not
toward the far end of the pool. A fill on the downstream side of the wall
drains out at its far end and is rejected, whichever way the local slope at
the dam points.
"""

from __future__ import annotations

import heapq

import numpy as np
from scipy.ndimage import binary_dilation

from ..config import (
    DRAIN_MAX_OUTLET_POSITION,
    DRAIN_MIN_PIXELS,
    DRAIN_MIN_SHARE,
    DRAIN_WALL_TOLERANCE_M,
)

_EIGHT_CONNECTED = np.ones((3, 3), dtype=bool)
_NEIGHBORS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
# Rise given to a cell that lies no higher than the cell that reached it, so flats and pits drain toward their outlet
_FLAT_RISE_M = 1e-3

_last = {"dem": None, "downstream": None}


def downstream_cells(dem):
    """Flat index of the cell each cell of ``dem`` drains to.

    The window is flooded from its edge and from the rim of its voids inward
    in order of elevation, and each cell drains to the cell that reached it.
    Edge cells, rim cells and voids carry -1. The result for the last window
    is kept, since placement tests many fills on one window, so a window must
    not be modified in place between calls.
    """
    if _last["dem"] is dem:
        return _last["downstream"]

    nrows, ncols = dem.shape
    valid = np.isfinite(dem)
    edge = np.zeros((nrows, ncols), dtype=bool)
    edge[0, :] = edge[-1, :] = edge[:, 0] = edge[:, -1] = True
    rim = binary_dilation(~valid, structure=_EIGHT_CONNECTED)
    seeds = np.flatnonzero(((edge | rim) & valid).ravel()).tolist()

    level = np.where(valid, dem, np.inf).ravel().tolist()
    reached = (~valid).ravel().tolist()
    downstream = [-1] * (nrows * ncols)
    for cell in seeds:
        reached[cell] = True
    heap = [(level[cell], cell) for cell in seeds]
    heapq.heapify(heap)

    while heap:
        z_cell, cell = heapq.heappop(heap)
        r, c = divmod(cell, ncols)
        for dr, dc in _NEIGHBORS:
            nr, nc = r + dr, c + dc
            if 0 <= nr < nrows and 0 <= nc < ncols:
                neighbor = nr * ncols + nc
                if not reached[neighbor]:
                    reached[neighbor] = True
                    downstream[neighbor] = cell
                    z_neighbor = level[neighbor]
                    if z_neighbor <= z_cell:
                        z_neighbor = z_cell + _FLAT_RISE_M
                        level[neighbor] = z_neighbor
                    heapq.heappush(heap, (z_neighbor, neighbor))

    _last["dem"] = dem
    _last["downstream"] = np.asarray(downstream, dtype=np.int64)
    return _last["downstream"]


def capacity_pool(footprint, dem, capacity_m3, pixel_area):
    """Part of ``footprint`` under water when the fill holds ``capacity_m3``.

    A fill that holds less than the capacity at its full level is returned whole.
    """
    z = dem[footprint]
    z = np.sort(z[np.isfinite(z)])
    if z.size == 0:
        return footprint
    n_wet = np.arange(1, z.size + 1)
    volume_at = pixel_area * (n_wet * z - np.cumsum(z))
    first_above = int(np.searchsorted(volume_at, capacity_m3))
    if first_above >= z.size:
        return footprint
    if first_above == 0:
        water_level = z[0]
    else:
        water_level = z[first_above - 1] + (capacity_m3 - volume_at[first_above - 1]) / (pixel_area * first_above)
    return footprint & (dem <= water_level)


def _pool_outlets(pool, dem, dam_r, dam_c):
    """Outlets of ``pool``, the cells where its water leaves it.

    Returns the number of pool cells each outlet drains, the distance of each
    outlet from the dam cell, the distance of the farthest pool cell from the
    dam cell, and the number of pool cells. Distances are in pixels.
    """
    downstream = downstream_cells(dem)
    ncols = dem.shape[1]
    in_pool = pool.ravel() & np.isfinite(dem).ravel()
    cells = np.flatnonzero(in_pool)
    if cells.size == 0:
        return np.zeros(0), np.zeros(0), 0.0, 0

    position = np.full(in_pool.size, -1, dtype=np.int64)
    position[cells] = np.arange(cells.size)
    target = downstream[cells]
    stays = target >= 0
    stays[stays] = in_pool[target[stays]]
    # Each pool cell points to the next pool cell on its way out, and the cells where water leaves the pool point to themselves
    outlet = np.arange(cells.size)
    outlet[stays] = position[target[stays]]
    while True:
        further = outlet[outlet]
        if np.array_equal(further, outlet):
            break
        outlet = further

    drained = np.bincount(outlet, minlength=cells.size)
    outlets = np.flatnonzero(drained)
    rows, cols = np.divmod(cells, ncols)
    distance = np.hypot(rows - dam_r, cols - dam_c)
    return drained[outlets], distance[outlets], float(distance.max()), cells.size


def share_draining_near(pool, dem, dam_r, dam_c, reach_px):
    """Share of ``pool`` whose water leaves the pool within ``reach_px`` of the dam cell."""
    drained, distance, _, n_cells = _pool_outlets(pool, dem, dam_r, dam_c)
    if n_cells == 0:
        return 0.0
    return float(drained[distance <= reach_px].sum() / n_cells)


def outlet_position(pool, dem, dam_r, dam_c):
    """Where ``pool`` drains out along its own length, 0 at the dam cell and 1 at its farthest cell.

    Each outlet counts by the share of the pool it drains.
    """
    drained, distance, extent_px, n_cells = _pool_outlets(pool, dem, dam_r, dam_c)
    if n_cells == 0 or extent_px == 0:
        return 0.0
    return float((drained * distance).sum() / n_cells / extent_px)


def drains_through_wall(footprint, dem, dam_r, dam_c, wall_length_m, capacity_m3, pixel_area):
    """Whether the capacity-level pool of ``footprint`` drains out next to the wall centered on the dam cell.

    The pool must leave most of its water within reach of the wall, which judges
    a long pool, and must not drain out toward its far end, which judges a pool
    shorter than that reach.
    """
    pool = capacity_pool(footprint, dem, capacity_m3, pixel_area)
    if int(pool.sum()) < DRAIN_MIN_PIXELS:
        return True
    drained, distance, extent_px, n_cells = _pool_outlets(pool, dem, dam_r, dam_c)
    reach_px = (0.5 * wall_length_m + DRAIN_WALL_TOLERANCE_M) / np.sqrt(pixel_area)
    if drained[distance <= reach_px].sum() / n_cells < DRAIN_MIN_SHARE:
        return False
    return (drained * distance).sum() / n_cells / extent_px < DRAIN_MAX_OUTLET_POSITION
