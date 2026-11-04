r"""Multi-panel publication figures of EAVES.

Renders the publication figures (p1-p6 main + s1-s5 supplementary) from existing EAVES outputs into the
plot directory (``<OUTPUT_DIR>/2_results_plots``). All figures share a single
matplotlib rcParams block defined in :mod:`._shared`. Every panel is drawn from
the output CSVs or from re-invoked pipeline calls.

Panel sets
----------
p1   Domain map (a) and pipeline flowchart (b).
p2   Dam wall placement on three exemplar reservoirs from three of the six
     placement stages: Stage 1 direct placement (a), Stage 4 river-direction
     retry (b), Stage 6 fallback (c).
p3   EAVES outputs at the reservoir with sonar bathymetry: SRTM DEM (a),
     area-volume log-log curve with power-law fit (b), histogram of the
     unconstrained exponent ``b`` over the trusted set (c).
p4   Leave-one-out evaluation of the regionalization procedure at three fill levels.
p5   Baish comparison and domain-wide volume ratio: area-volume (a) and
     elevation-area (b) curves from SRTM, sonar and the design table,
     volume-ratio distribution across the domain (c).
p6   EAVES against the GRDL reference curves, one row per reference reservoir:
     area-volume (a) and depth-area (b) curves.
s1   K-means clustering diagnostic for the exponent ``b``.
s2   Per-dam volume uncertainty band.
s3   Propagation of SRTM vertical error into recovered volume.
s4   Capacity-threshold sweep behind the training cut of the regional exponent.
s5   Sensitivity of the trusted set to the placement and acceptance constants.

CLI
---
    python -m eaves.postprocess.panels --settings region/ksa/ksa.json
    python -m eaves.postprocess.panels --settings region/ksa/ksa.json \
        --output-dir region/ksa/output/2_results_plots --figures 1 3 4

Programmatic use
----------------
    from eaves.postprocess.panels import make_panels
    make_panels()
"""

from __future__ import annotations

import os
from pathlib import Path

import eaves.config as _cfg

from ._shared import PANEL_RCPARAMS, apply_style
from .p1 import make_p1_domain
from .p2 import make_p2_placement
from .p3 import make_p3_baish
from .p4 import make_p4_validation
from .p5 import make_p5_comparison
from .p6 import make_p6_grdl_comparison
from .s1 import make_s1_clustering
from .s2 import make_s2_uncertainty
from .s3 import make_s3_dem_error
from .s4 import make_s4_threshold
from .s5 import make_s5_sensitivity

__all__ = [
    "PANEL_RCPARAMS",
    "apply_style",
    "make_p1_domain",
    "make_p2_placement",
    "make_p3_baish",
    "make_p4_validation",
    "make_p5_comparison",
    "make_p6_grdl_comparison",
    "make_s1_clustering",
    "make_s2_uncertainty",
    "make_s3_dem_error",
    "make_s4_threshold",
    "make_s5_sensitivity",
    "make_panels",
]


def _ensure_settings_loaded() -> None:
    """Raise if required ``eaves.config`` paths are absent."""
    required = ("CSV_DIR", "DAMS_CSV", "COUNTRY_SHP", "TARGET_COUNTRY", "PLOT_DIR")
    missing = [a for a in required if not getattr(_cfg, a, None)]
    if missing:
        raise RuntimeError(
            "EAVES settings not loaded. Pass --settings <file>.json or call "
            "eaves.settings.load_settings(...) before generating panel figures. "
            f"Missing config attrs: {missing}"
        )


def _default_output_dir() -> Path:
    """Default destination: the regional plot directory ``<OUTPUT_DIR>/2_results_plots``."""
    plot_dir = getattr(_cfg, "PLOT_DIR", None)
    if not plot_dir:
        raise RuntimeError(
            "PLOT_DIR is not set. Load a settings file or pass --output-dir."
        )
    return Path(plot_dir)


def make_panels(
    output_dir: str | os.PathLike | None = None,
    figures: tuple = ("1", "2", "3", "4", "5", "6", "s1", "s2", "s3", "s4", "s5"),
) -> dict:
    """Render the requested panel figures into ``output_dir``.

    Parameters
    ----------
    output_dir
        Destination directory. Defaults to ``<OUTPUT_DIR>/2_results_plots``.
    figures
        Subset of ``{"1", "2", "3", "4", "5", "6", "s1", "s2", "s3", "s4", "s5"}``
        to render. Defaults to every figure. Integer items are accepted too and
        converted to strings.

    Returns
    -------
    dict mapping panel id -> list of rendered output paths.
    """
    _ensure_settings_loaded()
    out_dir = Path(output_dir) if output_dir is not None else _default_output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    apply_style()

    figures = tuple(str(f) for f in figures)

    rendered: dict = {}
    builders = {
        "1":  make_p1_domain,
        "2":  make_p2_placement,
        "3":  make_p3_baish,
        "4":  make_p4_validation,
        "5":  make_p5_comparison,
        "6":  make_p6_grdl_comparison,
        "s1": make_s1_clustering,
        "s2": make_s2_uncertainty,
        "s3": make_s3_dem_error,
        "s4": make_s4_threshold,
        "s5": make_s5_sensitivity,
    }
    for pid, fn in builders.items():
        if pid not in figures:
            continue
        try:
            rendered[pid] = [fn(out_dir)]
        except Exception as e:
            # A panel failure (usually a missing input) is reported and does not abort sibling panels
            print(f"[panels] skipped {pid}: {type(e).__name__}: {e}")
    return rendered
