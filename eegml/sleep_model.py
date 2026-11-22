"""Sleep-stage model input pipeline and int8 export (REQ-ML-03/04, REQ-FEAT-10).

The firmware must build the model input exactly as `model_input` does:
  1. standardise each of the 30 epoch features with the session's own mean/SD
     (REQ-FEAT-10; on the device these come from the calibration state),
  2. clip to +-INPUT_CLIP,
  3. concatenate [current, previous, previous-but-one] epochs (causal; at the
     start of a session the missing previous epochs repeat the first epoch).
"""
import numpy as np

from .config import SLEEP_INPUT_CLIP as INPUT_CLIP
from .config import SLEEP_NEIGHBOURS as NEIGHBOURS
from .config import SLEEP_SD_FLOOR as SD_FLOOR
from .epochs import EPOCH_FEATURE_NAMES

N_FEATURES = len(EPOCH_FEATURE_NAMES)    # 30
N_INPUT = N_FEATURES * (NEIGHBOURS + 1)  # 90
MODEL_VERSION = 1
FEATURE_SCHEMA_VERSION = 1               # = feature_vectors_v1 (tests/vectors)


def standardise(x: np.ndarray, mean=None, sd=None):
    """Per-session z-score. Returns (z, mean, sd); pass mean/sd to reuse calibration stats."""
    x = np.asarray(x, dtype=np.float64)
    mean = x.mean(0) if mean is None else np.asarray(mean)
    sd = x.std(0) if sd is None else np.asarray(sd)
    return (x - mean) / np.maximum(sd, SD_FLOOR), mean, sd


def stack_neighbours(x: np.ndarray, k: int = NEIGHBOURS) -> np.ndarray:
    """Row t -> [x[t], x[t-1], ..., x[t-k]] for one session in time order.

    Missing earlier epochs at the start repeat x[0]. Call per session so no
    epoch ever sees another session's data.
    """
    x = np.asarray(x)
    if not len(x):
        return x.reshape(0, x.shape[1] * (k + 1) if x.ndim == 2 else 0)
    parts = []
    for lag in range(k + 1):
        idx = np.maximum(np.arange(len(x)) - lag, 0)
        parts.append(x[idx])
    return np.concatenate(parts, axis=1)


def model_input(x_session: np.ndarray, mean=None, sd=None) -> np.ndarray:
    """Raw epoch features of one session (time order) -> float32 model input [n, N_INPUT]."""
    z, _, _ = standardise(x_session, mean, sd)
    return stack_neighbours(np.clip(z, -INPUT_CLIP, INPUT_CLIP)).astype(np.float32)


def build_model(n_input: int = N_INPUT, n_classes: int = 5, hidden=(32, 16), dropout: float = 0.2):
    import tensorflow as tf
    layers = [tf.keras.Input((n_input,))]
    for h in hidden:
        layers += [tf.keras.layers.Dense(h, activation="relu"), tf.keras.layers.Dropout(dropout)]
    layers.append(tf.keras.layers.Dense(n_classes, activation="softmax"))
    m = tf.keras.Sequential(layers)
    m.compile(tf.keras.optimizers.Adam(2e-3), "sparse_categorical_crossentropy", metrics=["accuracy"])
    return m


def to_int8(model, representative: np.ndarray) -> bytes:
    """Full-integer post-training quantisation; int8 input and output."""
    import tensorflow as tf
    conv = tf.lite.TFLiteConverter.from_keras_model(model)
    conv.optimizations = [tf.lite.Optimize.DEFAULT]
    rep = np.asarray(representative, dtype=np.float32)
    conv.representative_dataset = lambda: ([r[None]] for r in rep)
    conv.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    conv.inference_input_type = tf.int8
    conv.inference_output_type = tf.int8
    return conv.convert()


