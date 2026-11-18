import json
import os
from pathlib import Path

NB = Path(__file__).resolve().parent.parent / "examples" / "demo.ipynb"


def test_notebook_runs():
    nb = json.loads(NB.read_text(encoding="utf-8"))
    assert nb["nbformat"] == 4
    code = [c for c in nb["cells"] if c["cell_type"] == "code"]
    assert code
    for c in code:
        assert c["outputs"] == [] and c["execution_count"] is None
    old = os.getcwd()
    os.chdir(NB.parent.parent)  # notebook paths are relative to the repo root
    try:
        ns = {"__name__": "__notebook__"}
        for c in code:
            exec("".join(c["source"]), ns)
    finally:
        os.chdir(old)
    assert len(ns["result"].geojson["features"]) == 8
