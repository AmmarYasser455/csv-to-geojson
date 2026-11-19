"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import os
import sys

from .core import ConversionError, convert_file


def _same_file(a: str, b: str) -> bool:
    """True if both paths name the same file (equivalent paths, symlinks, hard links)."""
    if os.path.realpath(a) == os.path.realpath(b):
        return True
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="csv-to-geojson",
        description="Convert a CSV with coordinates to GeoJSON (WGS 84, [lon, lat]).",
    )
    p.add_argument("csv", help="input CSV file")
    p.add_argument("-o", "--output", help="output file (default: stdout)")
    p.add_argument("--lat", help="latitude column (default: auto-detect)")
    p.add_argument("--lon", help="longitude column (default: auto-detect)")
    p.add_argument("--delimiter", help="field delimiter, one character or 'tab' (default: auto-detect)")
    p.add_argument("--encoding", default="utf-8-sig", help="input encoding (default: utf-8-sig)")
    p.add_argument("--strict", action="store_true", help="exit with status 1 if any row was skipped")
    p.add_argument("--rejects", help="write skipped rows (line, reason, values) to this JSON file")
    a = p.parse_args(argv)
    if a.delimiter in ("\\t", "tab"):
        a.delimiter = "\t"
    try:
        res = convert_file(a.csv, a.lat, a.lon, a.delimiter, a.encoding)
    except (ConversionError, OSError, UnicodeDecodeError, LookupError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if a.rejects:
        for label, other in (("input CSV", a.csv), ("output", a.output)):
            if other and _same_file(a.rejects, other):
                print(f"error: --rejects path is the same file as the {label}: {a.rejects}",
                      file=sys.stderr)
                return 2
    out = json.dumps(res.geojson, indent=2, ensure_ascii=False) + "\n"
    try:
        if a.output:
            with open(a.output, "w", encoding="utf-8") as f:
                f.write(out)
        else:
            sys.stdout.write(out)
    except (OSError, UnicodeEncodeError) as e:
        print(f"error: cannot write output: {e}", file=sys.stderr)
        return 2
    if a.rejects:
        rejects = [{"line": e.row, "reason": e.reason, "values": e.values} for e in res.errors]
        try:
            with open(a.rejects, "w", encoding="utf-8") as f:
                f.write(json.dumps(rejects, indent=2, ensure_ascii=False) + "\n")
        except (OSError, UnicodeEncodeError) as e:
            print(f"error: cannot write rejects: {e}", file=sys.stderr)
            return 2
    print(f"lat column: {res.lat_column}, lon column: {res.lon_column}; "
          f"{len(res.geojson['features'])} features, {len(res.errors)} rows skipped",
          file=sys.stderr)
    for e in res.errors:
        print(f"  line {e.row}: {e.reason}", file=sys.stderr)
    return 1 if (a.strict and res.errors) else 0
