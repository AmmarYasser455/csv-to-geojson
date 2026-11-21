"""Core conversion: coordinate parsing, column detection, FeatureCollection building."""

from __future__ import annotations

import csv
import io
import math
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

LAT_NAMES = ("lat", "latitude", "lat_deg", "latitude_deg", "y", "ycoord", "y_coord", "lat_dd")
LON_NAMES = ("lon", "lng", "long", "longitude", "lon_deg", "longitude_deg", "x", "xcoord", "x_coord", "lon_dd")

_DMS = re.compile(
    r"""^\s*(?P<h1>[NSEWnsew])?\s*(?P<sign>[+-])?\s*
        (?P<d>\d+(?:[.,]\d+)?)(?![\d.,])
        (?:\s*(?:°|deg|d)\s*|\s+|(?=[NSEWnsew]?\s*$))  # unambiguous end of degrees
        (?:(?P<m>\d+(?:[.,]\d+)?)\s*(?:'|′|m)\s*
           (?:(?P<s>\d+(?:[.,]\d+)?)\s*(?:"|″|'')?\s*)?  # a bare s is the south suffix, never a unit
        )?
        (?P<h2>[NSEWnsew])?\s*$""",
    re.VERBOSE,
)


class ConversionError(ValueError):
    """The file as a whole cannot be converted (e.g. no coordinate columns)."""


@dataclass
class RowError:
    row: int  # 1-based line where the record starts (header is line 1)
    reason: str
    values: dict = field(default_factory=dict)


@dataclass
class Result:
    geojson: dict
    errors: list
    lat_column: str
    lon_column: str


def _check_range(value: float, axis: str, text) -> float:
    limit = 90 if axis == "lat" else 180
    if not math.isfinite(value) or abs(value) > limit:
        raise ValueError(f"{axis} out of range [-{limit}, {limit}]: {value}")
    return value


def parse_coordinate(text, axis: str = "lat") -> float:
    """Parse one coordinate (decimal, decimal comma, hemisphere letter or DMS).

    text is a str, int or float; axis is "lat" or "lon" and limits the valid
    range and hemisphere letters. Raises ValueError when the value is not a
    valid coordinate and TypeError for unsupported input types.
    """
    if axis not in ("lat", "lon"):
        raise ValueError(f"axis must be 'lat' or 'lon', not {axis!r}")
    if text is None:
        raise ValueError("empty value")
    if isinstance(text, bool):
        raise TypeError("coordinate must be str, int or float, not bool")
    if isinstance(text, (int, float)):
        return _check_range(float(text), axis, text) + 0.0  # -0.0 -> 0.0
    if not isinstance(text, str):
        raise TypeError(f"coordinate must be str, int or float, not {type(text).__name__}")
    if not text.strip():
        raise ValueError("empty value")
    text = text.replace("−", "-")  # typographic minus (Wikipedia/spreadsheet exports)
    m = _DMS.match(text.replace(" ", " "))
    if not m:
        raise ValueError(f"not a coordinate: {text!r}")

    def num(g):
        return float(g.replace(",", ".")) if g else 0.0

    deg, minutes, seconds = num(m["d"]), num(m["m"]), num(m["s"])
    if minutes >= 60 or seconds >= 60:
        raise ValueError(f"minutes/seconds out of range: {text!r}")
    if (m["m"] and not deg.is_integer()) or (m["s"] and not minutes.is_integer()):
        raise ValueError(f"fractional degrees/minutes followed by smaller units: {text!r}")
    if m["h1"] and m["h2"]:
        raise ValueError(f"two hemisphere letters: {text!r}")
    hemi = (m["h1"] or m["h2"] or "").upper()
    allowed = "NS" if axis == "lat" else "EW"
    if hemi and hemi not in allowed:
        raise ValueError(f"hemisphere {hemi} invalid for {axis}: {text!r}")
    if m["sign"] and hemi:
        raise ValueError(f"sign combined with hemisphere letter: {text!r}")
    value = deg + minutes / 60 + seconds / 3600
    if m["sign"] == "-" or hemi in ("S", "W"):
        value = -value
    return _check_range(value, axis, text) + 0.0  # "-0" / "0 S" -> 0.0, not -0.0


def _check_header(fieldnames) -> list:
    if isinstance(fieldnames, (str, bytes, Mapping)) or fieldnames is None:
        raise TypeError("fieldnames must be a list or tuple of column names")
    names = list(fieldnames)
    for n in names:
        if not isinstance(n, str):
            raise TypeError(f"column names must be str, not {type(n).__name__}")
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise ConversionError(f"duplicate column names {dupes}; rename them so every column is unique")
    return names


def _find(names, candidates, axis, exclude=None):
    found = [n for n in names if n != exclude and n.strip().lower() in candidates]
    if len(found) > 1:
        raise ConversionError(
            f"ambiguous {axis} columns {found}; choose one explicitly (--{axis})")
    return found[0] if found else None


