// eeg_node, stage 2 on the XIAO ESP32-S3: on-device checks before any sensor is wired.
//
// 1. Feature parity (task 6, REQ-FEAT-09): run the filter chain and window features from
//    eeg_features.h on the reference signal in feature_vectors_v1.h and compare with Python:
//      filtered samples: max |error| <= 1e-3 x max |reference|
//      log powers: |error| <= 0.01; other features: |error| <= 1e-3 x |reference| + 1e-6
//    Run twice: features from Python's filtered samples (feature code alone), and from the
//    board's own filter output (the whole chain).
// 2. Sleep-model bench (task 4b, REQ-ML-04, REQ-ML-06): the int8 model from sleep_model.h on
//    its embedded test epochs: parity with Python, microseconds per inference, arena used.
// 3. Replay (task 6b): the laptop (scripts/replay_night.py) streams a recorded night, one 30 s
//    epoch at a time, and the board runs the whole chain on it: filters -> window features ->
//    epoch summaries -> running standardisation -> [t, t-1, t-2] -> int8 model -> stage.
//    Serial protocol (115200 baud is ignored by USB CDC), one command per line:
//      BEGIN <mains Hz>        start a session (50 for Sleep-EDF)  -> "OK BEGIN"
//      EPOCH + 7500 float32 LE raw samples (uV), sent in 4096-byte chunks, each answered
//                              with "C" (flow control)              -> "FEAT e f0..f29",
//                              any "OUT t stage q0..q4" now ready, then "ACK e <us>"
//      END                     flush a session shorter than the warm-up -> "DONE <epochs>"
//      TEST                    re-run checks 1 and 2
// Self-tests run at boot and end with "READY". No sensor or electrodes are needed.
#include <Chirale_TensorFlowLite.h>
#include "eeg_config.h"
#include "eeg_features.h"
#include "eeg_pipeline.h"
#include "feature_vectors_v1.h"
#include "sleep_model.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/schema/schema_generated.h"

// REQ-ML-06: the feature schema this firmware produces. Refuse a model built for another.
constexpr int kFeatureSchema = 1;
constexpr int kTimingRuns = 200;
constexpr float kLineFreq = 60.0f;  // the reference vectors use the 60 Hz chain
static_assert(TV_N_FEATURES == EEG_N_FEATURES, "vectors and firmware disagree on the feature count");
static_assert(TV_N_SOS == EEG_N_SOS_60, "vectors and firmware disagree on the filter chain");

// ---------------- feature parity ----------------
eeg::BiquadCascade chain;
eeg::WindowFeatures features;
float dev_filtered[TV_N_SAMPLES];
const char* const kFeatureNames[EEG_N_FEATURES] = {
  "logp_delta", "logp_theta", "logp_alpha", "logp_sigma", "logp_beta", "logp_gamma",
  "rel_delta", "rel_theta", "rel_alpha", "rel_sigma", "rel_beta", "rel_gamma",
  "ratio_delta_beta", "ratio_alpha_beta", "ratio_theta_alpha", "skew", "kurtosis",
  "q_ptp_uv", "q_line_ratio", "q_clip_frac"};

struct ParityResult { bool ok; float filt_err_rel; int bad_features; float worst_ratio; uint32_t us_sample, us_window; };

// Feature error as a fraction of its tolerance (<= 1 passes).
float tolerance_ratio(int f, float got, float want) {
  const float err = fabsf(got - want);
  const float tol = f < EEG_N_BANDS ? 0.01f : 1e-3f * fabsf(want) + 1e-6f;
  return err / tol;
}

