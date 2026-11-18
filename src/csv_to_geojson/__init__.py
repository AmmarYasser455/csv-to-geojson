"""Convert CSV files with coordinates to GeoJSON."""

from .core import (
    ConversionError,
    Result,
    RowError,
    convert,
    convert_file,
    detect_columns,
    parse_coordinate,
)

__all__ = [
    "ConversionError",
    "Result",
    "RowError",
    "convert",
    "convert_file",
    "detect_columns",
    "parse_coordinate",
]
__version__ = "0.1.0"
