"""Post-processing of the EAVES outputs, from regionalization and validation to the domain report and the panel figures.

:func:`panels.make_panels` renders the panel figures, and
``python -m eaves.postprocess.panels --help`` lists its command-line options.
"""

from .panels import make_panels  # noqa: F401