ParityResult feature_parity(bool verbose) {
  ParityResult r = {true, 0, 0, 0, 0, 0};
  // Filters: same coefficients as Python (eeg_config.h) and as the vectors.
  for (int i = 0; i < 6 * EEG_N_SOS_60; i++)
    if ((float)EEG_SOS_60[i] != tv_sos[i]) { Serial.println("SOS in eeg_config.h differs from the vectors"); r.ok = false; }
  chain.init(EEG_SOS_60, EEG_N_SOS_60);
  uint32_t t0 = micros();
  for (int n = 0; n < TV_N_SAMPLES; n++) dev_filtered[n] = chain.process(tv_raw_uv[n]);
  r.us_sample = (micros() - t0 + TV_N_SAMPLES / 2) / TV_N_SAMPLES;
  float max_ref = 0, max_err = 0;
  for (int n = 0; n < TV_N_SAMPLES; n++) {
    max_ref = fmaxf(max_ref, fabsf(tv_filtered_uv[n]));
    max_err = fmaxf(max_err, fabsf(dev_filtered[n] - tv_filtered_uv[n]));
  }
  r.filt_err_rel = max_err / max_ref;
  if (r.filt_err_rel > 1e-3f) r.ok = false;

  // Window features, from Python's filtered samples (pass 0) and from the board's (pass 1).
  float worst[2][EEG_N_FEATURES] = {};
  float out[EEG_N_FEATURES];
  uint32_t t_feat = 0;
  for (int pass = 0; pass < 2; pass++) {
    const float* filt = pass == 0 ? tv_filtered_uv : dev_filtered;
    for (int w = 0; w < TV_N_WINDOWS; w++) {
      const int s = w * EEG_HOP;
      t0 = micros();
      features.compute(filt + s, tv_raw_uv + s, kLineFreq, 0.0f, out);
      t_feat += micros() - t0;
      for (int f = 0; f < EEG_N_FEATURES; f++)
        worst[pass][f] = fmaxf(worst[pass][f], tolerance_ratio(f, out[f], tv_features[w * TV_N_FEATURES + f]));
    }
  }
  r.us_window = t_feat / (2 * TV_N_WINDOWS);
  for (int f = 0; f < EEG_N_FEATURES; f++) {
    const float wr = fmaxf(worst[0][f], worst[1][f]);
    r.worst_ratio = fmaxf(r.worst_ratio, wr);
    if (wr > 1.0f) { r.bad_features++; r.ok = false; }
  }
  if (verbose) {
    Serial.printf("Filtered samples: max error %.3g of full scale (limit 1e-3)\n", r.filt_err_rel);
    Serial.println("Worst error / tolerance per feature (python-filtered input | board-filtered input):");
    for (int f = 0; f < EEG_N_FEATURES; f++)
      Serial.printf("  %-18s %8.4f | %8.4f %s\n", kFeatureNames[f], worst[0][f], worst[1][f],
                    fmaxf(worst[0][f], worst[1][f]) <= 1.0f ? "" : "  FAIL");
  }
  return r;
}

// ---------------- sleep-model bench ----------------
alignas(16) uint8_t tensor_arena[SLEEP_MODEL_ARENA_BYTES];
tflite::MicroInterpreter* interpreter = nullptr;
TfLiteTensor* input = nullptr;
TfLiteTensor* output = nullptr;

struct TestEpoch { const char* name; const int8_t* in; const int8_t* out; };
const TestEpoch kTests[] = {
  {"W", g_sleep_in_w, g_sleep_out_w},     {"N1", g_sleep_in_n1, g_sleep_out_n1},
  {"N2", g_sleep_in_n2, g_sleep_out_n2},  {"N3", g_sleep_in_n3, g_sleep_out_n3},
  {"REM", g_sleep_in_rem, g_sleep_out_rem},
};

void halt(const char* msg) {
  Serial.println(msg);
  while (true) delay(1000);
}

int argmax(const int8_t* v, int n) {
  int best = 0;
  for (int i = 1; i < n; i++) if (v[i] > v[best]) best = i;
  return best;
}

