"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import sys

from .core import ConversionError, convert_file


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
    a = p.parse_args(argv)
    if a.delimiter in ("\\t", "tab"):
        a.delimiter = "\t"
    try:
        res = convert_file(a.csv, a.lat, a.lon, a.delimiter, a.encoding)
    except (ConversionError, OSError, UnicodeDecodeError, LookupError) as e:
        print(f"error: {e}", file=sys.stderr)
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
    print(f"lat column: {res.lat_column}, lon column: {res.lon_column}; "
          f"{len(res.geojson['features'])} features, {len(res.errors)} rows skipped",
          file=sys.stderr)
    for e in res.errors:
        print(f"  line {e.row}: {e.reason}", file=sys.stderr)
    return 1 if (a.strict and res.errors) else 0
