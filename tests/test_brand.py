import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

BRAND = Path(__file__).resolve().parent.parent / "assets" / "brand"
ALLOWED = {
    "logo.svg": {"#121417", "#f2552c"},
    "logo-dark.svg": {"#f3eee4", "#f2552c"},
}


@pytest.mark.parametrize("name", sorted(ALLOWED))
def test_logo(name):
    path = BRAND / name
    assert path.is_file()
    root = ET.parse(path).getroot()
    assert root.get("viewBox") == "0 0 100 100"
    assert root.get("width") == "100" and root.get("height") == "100"
    colours = {c.lower() for c in re.findall(r"#[0-9a-fA-F]{3,8}\b", path.read_text())}
    assert colours == ALLOWED[name]
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        assert tag in {"svg", "rect", "circle", "path"}
        assert "opacity" not in el.attrib and "stroke" not in el.attrib
