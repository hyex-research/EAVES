"""Multi-panel publication figures for the EAVES Data Descriptor.

Renders four publication figures from existing EAVES outputs into the
plot directory (``<OUTPUT_DIR>/2_results_plots``). All figures share a single
matplotlib rcParams block (Scientific Data / Nature portfolio conventions)
defined in :mod:`._shared`. Every panel is drawn directly from CSV data or
re-invoked pipeline calls so that all axis fonts, tick labels, and titles
match across panels.

Panel sets
----------
p1   Domain map (a) and pipeline flowchart (b).
p2   Dam wall placement on three exemplar reservoirs illustrating the six
     pipeline stages: Stage 1 fast path (a), Stage 4 river-direction retry
     (b), Stage 6 synthetic fallback (c).
p3   Worked example for the bathymetry-validated reservoir: SRTM DEM (a),
     area--volume log--log curve with power-law fit (b), histogram of the
     volume--area exponent ``b`` over grade-A/B reservoirs (c).
p4   Validation: sonar vs. SRTM (a), EAVES vs. GRDL for three reference
     reservoirs (b), volume-ratio distribution across the domain (c).

CLI
---
    python -m eaves.postprocess.panels --settings settings/ksa.json
    python -m eaves.postprocess.panels --settings settings/ksa.json \
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


__all__ = [
    "PANEL_RCPARAMS",
    "apply_style",
    "make_p1_domain",
    "make_p2_placement",
    "make_p3_baish",
    "make_p4_validation",
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
            "PLOT_DIR is not set; load a settings file or pass --output-dir."
        )
    return Path(plot_dir)


def make_panels(
    output_dir: str | os.PathLike | None = None,
    figures: tuple[int, ...] = (1, 2, 3, 4),
) -> dict[int, list[Path]]:
    """Render the requested panel figures into ``output_dir``.

    Parameters
    ----------
    output_dir
        Destination directory. Defaults to ``<OUTPUT_DIR>/2_results_plots``.
    figures
        Subset of ``{1, 2, 3, 4}`` to render; defaults to all four.

    Returns
    -------
    dict mapping figure number -> list of rendered output paths.
    """
    _ensure_settings_loaded()
    out_dir = Path(output_dir) if output_dir is not None else _default_output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    apply_style()

    rendered: dict[int, list[Path]] = {}
    if 1 in figures:
        rendered[1] = [make_p1_domain(out_dir)]
    if 2 in figures:
        rendered[2] = [make_p2_placement(out_dir)]
    if 3 in figures:
        rendered[3] = [make_p3_baish(out_dir)]
    if 4 in figures:
        rendered[4] = [make_p4_validation(out_dir)]
    return rendered
