"""Sleep-model input windowing and int8 export (REQ-ML-03/04, REQ-FEAT-10)."""
import re
from pathlib import Path

import numpy as np
import pytest

from eegml import config
from eegml import sleep_model as sm

HEADER = Path(__file__).resolve().parents[1] / "firmware" / "eeg_node" / "sleep_model.h"


def test_stack_neighbours_order_and_start_padding():
    x = np.arange(4)[:, None] * np.ones((1, 2))          # rows 0,1,2,3
    s = sm.stack_neighbours(x, k=2)
    assert s.shape == (4, 6)
    # row t = [x[t], x[t-1], x[t-2]], earlier rows repeat x[0]
    np.testing.assert_array_equal(s[:, ::2], [[0, 0, 0], [1, 0, 0], [2, 1, 0], [3, 2, 1]])


def test_stack_neighbours_is_causal():
    x = np.random.default_rng(0).normal(size=(10, 3))
    full = sm.stack_neighbours(x)
    for t in range(10):  # input for epoch t must not change when later epochs are removed
        np.testing.assert_array_equal(sm.stack_neighbours(x[:t + 1])[t], full[t])


def test_sessions_do_not_leak_into_each_other():
    a, b = np.zeros((5, sm.N_FEATURES)), np.ones((5, sm.N_FEATURES))
    first_b = sm.stack_neighbours(b)[0]
    assert (first_b == 1).all()  # padding comes from b itself, never from a
    assert sm.stack_neighbours(a).shape == (5, sm.N_INPUT)


def test_standardise_and_sd_floor():
    rng = np.random.default_rng(1)
    x = rng.normal(5, 3, size=(500, 4))
    x[:, 3] = 7.0  # constant feature: must not divide by zero
    z, m, s = sm.standardise(x)
    np.testing.assert_allclose(z[:, :3].mean(0), 0, atol=1e-12)
    np.testing.assert_allclose(z[:, :3].std(0), 1, atol=1e-12)
    assert np.isfinite(z).all() and (z[:, 3] == 0).all()
    z2, _, _ = sm.standardise(x[:10], m, s)  # reuse calibration stats
    np.testing.assert_allclose(z2, z[:10])


def test_model_input_shape_clip_and_config():
    assert sm.NEIGHBOURS == config.SLEEP_NEIGHBOURS and sm.INPUT_CLIP == config.SLEEP_INPUT_CLIP
    x = np.random.default_rng(2).normal(size=(50, sm.N_FEATURES))
    x[10, 0] = 1e6
    xi = sm.model_input(x, mode="whole-night")
    assert xi.shape == (50, sm.N_INPUT) and xi.dtype == np.float32
    assert np.abs(xi).max() <= sm.INPUT_CLIP
    assert xi[10, 0] == sm.INPUT_CLIP and xi[11, sm.N_FEATURES] == sm.INPUT_CLIP  # lag-1 block


@pytest.fixture(scope="module")
def tiny():
    tf = pytest.importorskip("tensorflow")
    tf.keras.utils.set_random_seed(0)
    rng = np.random.default_rng(0)
    x = rng.normal(size=(300, sm.N_INPUT)).astype(np.float32)
    y = (x[:, 0] > 0).astype(int) + 2 * (x[:, 1] > 0)
    m = sm.build_model(hidden=(8,))
    m.fit(x, y, epochs=3, verbose=0)
    tfl = sm.to_int8(m, x[:100])
    return tfl, sm.Int8Runner(tfl), x


def test_export_round_trip(tiny):
    tfl, runner, x = tiny
    xq = runner.quantise(x[:1])
    yq = runner.predict_q(xq)
    text = sm.header_text(tfl, runner, {"w": (xq[0], yq[0], 0)}, ["W", "N1", "N2", "N3", "REM"], 4096)
    assert bytes(sm.parse_header_array(text, "g_sleep_model").astype(np.uint8)) == tfl
    np.testing.assert_array_equal(sm.parse_header_array(text, "g_sleep_in_w"), xq[0])
    np.testing.assert_array_equal(sm.parse_header_array(text, "g_sleep_out_w"), yq[0])
    assert f"#define SLEEP_MODEL_N_INPUT {sm.N_INPUT}" in text
    assert re.search(r"#define SLEEP_MODEL_INPUT_CLIP \d+\.\d+f", text)  # valid C float literal
    assert runner.inp["dtype"] == np.int8 and runner.out["dtype"] == np.int8
    assert sm.per_channel_tensors(tfl) == []  # the XIAO's TFLM needs per-tensor dense weights


