import json

import pytest

from csv_to_geojson import ConversionError, convert, detect_columns, parse_coordinate
from csv_to_geojson.core import convert_file
from csv_to_geojson.cli import main


def test_zero_is_never_negative_zero():
    import math
    for text, axis in (("-0", "lat"), ("0 S", "lat"), ("W 0", "lon"), ("-0°0'0\"", "lon"), (-0.0, "lat")):
        assert math.copysign(1.0, parse_coordinate(text, axis)) == 1.0
    r = convert("name,lat,lon\nGreenwich,51.4769,-0\n")
    assert r.geojson["features"][0]["geometry"]["coordinates"] == [0.0, 51.4769]
    assert "-0.0" not in json.dumps(r.geojson)


def test_unicode_minus_sign():
    # Wikipedia-style U+2212 minus: Buenos Aires is 34.6037 S, 58.3816 W
    assert parse_coordinate("−34.6037", "lat") == pytest.approx(-34.6037)
    r = convert("city,lat,lon\nBuenos Aires,−34.6037,−58.3816\n")
    assert not r.errors
    assert r.geojson["features"][0]["geometry"]["coordinates"] == [-58.3816, -34.6037]
    with pytest.raises(ValueError):  # still rejected with a hemisphere letter
        parse_coordinate("−30 N", "lat")


def test_parse_formats():
    assert parse_coordinate("30.0444") == pytest.approx(30.0444)
    assert parse_coordinate("30,0444") == pytest.approx(30.0444)
    assert parse_coordinate("33.8688 S") == pytest.approx(-33.8688)
    assert parse_coordinate("W 0.1278", "lon") == pytest.approx(-0.1278)
    assert parse_coordinate("""30°02'39.8"N""") == pytest.approx(30.0444, abs=1e-4)
    assert parse_coordinate("""31°14'08"E""", "lon") == pytest.approx(31.2356, abs=1e-4)


@pytest.mark.parametrize("bad,axis", [
    ("", "lat"), ("abc", "lat"), ("91", "lat"), ("181", "lon"), ("nan", "lat"),
    ("10 E", "lat"), ("10 N", "lon"), ("10°75'N", "lat"),
])
def test_parse_rejects(bad, axis):
    with pytest.raises(ValueError):
        parse_coordinate(bad, axis)


def test_axis_order_is_lon_lat():
    # Cairo: lat 30.04 N, lon 31.24 E -> GeoJSON [lon, lat]
    res = convert("name,lat,lng\nCairo,30.0444,31.2357\n")
    assert res.geojson["features"][0]["geometry"]["coordinates"] == [31.2357, 30.0444]
    assert (res.lat_column, res.lon_column) == ("lat", "lng")


def test_negative_hemispheres_not_swapped():
    res = convert("Latitude,Longitude\n-33.8688,151.2093\n51.5074,-0.1278\n")
    assert res.geojson["features"][0]["geometry"]["coordinates"] == [151.2093, -33.8688]
    assert res.geojson["features"][1]["geometry"]["coordinates"] == [-0.1278, 51.5074]


def test_bad_rows_reported_with_line_numbers():
    text = "id,lat,lon\na,10,20\nb,abc,20\nc,95,20\nd,10,\n\ne,11,21\n"
    res = convert(text)
    assert [f["properties"]["id"] for f in res.geojson["features"]] == ["a", "e"]
    assert [e.row for e in res.errors] == [3, 4, 5]
    assert "lat" in res.errors[0].reason and "out of range" in res.errors[1].reason


def test_semicolon_decimal_comma_and_bom():
    res = convert("﻿name;lat;lon\nRio;-22,9068;-43,1729\n")
    assert res.geojson["features"][0]["geometry"]["coordinates"] == [-43.1729, -22.9068]


def test_quoted_fields_and_attributes_kept():
    res = convert('name,x,y,note\n"Paris, FR",2.3522,48.8566,"a ""b"""\n')
    assert res.geojson["features"][0]["properties"] == {"name": "Paris, FR", "note": 'a "b"'}


