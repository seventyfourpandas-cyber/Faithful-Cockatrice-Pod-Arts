#!/usr/bin/env python3
"""Validate the generated database against Cockatrice's official v4 XSD."""

from __future__ import annotations

import argparse
from pathlib import Path


HERE = Path(__file__).resolve().parent
REPOSITORY_ROOT = HERE.parents[1]


def main(*, require_lxml: bool) -> int:
    try:
        from lxml import etree
    except ImportError:
        if require_lxml:
            raise SystemExit("lxml is required for Cockatrice XSD validation")
        print("SKIP: lxml is not installed")
        return 0

    schema = etree.XMLSchema(etree.parse(str(HERE / "cards_v4.xsd")))
    document = etree.parse(str(REPOSITORY_ROOT / "customsets" / "willex_whimsical_arts.xml"))
    schema.assertValid(document)
    print("PASS: generated XML conforms to Cockatrice card database v4 XSD")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-lxml", action="store_true")
    args = parser.parse_args()
    raise SystemExit(main(require_lxml=args.require_lxml))