void model_setup() {
  Serial.printf("Model v%d, feature schema %d, input %d, arena %d bytes\n", SLEEP_MODEL_VERSION,
                SLEEP_MODEL_FEATURE_SCHEMA, SLEEP_MODEL_N_INPUT, SLEEP_MODEL_ARENA_BYTES);
  if (SLEEP_MODEL_FEATURE_SCHEMA != kFeatureSchema) halt("REFUSED: model feature schema mismatch");
  const tflite::Model* model = tflite::GetModel(g_sleep_model);
  if (model->version() != TFLITE_SCHEMA_VERSION) halt("REFUSED: TFLite schema mismatch");
  static tflite::MicroMutableOpResolver<2> resolver;
  resolver.AddFullyConnected();
  resolver.AddSoftmax();
  static tflite::MicroInterpreter static_interpreter(model, resolver, tensor_arena, SLEEP_MODEL_ARENA_BYTES);
  interpreter = &static_interpreter;
  if (interpreter->AllocateTensors() != kTfLiteOk) halt("AllocateTensors failed (arena too small?)");
  input = interpreter->input(0);
  output = interpreter->output(0);
  if (input->type != kTfLiteInt8 || input->bytes != SLEEP_MODEL_N_INPUT ||
      output->bytes != SLEEP_MODEL_N_CLASSES) halt("Unexpected tensor shapes");
  Serial.printf("in scale %g zp %d, out scale %g zp %d\n", input->params.scale, input->params.zero_point,
                output->params.scale, output->params.zero_point);
  Serial.printf("Model %u bytes, arena used %u / %d bytes\n", g_sleep_model_len,
                (unsigned)interpreter->arena_used_bytes(), SLEEP_MODEL_ARENA_BYTES);
}

void model_bench(bool verbose) {
  int matches = 0;
  uint32_t worst = 0;
  for (const TestEpoch& t : kTests) {
    // TFLM reuses the input tensor's memory for later layers, so the input must be
    // copied before every Invoke (found in task 4b: reusing it gave wrong outputs).
    uint32_t t0 = micros();
    for (int r = 0; r < kTimingRuns; r++) {
      memcpy(input->data.int8, t.in, SLEEP_MODEL_N_INPUT);
      interpreter->Invoke();
    }
    uint32_t us = (micros() - t0) / kTimingRuns;  // includes the 90-byte copy
    worst = max(worst, us);
    memcpy(input->data.int8, t.in, SLEEP_MODEL_N_INPUT);
    if (interpreter->Invoke() != kTfLiteOk) halt("Invoke failed");
    bool same = memcmp(output->data.int8, t.out, SLEEP_MODEL_N_CLASSES) == 0;
    matches += same;
    if (!same) {
      Serial.print("  got");
      for (int i = 0; i < SLEEP_MODEL_N_CLASSES; i++) Serial.printf(" %d", output->data.int8[i]);
      Serial.print("  want");
      for (int i = 0; i < SLEEP_MODEL_N_CLASSES; i++) Serial.printf(" %d", t.out[i]);
      Serial.println();
    }
    if (verbose)
      Serial.printf("true %-3s -> predicted %-3s  output %s Python  %lu us/inference\n", t.name,
                    SLEEP_MODEL_STAGES[argmax(output->data.int8, SLEEP_MODEL_N_CLASSES)],
                    same ? "matches" : "DIFFERS from", (unsigned long)us);
  }
  Serial.printf("MODEL SUMMARY parity %d/5, worst %lu us/inference, arena used %u bytes\n", matches,
                (unsigned long)worst, (unsigned)interpreter->arena_used_bytes());
}

void features_summary(bool verbose) {
  ParityResult r = feature_parity(verbose);
  Serial.printf("FEATURE SUMMARY %s: filtered error %.2g of full scale, %d/%d features out of tolerance "
                "(worst %.3f of tolerance), %lu us/sample filter, %lu us/window features\n",
                r.ok ? "PASS" : "FAIL", r.filt_err_rel, r.bad_features, EEG_N_FEATURES, r.worst_ratio,
                (unsigned long)r.us_sample, (unsigned long)r.us_window);
}

