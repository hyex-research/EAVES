"""Entry point for ``python -m eaves``. Delegates to :func:`eaves.cli.main`."""

from .cli import main


if __name__ == "__main__":
    main()
