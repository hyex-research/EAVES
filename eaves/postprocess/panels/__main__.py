"""CLI entry point: ``python -m eaves.postprocess.panels``."""

from __future__ import annotations

import argparse

from ..panels import make_panels
from ...settings import load_settings


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Render EAVES Data Descriptor panel figures (1-5).",
    )
    parser.add_argument(
        "--settings",
        default=None,
        help="Path to a settings JSON file (e.g. region/ksa/ksa.json). "
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
        type=str,
        choices=["1", "2", "3", "4", "5", "s1", "s2", "s3"],
        default=["1", "2", "3", "4", "5", "s1", "s2", "s3"],
        metavar="ID",
        help="Subset of panel IDs to render (default: all, including the "
             "supplementary s1, s2, and s3 figures).",
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
    return None


if __name__ == "__main__":  # pragma: no cover
    main()
