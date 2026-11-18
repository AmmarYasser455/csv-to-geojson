import importlib.util
import json
import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SHOWCASE = ROOT / "showcase"


def _load():
    spec = importlib.util.spec_from_file_location("make_showcase", SHOWCASE / "make_showcase.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_map_geojson_not_stale(tmp_path):
    ms = _load()
    ms.build(out_dir=tmp_path, png=False)
    fresh = (tmp_path / "map.geojson").read_text(encoding="utf-8")
    committed = (SHOWCASE / "map.geojson").read_text(encoding="utf-8")
    assert fresh == committed
    assert (tmp_path / "index.html").read_text(encoding="utf-8") == (
        SHOWCASE / "index.html").read_text(encoding="utf-8")


def test_png_is_produced(tmp_path):
    pytest.importorskip("matplotlib")
    _load().build(out_dir=tmp_path, png=True)
    png = tmp_path / "map.png"
    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_geojson_is_lonlat_and_plausible():
    gj = json.loads((SHOWCASE / "map.geojson").read_text(encoding="utf-8"))
    stations = [f for f in gj["features"] if f["properties"]["feature_type"] == "station"]
    sadat = next(f for f in stations if f["properties"]["name"] == "Sadat")
    lon, lat = sadat["geometry"]["coordinates"]
    assert 31.2 < lon < 31.3 and 30.0 < lat < 30.1  # Cairo: lon first, lat second
    ring = next(f for f in gj["features"] if f["properties"]["feature_type"] == "radius")
    pts = ring["geometry"]["coordinates"][0]
    assert pts[0] == pts[-1]
    area2 = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:]))
    assert area2 > 0  # counter-clockwise exterior ring (RFC 7946)


def test_distance_known_values():
    ms = _load()
    # Cairo (31.2357 E, 30.0444 N) to Alexandria (29.9187 E, 31.2001 N): about 179 km.
    assert ms.distance_km(31.2357, 30.0444, 29.9187, 31.2001) == pytest.approx(179, abs=2)
    # One degree of latitude is about 111.2 km; one degree of longitude at 30 N about 96.3 km.
    assert ms.distance_km(31.0, 30.0, 31.0, 31.0) == pytest.approx(111.2, abs=0.3)
    assert ms.distance_km(31.0, 30.0, 32.0, 30.0) == pytest.approx(96.3, abs=0.3)


def test_circle_ring_radius():
    ms = _load()
    ring = ms.circle_ring(31.2354, 30.0439, 5.0)
    for lon, lat in ring:
        assert ms.distance_km(31.2354, 30.0439, lon, lat) == pytest.approx(5.0, abs=0.01)
    assert math.isclose(ring[0][0], ring[-1][0]) and math.isclose(ring[0][1], ring[-1][1])


def test_notebook_executes_from_showcase_dir():
    nbformat = pytest.importorskip("nbformat")
    nbclient = pytest.importorskip("nbclient")
    pytest.importorskip("ipykernel")
    pytest.importorskip("matplotlib")
    nb = nbformat.read(SHOWCASE / "showcase.ipynb", as_version=4)
    # same working directory as `jupyter nbconvert` on showcase/showcase.ipynb
    nbclient.NotebookClient(nb, timeout=120, resources={"metadata": {"path": str(SHOWCASE)}}).execute()
    outputs = [o for c in nb.cells if c.cell_type == "code" for o in c.outputs]
    assert not [o for o in outputs if o.output_type == "error"]
    assert any(o.output_type in ("display_data", "execute_result") and "image/png" in o.data
               for o in outputs)