def test_errors_without_columns_or_empty():
    with pytest.raises(ConversionError):
        convert("a,b\n1,2\n")
    with pytest.raises(ConversionError):
        convert("")
    with pytest.raises(ConversionError):
        convert("a,b\n1,2\n", lat="zz", lon="b")
    assert convert("lat,lon\n").geojson["features"] == []


def test_explicit_columns_and_detect():
    assert detect_columns(["ID", " Latitude ", "LONG"]) == (" Latitude ", "LONG")
    res = convert("p,q,r\n1,10,20\n", lat="q", lon="r")
    assert res.geojson["features"][0]["properties"] == {"p": "1"}


def test_cli(tmp_path, capsys):
    src = tmp_path / "in.csv"
    src.write_text("lat,lon\n10,20\nx,y\n", encoding="utf-8")
    out = tmp_path / "out.geojson"
    assert main([str(src), "-o", str(out)]) == 0
    assert len(json.loads(out.read_text(encoding="utf-8"))["features"]) == 1
    assert "line 3" in capsys.readouterr().err
    assert main([str(src), "-o", str(out), "--strict"]) == 1
    assert main([str(tmp_path / "missing.csv")]) == 2


def test_extra_fields_reported_not_silently_dropped():
    res = convert("lat,lon\n30,04,31,24\n")
    assert res.geojson["features"] == []
    assert len(res.errors) == 1 and "too many fields" in res.errors[0].reason


@pytest.mark.parametrize("text,axis", [("-30 N", "lat"), ("-31 E", "lon"), ("+30 S", "lat")])
def test_sign_hemisphere_conflict_rejected(text, axis):
    with pytest.raises(ValueError):
        parse_coordinate(text, axis)


def test_single_column_override(tmp_path):
    res = convert("northing,lon\n30,31\n", lat="northing")
    assert res.geojson["features"][0]["geometry"]["coordinates"] == [31.0, 30.0]
    res = convert("lat,easting\n30,31\n", lon="easting")
    assert res.geojson["features"][0]["geometry"]["coordinates"] == [31.0, 30.0]
    f = tmp_path / "a.csv"
    f.write_text("northing,lon\n30,31\n", encoding="utf-8")
    assert main([str(f), "--lat", "northing", "-o", str(tmp_path / "o.json")]) == 0


def test_override_never_reused_for_other_axis():
    # Cairo 30.04 N, 31.24 E; the explicit column must not be auto-picked again.
    res = convert("lon,longitude\n30.0444,31.2357\n", lat="lon")
    assert res.geojson["features"][0]["geometry"]["coordinates"] == [31.2357, 30.0444]
    res = convert("lat,latitude\n31.2357,30.0444\n", lon="lat")
    assert res.geojson["features"][0]["geometry"]["coordinates"] == [31.2357, 30.0444]
    with pytest.raises(ConversionError, match="different columns"):
        convert("a,b\n1,2\n", lat="a", lon="a")


@pytest.mark.parametrize("text", [
    "lat,lon,lat\n30,31,40\n",        # duplicate coordinate header
    "name,lat,lon,name\na,30,31,b\n",  # duplicate property header
    "lat,latitude,lon\n30,31,32\n",   # two latitude candidates
    "x,y,lat,lon\n1,2,30,31\n",       # projected x/y next to lat/lon
])
def test_duplicate_or_ambiguous_headers_rejected(text):
    with pytest.raises(ConversionError):
        convert(text)


def test_blank_looking_rows_with_overflow_reported(tmp_path):
    res = convert("lat,lon\n,,30,31\n30,\n")
    assert res.geojson["features"] == []
    assert [e.row for e in res.errors] == [2, 3]
    assert "too many fields" in res.errors[0].reason
    assert "lon: empty value" in res.errors[1].reason
    short = convert("id,lat,lon\na,30\n")
    assert "too few fields" in short.errors[0].reason
    f = tmp_path / "o.csv"
    f.write_text("lat,lon\n,,30,31\n", encoding="utf-8")
    assert main([str(f), "--strict", "-o", str(tmp_path / "o.json")]) == 1


