"""CLI entry point: ``python -m eaves.postprocess.panels``."""

from __future__ import annotations

import argparse

from ..panels import make_panels
from ...settings import load_settings


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Render EAVES Data Descriptor panel figures (1-4).",
    )
    parser.add_argument(
        "--settings",
        default=None,
        help="Path to a settings JSON file (e.g. settings/ksa.json). "
        "Required unless settings have already been applied in-process.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Destination directory for the rendered figures. "
        "Defaults to <OUTPUT_DIR>/2_results_plots.",
    )
    parser.add_argument(
        "--figures",
        nargs="+",
        type=int,
        choices=[1, 2, 3, 4],
        default=[1, 2, 3, 4],
        metavar="N",
        help="Subset of figure numbers to render (default: all).",
    )
    args = parser.parse_args(argv)

    if args.settings:
        load_settings(args.settings)
        print(f"[settings] Loaded {args.settings}")

    out = make_panels(
        output_dir=args.output_dir,
        figures=tuple(args.figures),
    )
    n = sum(len(v) for v in out.values())
    print(f"\nDone. Rendered {n} file(s) in total.")


if __name__ == "__main__":  # pragma: no cover
    main()