class Int8Runner:
    """Run an int8 .tflite on float inputs (quantise in, argmax out)."""

    def __init__(self, tflite: bytes):
        import tensorflow as tf
        self.interp = tf.lite.Interpreter(model_content=tflite)
        self.interp.allocate_tensors()
        self.inp = self.interp.get_input_details()[0]
        self.out = self.interp.get_output_details()[0]
        self.in_scale, self.in_zero = self.inp["quantization"]
        self.out_scale, self.out_zero = self.out["quantization"]

    def quantise(self, x: np.ndarray) -> np.ndarray:
        return np.clip(np.round(x / self.in_scale + self.in_zero), -128, 127).astype(np.int8)

    def predict_q(self, xq: np.ndarray) -> np.ndarray:
        """Raw int8 outputs for int8 inputs [n, N_INPUT]."""
        out = np.empty((len(xq), self.out["shape"][-1]), dtype=np.int8)
        for i, r in enumerate(xq):
            self.interp.set_tensor(self.inp["index"], r[None])
            self.interp.invoke()
            out[i] = self.interp.get_tensor(self.out["index"])[0]
        return out

    def predict(self, x: np.ndarray) -> np.ndarray:
        return self.predict_q(self.quantise(x)).argmax(1)


def _carr(name, ctype, data, align=False, per_line=24):
    vals = [str(int(v)) for v in data]
    lines = ",\n  ".join(",".join(vals[i:i + per_line]) for i in range(0, len(vals), per_line))
    a = "alignas(16) " if align else ""
    return f"{a}const {ctype} {name}[] = {{\n  {lines}\n}};\nconst unsigned int {name}_len = {len(vals)};\n"


def header_text(tflite: bytes, runner: "Int8Runner", samples: dict, stage_names, arena_bytes: int,
                source: str = "scripts/train_sleep_model.py") -> str:
    """C header with the model, its I/O quantisation, layout defines and test inputs.

    samples: {name: (int8 input[N_INPUT], expected int8 output[n_classes], label)}.
    """
    s = [f"// Generated by {source} -- do not edit",
         "#pragma once", "#include <stdint.h>", "",
         f"#define SLEEP_MODEL_VERSION {MODEL_VERSION}",
         f"#define SLEEP_MODEL_FEATURE_SCHEMA {FEATURE_SCHEMA_VERSION}",
         f"#define SLEEP_MODEL_N_FEATURES {N_FEATURES}",
         f"#define SLEEP_MODEL_NEIGHBOURS {NEIGHBOURS}  // input = [t, t-1, t-2] x features",
         f"#define SLEEP_MODEL_N_INPUT {N_INPUT}",
         f"#define SLEEP_MODEL_N_CLASSES {len(stage_names)}",
         f"#define SLEEP_MODEL_INPUT_CLIP {float(INPUT_CLIP)!r}f  // standardised units, before quantising",
         f"#define SLEEP_MODEL_INPUT_SCALE {runner.in_scale:.9g}f",
         f"#define SLEEP_MODEL_INPUT_ZERO_POINT {int(runner.in_zero)}",
         f"#define SLEEP_MODEL_OUTPUT_SCALE {runner.out_scale:.9g}f",
         f"#define SLEEP_MODEL_OUTPUT_ZERO_POINT {int(runner.out_zero)}",
         f"#define SLEEP_MODEL_ARENA_BYTES {arena_bytes}  // estimate; measure on the device (task 4b)",
         "static const char *const SLEEP_MODEL_STAGES[] = {" + ", ".join(f'"{n}"' for n in stage_names) + "};",
         "// Feature order within each block (REQ-FEAT-07):",
         "// " + ", ".join(EPOCH_FEATURE_NAMES), ""]
    body = "\n".join(s) + "\n" + _carr("g_sleep_model", "unsigned char", tflite, align=True)
    for name, (xq, yq, label) in samples.items():
        body += f"\n// test epoch: true stage {stage_names[label]}\n"
        body += _carr(f"g_sleep_in_{name}", "int8_t", xq)
        body += _carr(f"g_sleep_out_{name}", "int8_t", yq)
    return body


def parse_header_array(text: str, name: str) -> np.ndarray:
    """Read back an integer array written by header_text (for tests)."""
    import re
    m = re.search(rf"\b{name}\[\] = \{{(.*?)\}};", text, re.S)
    if not m:
        raise KeyError(name)
    return np.array([int(v) for v in m.group(1).replace("\n", "").split(",") if v.strip()])
