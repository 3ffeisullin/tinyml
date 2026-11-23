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


def test_node_firmware_headers_are_current_and_compile_clean():
    """The eeg_node copies are what the exporter writes now; float literals are valid C."""
    import re
    assert etv.H_NODE_COPY.read_text() == etv.H_OUT.read_text()
    assert etv.CONFIG_H.read_text() == etv.config_header()
    for path in (etv.H_OUT, etv.H_NODE_COPY, etv.CONFIG_H):
        # '1f' is not a C float literal ('1.0f' is); it slipped into v1 unnoticed.
        bad = [m for m in re.findall(r"(?<![\w.])(\d[\d.eE+-]*)f\b", path.read_text())
               if not any(c in m for c in ".eE")]
        assert not bad, (path, bad[:3])


def test_config_header_matches_python_config():
    from eegml import config, filters
    h = etv.CONFIG_H.read_text()
    assert f"#define EEG_WIN {int(config.WIN_S * config.FS)}" in h
    assert f"#define EEG_NFFT {config.NFFT}" in h
    assert f"#define EEG_N_BANDS {len(config.BANDS)}" in h
    sos = filters.design_sos(config.FilterSpec(line_freq=60.0))
    vals = [float(v) for v in h.split("EEG_SOS_60[30] = {")[1].split("}")[0].split(",")]
    assert vals == sos.ravel().tolist()  # bit-exact doubles
