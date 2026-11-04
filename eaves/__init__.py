"""EAVES: Elevation-Area-Volume Estimation from SRTM.

Reconstructs reservoir EAV curves from SRTM topography captured in
February 2000, before most dams were built:
staged dam-wall placement, flood fill to the spillway, a per-dam
V = c*A^b fit, and regionalized parameters where the DEM fit is not
trusted.
"""

__version__ = "1.4.0"
