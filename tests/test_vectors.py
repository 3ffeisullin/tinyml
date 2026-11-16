"""REQ-FEAT-09: stored firmware test vectors match the current Python pipeline."""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import export_test_vectors as etv  # noqa: E402


def test_vectors_are_current():
    stored = json.loads(etv.JSON_OUT.read_text())
    fresh = etv.build()
    assert stored["feature_names"] == fresh["feature_names"]
    np.testing.assert_allclose(stored["sos"], fresh["sos"], rtol=1e-12)
    np.testing.assert_allclose(stored["filtered_uv"], fresh["filtered_uv"], rtol=1e-9, atol=1e-9)
    np.testing.assert_allclose(stored["features"], fresh["features"], rtol=1e-9, atol=1e-9)


def test_header_exists_and_sized():
    h = etv.H_OUT.read_text()
    assert "#define TV_N_WINDOWS 11" in h and "#define TV_N_FEATURES 20" in h
