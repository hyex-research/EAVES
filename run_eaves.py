#!/usr/bin/env python
"""Thin wrapper, equivalent to ``python -m eaves``."""

import sys

from eaves.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