@pytest.mark.skipif(not HEADER.exists(), reason="run scripts/train_sleep_model.py first")
def test_generated_header_runs_and_fits():
    pytest.importorskip("tensorflow")
    text = HEADER.read_text()
    tfl = bytes(sm.parse_header_array(text, "g_sleep_model").astype(np.uint8))
    assert len(tfl) <= 64 * 1024  # REQ-ML-04 flash
    arena = int(re.search(r"SLEEP_MODEL_ARENA_BYTES (\d+)", text).group(1))
    assert arena <= 32 * 1024     # REQ-ML-04 arena (estimate)
    r = sm.Int8Runner(tfl)
    assert list(r.inp["shape"]) == [1, sm.N_INPUT] and list(r.out["shape"]) == [1, 5]
    assert f"#define SLEEP_MODEL_FEATURE_SCHEMA {sm.FEATURE_SCHEMA_VERSION}" in text
    assert sm.per_channel_tensors(tfl) == []  # per-channel dense weights give wrong outputs on the XIAO
    for stage in ["w", "n1", "n2", "n3", "rem"]:  # embedded test epochs reproduce their outputs
        xq = sm.parse_header_array(text, f"g_sleep_in_{stage}").astype(np.int8)
        want = sm.parse_header_array(text, f"g_sleep_out_{stage}")
        np.testing.assert_array_equal(r.predict_q(xq[None])[0], want)


def test_running_standardise_matches_reference_definition():
    x = np.random.default_rng(3).normal(2, 5, size=(40, 6))
    z = sm.running_standardise(x, warmup=10)
    for t in range(40):
        w = x[:max(t + 1, 10)]
        np.testing.assert_allclose(z[t], (x[t] - w.mean(0)) / w.std(0), rtol=1e-10)


def test_running_standardise_short_session_and_config():
    x = np.random.default_rng(4).normal(size=(4, 3))  # shorter than the warm-up
    z = sm.running_standardise(x, warmup=10)
    np.testing.assert_allclose(z, (x - x.mean(0)) / x.std(0))
    assert sm.WARMUP == config.SLEEP_WARMUP_EPOCHS and config.SLEEP_STANDARDISE == "running"
    np.testing.assert_allclose(sm.model_input(x), sm.stack_neighbours(np.clip(z, -6, 6)).astype(np.float32))


def test_welford_in_float32_is_close_enough_for_the_device():
    # Real feature scale: log powers ~0-4, kurtosis up to ~50; a full night ~1000 epochs.
    x = np.random.default_rng(5).normal([2, 0.3, 10], [0.5, 0.1, 8], size=(1000, 3))
    z64 = sm.running_standardise(x)
    z32 = sm.running_standardise(x.astype(np.float32), dtype=np.float32)
    assert np.abs(z32 - z64).max() < 1e-3  # far below one int8 input step (~0.04)


def test_replay_parses_board_lines():
    import sys
    sys.path.insert(0, str(HEADER.parents[2] / "scripts"))
    import replay_night as rn
    feats, windows = np.full((3, 30), np.nan), np.zeros(3, int)
    out, names = np.zeros((3, 5), int), {}
    rn.parse_line("FEAT 1 29 " + " ".join(["0.5"] * 30), feats, windows, out, names)
    rn.parse_line("OUT 2 N2 -128 -100 90 -120 -128", feats, windows, out, names)
    assert windows[1] == 29 and (feats[1] == 0.5).all() and np.isnan(feats[0]).all()
    assert names[2] == "N2" and out[2].tolist() == [-128, -100, 90, -120, -128]
