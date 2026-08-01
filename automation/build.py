#!/usr/bin/env python3
"""Validate the source catalogs and rebuild the hosted WLX payload."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import wlxlib


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Build the WLX Cockatrice publication")
    result.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    result.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate source catalogs without replacing generated files",
    )
    return result


def main() -> int:
    arguments = parser().parse_args()
    root = arguments.repository_root.resolve()
    try:
        config, _state, printings = wlxlib.validate_repository(root)
        if arguments.validate_only:
            print(
                f"Validated {len(printings)} WLX printing(s) for version {config['version']}."
            )
            return 0
        manifest = wlxlib.build_repository(root)
        print(
            json.dumps(
                {
                    "status": "published",
                    "version": manifest["version"],
                    "card_identities": manifest["cards"],
                    "printings": manifest["printings_count"],
                },
                indent=2,
            )
        )
        return 0
    except wlxlib.WlxError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

