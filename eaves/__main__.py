"""Entry point for ``python -m eaves``. Delegates to :func:`eaves.cli.main` and exits with its code."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
