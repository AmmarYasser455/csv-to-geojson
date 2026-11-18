import json
from pathlib import Path

import pytest

from csv_to_geojson import convert_file

ROOT = Path(__file__).resolve().parent.parent


def _by_city():
    res = convert_file(ROOT / "examples" / "cities.csv")
    assert res.errors == []
    return res, {f["properties"]["city"]: f["geometry"]["coordinates"]
                 for f in res.geojson["features"]}


def test_known_cities():
    res, cities = _by_city()
    assert len(cities) == 8
    # known real locations, GeoJSON order [lon, lat]
    assert cities["Cairo"] == pytest.approx([31.24, 30.04], abs=0.05)
    assert cities["London"] == pytest.approx([-0.13, 51.51], abs=0.05)
    assert cities["Sydney"] == pytest.approx([151.21, -33.87], abs=0.05)
    assert cities["Rio de Janeiro"] == pytest.approx([-43.17, -22.91], abs=0.05)
    assert cities["Tokyo"][0] > 0 and cities["Tokyo"][1] > 0
    assert cities["Auckland"][1] < 0 < cities["Auckland"][0]
    assert cities["Nairobi"][1] == pytest.approx(-1.29, abs=0.05)  # just south of equator


def test_demo_geojson_is_current():
    res = convert_file(ROOT / "examples" / "cities.csv")
    demo = json.loads((ROOT / "docs" / "demo.geojson").read_text(encoding="utf-8"))
    assert demo == res.geojson