def detect_columns(fieldnames) -> tuple[str, str]:
    """Return (lat_column, lon_column) guessed from header names.

    Raises ConversionError if a column is missing, ambiguous or duplicated.
    """
    return _resolve(_check_header(fieldnames), None, None)


def _match_name(c, names, axis):
    """Return the header equal to c, else the single header equal ignoring case and padding."""
    if c in names:
        return c
    key = c.strip().casefold()
    loose = [n for n in names if n.strip().casefold() == key] if key else []
    if len(loose) == 1:
        return loose[0]
    if loose:
        raise ConversionError(f"{axis} column {c!r} matches several columns {loose}; use the exact name")
    raise ConversionError(f"{axis} column {c!r} not found in {names}")


def _resolve(names, lat, lon):
    if lat is not None:
        lat = _match_name(lat, names, "lat")
    if lon is not None:
        lon = _match_name(lon, names, "lon")
    if lat is None:
        lat = _find(names, LAT_NAMES, "lat", exclude=lon)
    if lon is None:
        lon = _find(names, LON_NAMES, "lon", exclude=lat)
    if lat is None or lon is None:
        raise ConversionError(
            f"could not detect latitude/longitude columns in {names}; "
            "name them explicitly (--lat/--lon)")
    if lat == lon:
        raise ConversionError(f"latitude and longitude must be different columns, both are {lat!r}")
    return lat, lon


def _sniff(header_line: str) -> str:
    """Pick the delimiter that occurs most often in the header line."""
    counts = {d: header_line.count(d) for d in ",;\t|"}
    best = max(counts, key=counts.get)
    return best if counts[best] else ","


def convert(text: str, lat: str | None = None, lon: str | None = None,
            delimiter: str | None = None) -> Result:
    """Convert CSV text to a GeoJSON FeatureCollection (WGS 84, [lon, lat] order).

    Rows whose coordinates cannot be parsed, or whose field count differs from
    the header, are skipped and listed in Result.errors. All other columns
    become feature properties (as strings).
    """
    if not isinstance(text, str):
        raise TypeError(f"text must be str, not {type(text).__name__}")
    for name, v in (("lat", lat), ("lon", lon)):
        if v is not None and not isinstance(v, str):
            raise TypeError(f"{name} must be a column name (str) or None")
    if delimiter is not None and (not isinstance(delimiter, str) or len(delimiter) != 1
                                  or delimiter in "\"\r\n"):
        raise ConversionError(f"delimiter must be a single character, not {delimiter!r}")
    text = text.lstrip("﻿")
    if not text.strip():
        raise ConversionError("empty CSV: no header row")
    delim = delimiter or _sniff(io.StringIO(text, newline="").readline())
    consumed = []  # physical lines read for the current record

    def lines():
        for physical in io.StringIO(text, newline=""):
            consumed.append(physical)
            yield physical

    reader = csv.reader(lines(), delimiter=delim, strict=True)
    try:
        names = _check_header(next(reader))
        consumed.clear()
        lat, lon = _resolve(names, lat, lon)
        features, errors = [], []
        for raw in reader:
            line = reader.line_num - len(consumed) + 1  # first line of the record
            n = len(raw)
            source = "".join(consumed)
            consumed.clear()
            if not source.strip() and delim not in source:
                continue  # physically blank line; quoted "" or a lone delimiter is a record
            row = dict(zip(names, raw))
            if n != len(names):
                extra = {"_extra": raw[len(names):]} if n > len(names) else {}
                kind = "too many" if n > len(names) else "too few"
                hint = "; unquoted delimiter?" if n > len(names) else ""
                errors.append(RowError(
                    line, f"{kind} fields ({n} for {len(names)} columns){hint}", {**row, **extra}))
                continue
            try:
                y = parse_coordinate(row[lat], "lat")
            except ValueError as e:
                errors.append(RowError(line, f"{lat}: {e}", row))
                continue
            try:
                x = parse_coordinate(row[lon], "lon")
            except ValueError as e:
                errors.append(RowError(line, f"{lon}: {e}", row))
                continue
            props = {k: v for k, v in row.items() if k not in (lat, lon)}
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [x, y]},
                "properties": props,
            })
    except csv.Error as e:
        raise ConversionError(f"malformed CSV near line {reader.line_num}: {e}") from e
    return Result({"type": "FeatureCollection", "features": features}, errors, lat, lon)


def convert_file(path, lat=None, lon=None, delimiter=None, encoding="utf-8-sig") -> Result:
    """Read a CSV file and convert it (see convert).

    The file is opened with newline="" so line endings inside quoted fields
    (CRLF, CR or LF) reach the properties unchanged, exactly as with convert().
    """
    if not isinstance(path, (str, os.PathLike)) or isinstance(path, bytes):
        raise TypeError(f"path must be str or os.PathLike, not {type(path).__name__}")
    if not isinstance(encoding, str):
        raise TypeError(f"encoding must be str, not {type(encoding).__name__}")
    with Path(path).open(encoding=encoding, newline="") as f:
        return convert(f.read(), lat, lon, delimiter)
