"""EAVES — Elevation–Area–Volume Estimation from SRTM.

Reconstructs reservoir EAV curves from pre-impoundment SRTM topography:
staged dam-wall placement, flood fill to the spillway, a per-dam
V = c*A^b fit, and regionalized parameters where the DEM fit is not
trusted.
"""

__version__ = "1.2.0"
