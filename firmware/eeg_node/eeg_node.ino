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
// No sensor or electrodes are needed. Acquisition joins in task 7.
#include <Chirale_TensorFlowLite.h>
#include "eeg_config.h"
#include "eeg_features.h"
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

void setup() {
  Serial.begin(115200);
  delay(2000);
  Serial.println("\n=== eeg_node: feature parity + sleep-model bench ===");
  Serial.printf("Vectors v%d: %d samples, %d windows x %d features\n", TV_VERSION, TV_N_SAMPLES,
                TV_N_WINDOWS, TV_N_FEATURES);
  features_summary(true);
  model_setup();
  model_bench(true);
}

void loop() {
  delay(5000);
  features_summary(false);
  model_bench(false);
}
