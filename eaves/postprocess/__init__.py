"""Post-computation: regionalization + diagnostic / validation plots.

The :mod:`panels` submodule renders the publication-grade panel figures
shipped with the EAVES Data Descriptor (figures 1-3); see
:func:`panels.make_panels` for the programmatic entry point
and ``python -m eaves.postprocess.panels --help`` for the CLI.
"""

from .panels import make_panels  # noqa: F401