@pytest.mark.parametrize("call,exc", [
    # parse_coordinate: null, empty, wrong types, NaN/inf, mappings, bad axis
    (lambda: parse_coordinate(None), ValueError),
    (lambda: parse_coordinate("   "), ValueError),
    (lambda: parse_coordinate(float("nan")), ValueError),
    (lambda: parse_coordinate(float("inf"), "lon"), ValueError),
    (lambda: parse_coordinate(True), TypeError),
    (lambda: parse_coordinate({"lat": 1}), TypeError),
    (lambda: parse_coordinate(["30"]), TypeError),
    (lambda: parse_coordinate(b"30"), TypeError),
    (lambda: parse_coordinate("30", "north"), ValueError),
    (lambda: parse_coordinate("inf"), ValueError),
    (lambda: parse_coordinate("1" * 400), ValueError),
    (lambda: parse_coordinate("30 45"), ValueError),        # ambiguous bare numbers
    (lambda: parse_coordinate("30.5°15'"), ValueError),     # fractional deg + minutes
    (lambda: parse_coordinate("45′"), ValueError),          # minutes only: never 4°5′
    (lambda: parse_coordinate("45'"), ValueError),
    (lambda: parse_coordinate('45"'), ValueError),          # seconds only
    (lambda: parse_coordinate("45′ N"), ValueError),
    (lambda: parse_coordinate("123′", "lon"), ValueError),  # never 12°3′ or 1°23′
    (lambda: parse_coordinate("12 30"), ValueError),        # no minute mark
    (lambda: convert('lat,lon,name\n30,31,"Cairo\n10,20,Other\n'), ConversionError),
    (lambda: convert('lat,lon,name\n30,31,"Cairo"x\n'), ConversionError),
    # convert: wrong types, empty, bad delimiter, bad column names
    (lambda: convert(None), TypeError),
    (lambda: convert(b"lat,lon\n1,2\n"), TypeError),
    (lambda: convert({"lat": 1, "lon": 2}), TypeError),
    (lambda: convert("﻿ \n"), ConversionError),
    (lambda: convert("lat,lon\n1,2\n", lat=1), TypeError),
    (lambda: convert("lat,lon\n1,2\n", lon=["lon"]), TypeError),
    (lambda: convert("lat,lon\n1,2\n", lat=""), ConversionError),
    (lambda: convert("lat,lon\n1,2\n", delimiter=""), ConversionError),
    (lambda: convert("lat,lon\n1,2\n", delimiter=",;"), ConversionError),
    (lambda: convert("lat,lon\n1,2\n", delimiter=5), ConversionError),
    # detect_columns: str, mapping, None, non-str names, duplicates
    (lambda: detect_columns("lat,lon"), TypeError),
    (lambda: detect_columns({"lat": 0, "lon": 1}), TypeError),
    (lambda: detect_columns(None), TypeError),
    (lambda: detect_columns(["lat", 2]), TypeError),
    (lambda: detect_columns(["lat", "lon", "lon"]), ConversionError),
    # convert_file: null, bytes, wrong-type path or encoding
    (lambda: convert_file(None), TypeError),
    (lambda: convert_file(b"x.csv"), TypeError),
    (lambda: convert_file(5), TypeError),
    (lambda: convert_file({"path": "x.csv"}), TypeError),
    (lambda: convert_file("x.csv", encoding=None), TypeError),
])
def test_boundary_inputs_rejected(call, exc):
    with pytest.raises(exc):
        call()