// ---------------- replay ----------------
eeg::EpochFeatures epoch_features(&features);
eeg::ModelInput model_input;
float replay_buf[EEG_EPOCH];

void run_model(long t, const float* in) {
  for (int i = 0; i < SLEEP_MODEL_N_INPUT; i++)
    input->data.int8[i] = eeg::quantise_input(in[i], input->params.scale, input->params.zero_point);
  if (interpreter->Invoke() != kTfLiteOk) { Serial.printf("ERR invoke %ld\n", t); return; }
  const int8_t* q = output->data.int8;
  Serial.printf("OUT %ld %s %d %d %d %d %d\n", t, SLEEP_MODEL_STAGES[argmax(q, SLEEP_MODEL_N_CLASSES)],
                q[0], q[1], q[2], q[3], q[4]);
}

// The USB CDC receive buffer (8 KB) drops data when the host sends faster than it is read, so the
// host sends 4 KB chunks and waits for "C" after each (found in task 6b: 30 KB at once lost bytes).
constexpr size_t kChunk = 4096;

void replay_epoch() {
  const size_t want = sizeof replay_buf;
  uint8_t* dst = (uint8_t*)replay_buf;
  size_t got = 0;
  while (got < want) {
    const size_t n = min(kChunk, want - got);
    const size_t r = Serial.readBytes(dst + got, n);
    got += r;
    if (r != n) { Serial.printf("ERR short epoch %u/%u bytes\n", (unsigned)got, (unsigned)want); return; }
    Serial.println("C");
  }
  const uint32_t t0 = micros();
  float f[eeg::kEpochFeatures];
  bool done = false;
  for (int n = 0; n < EEG_EPOCH; n++) done |= epoch_features.push(replay_buf[n], f);
  const long e = epoch_features.epochs() - 1;
  if (!done) { Serial.println("ERR epoch did not complete"); return; }
  Serial.printf("FEAT %ld %d", e, epoch_features.last_window_count());
  for (int i = 0; i < eeg::kEpochFeatures; i++) Serial.printf(" %.9g", f[i]);
  Serial.println();
  model_input.push(f, run_model);
  Serial.printf("ACK %ld %lu\n", e, (unsigned long)(micros() - t0));
}

void self_tests() {
  Serial.printf("Vectors v%d: %d samples, %d windows x %d features\n", TV_VERSION, TV_N_SAMPLES,
                TV_N_WINDOWS, TV_N_FEATURES);
  features_summary(true);
  model_bench(true);
}

void setup() {
  Serial.setRxBufferSize(8192);
  Serial.begin(115200);
  Serial.setTimeout(10000);
  delay(2000);
  Serial.println("\n=== eeg_node: feature parity + sleep-model bench + replay ===");
  model_setup();
  self_tests();
  Serial.println("READY");
}

void loop() {
  if (!Serial.available()) { delay(1); return; }
  String cmd = Serial.readStringUntil('\n');
  cmd.trim();
  if (cmd == "EPOCH") {
    replay_epoch();
  } else if (cmd.startsWith("BEGIN")) {
    const float line = cmd.length() > 6 ? cmd.substring(6).toFloat() : 60.0f;
    if (line == 50.0f) epoch_features.begin(EEG_SOS_50, EEG_N_SOS_50, 50.0f);
    else epoch_features.begin(EEG_SOS_60, EEG_N_SOS_60, 60.0f);
    model_input.reset();
    Serial.printf("OK BEGIN %g\n", line == 50.0f ? 50.0f : 60.0f);
  } else if (cmd == "END") {
    model_input.finish(run_model);
    Serial.printf("DONE %ld\n", epoch_features.epochs());
  } else if (cmd == "TEST") {
    self_tests();
    Serial.println("READY");
  } else if (cmd.length()) {
    Serial.printf("ERR unknown command '%s'\n", cmd.c_str());
  }
}