def test_dms_unit_boundaries():
    assert parse_coordinate("0°45′") == pytest.approx(0.75)
    assert parse_coordinate("0 45' N") == pytest.approx(0.75)
    assert parse_coordinate("4d5m") == pytest.approx(4 + 5 / 60)
    assert parse_coordinate("40 26' 46\" N") == pytest.approx(40.446111, abs=1e-6)
    assert parse_coordinate("30,5") == pytest.approx(30.5)  # decimal comma, not 30°5′


def test_empty_field_records_reported_not_skipped(tmp_path):
    # "," is a record with two empty fields; "" and "  " are blank lines.
    res = convert("lat,lon\n,\n\n30.0444,31.2357\n  \n")
    assert [e.row for e in res.errors] == [2]
    assert "lat: empty value" in res.errors[0].reason
    assert len(res.geojson["features"]) == 1
    f = tmp_path / "e.csv"
    f.write_text("lat,lon\n,\n", encoding="utf-8")
    assert main([str(f), "--strict", "-o", str(tmp_path / "e.json")]) == 1


@pytest.mark.parametrize("body,delimiter,error_rows,reason", [
    # Only physically blank lines are skipped; every other record is reported.
    ('""\n', None, [2], "too few fields"),               # quoted empty record
    ('" "\n', None, [2], "too few fields"),              # quoted whitespace record
    ('""\n\n30,31\n', None, [2], "too few fields"),
    ('"",""\n', None, [2], "lat: empty value"),          # two quoted empty fields
    (',\n', None, [2], "lat: empty value"),              # lone delimiter
    (' , \n', None, [2], "lat: empty value"),
    ('\t\n', "\t", [2], "lat: empty value"),             # lone tab with tab delimiter
    ('"\n"\n', None, [2], "too few fields"),             # quoted newline only
    ('\n', None, [], None),                              # blank lines
    ('   \n\r\n\n', None, [], None),
    ('\n\n30,31\n\n', None, [], None),
])
def test_blank_versus_empty_records(tmp_path, body, delimiter, error_rows, reason):
    text = ("lat\tlon\n" if delimiter == "\t" else "lat,lon\n") + body
    res = convert(text, delimiter=delimiter)
    assert [e.row for e in res.errors] == error_rows
    if reason:
        assert reason in res.errors[0].reason
    f = tmp_path / "b.csv"
    f.write_text(text, encoding="utf-8", newline="")
    args = [str(f), "--strict", "-o", str(tmp_path / "b.json")]
    if delimiter:
        args += ["--delimiter", "tab"]
    assert main(args) == (1 if error_rows else 0)


@pytest.mark.parametrize("text,expected", [
    ("33°52'7.68S", -33.8688),
    ("33°52'7.68s", -33.8688),
    ("33°52'7.68\"S", -33.8688),
    ("33°52'7.68\"", 33.8688),
])
def test_lowercase_s_is_south_not_seconds(text, expected):
    assert parse_coordinate(text, "lat") == pytest.approx(expected, abs=1e-4)


@pytest.mark.parametrize("target", ["missing/dir/out.json", ""])
def test_cli_unwritable_output_status_2(tmp_path, capsys, target):
    src = tmp_path / "a.csv"
    src.write_text("lat,lon\n30,31\n", encoding="utf-8")
    out = str(tmp_path / target)  # "" -> the directory itself
    assert main([str(src), "-o", out, "--strict"]) == 2
    assert "error:" in capsys.readouterr().err


def test_cli_unknown_encoding_status_2(tmp_path, capsys):
    src = tmp_path / "a.csv"
    src.write_text("lat,lon\n30,31\n", encoding="utf-8")
    assert main([str(src), "--encoding", "nope"]) == 2
    assert "error:" in capsys.readouterr().err


def test_unterminated_quote_is_an_error(tmp_path, capsys):
    f = tmp_path / "q.csv"
    f.write_text('lat,lon,name\n30,31,"Cairo\n10,20,Other\n', encoding="utf-8")
    assert main([str(f), "-o", str(tmp_path / "q.json")]) == 2
    assert "malformed CSV" in capsys.readouterr().err


def test_numeric_inputs_and_tab_delimiter(tmp_path):
    assert parse_coordinate(30) == 30.0
    assert parse_coordinate(1e-7, "lon") == 1e-7
    f = tmp_path / "t.tsv"
    f.write_text("name\tlat\tlon\nCairo\t30.0444\t31.2357\n", encoding="utf-8")
    out = tmp_path / "t.json"
    assert main([str(f), "--delimiter", "tab", "-o", str(out)]) == 0
    feat = json.loads(out.read_text(encoding="utf-8"))["features"][0]
    assert feat["geometry"]["coordinates"] == [31.2357, 30.0444]


@pytest.mark.parametrize("eol", ["\r\n", "\n", "\r"])
@pytest.mark.parametrize("inner", ["a\r\nb", "a\rb", "a\nb"])
def test_embedded_newlines_preserved_in_file_and_text(tmp_path, eol, inner):
    text = f'lat,lon,note{eol}30.0444,31.2357,"{inner}"{eol}'
    f = tmp_path / "nl.csv"
    f.write_bytes(text.encode("utf-8"))
    from_text, from_file = convert(text), convert_file(f)
    assert from_file.geojson == from_text.geojson
    assert from_file.errors == from_text.errors == []
    feat = from_file.geojson["features"][0]
    assert feat["properties"]["note"] == inner
    assert feat["geometry"]["coordinates"] == [31.2357, 30.0444]
    out = tmp_path / "nl.json"
    assert main([str(f), "-o", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["features"][0]["properties"]["note"] == inner


def test_cli_rejects_file(tmp_path):
    src = tmp_path / "in.csv"
    src.write_text("name,lat,lon\nCairo,30.0444,31.2357\nBad,95,10\nSydney,-33.8688,151.2093\n",
                   encoding="utf-8")
    rej = tmp_path / "rej.json"
    assert main([str(src), "-o", str(tmp_path / "o.geojson"), "--rejects", str(rej)]) == 0
    assert json.loads(rej.read_text(encoding="utf-8")) == [
        {"line": 3, "reason": "lat: lat out of range [-90, 90]: 95.0",
         "values": {"name": "Bad", "lat": "95", "lon": "10"}}]
    ok = tmp_path / "ok.csv"
    ok.write_text("lat,lon\n30.0444,31.2357\n", encoding="utf-8")
    assert main([str(ok), "-o", str(tmp_path / "o2.geojson"), "--rejects", str(rej)]) == 0
    assert json.loads(rej.read_text(encoding="utf-8")) == []
    assert main([str(src), "-o", str(tmp_path / "o3.geojson"),
                 "--rejects", str(tmp_path / "nodir" / "r.json")]) == 2


def test_cli_rejects_path_collisions(tmp_path):
    src = tmp_path / "in.csv"
    text = "name,lat,lon\nCairo,30.0444,31.2357\nBad,95,10\n"
    src.write_text(text, encoding="utf-8")
    out = tmp_path / "o.geojson"
    out.write_text("keep", encoding="utf-8")
    assert main([str(src), "-o", str(out), "--rejects", str(out)]) == 2
    assert main([str(src), "-o", str(out), "--rejects", str(tmp_path / "." / "o.geojson")]) == 2
    assert main([str(src), "-o", str(out), "--rejects", str(src)]) == 2
    assert main([str(src), "--rejects", str(src)]) == 2
    link = tmp_path / "link.json"
    link.symlink_to(src)
    assert main([str(src), "-o", str(out), "--rejects", str(link)]) == 2
    hard = tmp_path / "hard.json"
    hard.hardlink_to(out)
    assert main([str(src), "-o", str(out), "--rejects", str(hard)]) == 2
    assert src.read_text(encoding="utf-8") == text
    assert out.read_text(encoding="utf-8") == "keep"
