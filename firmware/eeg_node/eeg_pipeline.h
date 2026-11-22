// Raw samples -> 30 s epoch features -> sleep-model input, on the device (task 6b).
//
// Mirrors the Python reference step by step:
//   EpochFeatures   eegml.sleep_edf.device_epoch_features + eegml.epochs.epoch_features
//                   (REQ-FEAT-06): filter every sample; one window every EEG_HOP samples;
//                   the 29 windows that lie fully inside a 30 s epoch are summarised as the
//                   mean and population SD of logp_*, rel_*, skew, kurtosis (14 each), plus
//                   max peak-to-peak and mean mains ratio = 30 features.
//   ModelInput      eegml.sleep_model.running_standardise + model_input (REQ-FEAT-10):
//                   Welford mean / population SD per feature; the first SLEEP_MODEL_WARMUP_EPOCHS
//                   epochs are held back and emitted together once the warm-up completes; then
//                   z = clip((x - mean) / max(sd, floor)), input = [z_t, z_t-1, z_t-2], where the
//                   missing earlier epochs at the start repeat epoch 0.
// Epochs are counted from the first sample pushed after begin(); the caller aligns them.
#pragma once
#include <math.h>
#include <string.h>

#include "eeg_config.h"
#include "eeg_features.h"
#include "sleep_model.h"

namespace eeg {

constexpr int kSummarised = 2 * EEG_N_BANDS + 2;              // logp x6, rel x6, skew, kurtosis
constexpr int kEpochFeatures = 2 * kSummarised + 2;          // 30
constexpr int kWindowsPerEpoch = (EEG_EPOCH - EEG_WIN) / EEG_HOP + 1;  // 29
static_assert(kEpochFeatures == SLEEP_MODEL_N_FEATURES, "epoch features differ from the model input");
static_assert(SLEEP_MODEL_N_INPUT == kEpochFeatures * (SLEEP_MODEL_NEIGHBOURS + 1), "model input layout");

// Window feature index of each summarised feature, in eegml.epochs.SUMMARISED order.
inline int summarised_index(int i) {
  return i < 2 * EEG_N_BANDS ? F_LOGP + i : (i == 2 * EEG_N_BANDS ? F_SKEW : F_KURT);
}

class EpochFeatures {
 public:
  explicit EpochFeatures(WindowFeatures* wf) : wf_(wf) {}

  void begin(const double* sos, int n_sos, float line_freq, float adc_full_scale_uv = 0.0f) {
    chain_.init(sos, n_sos);
    line_freq_ = line_freq;
    adc_fs_ = adc_full_scale_uv;
    n_ = 0;
    epochs_ = 0;
    new_window_ = false;
    reset_epoch();
  }

  // Push one raw sample (uV). Returns true when an epoch completed; its features go to out.
  bool push(float raw, float out[kEpochFeatures]) {
    const int pos = (int)(n_ % EEG_WIN);
    raw_[pos] = raw;
    filt_[pos] = chain_.process(raw);
    n_++;
    if (n_ >= EEG_WIN && (n_ - EEG_WIN) % EEG_HOP == 0) {
      const long start = n_ - EEG_WIN;
      compute_window();  // every window, for the 1 s live output
      // Only windows that lie fully inside one epoch count (REQ-FEAT-06, decision D-2).
      if (start / EEG_EPOCH == (start + EEG_WIN - 1) / EEG_EPOCH) add_window();
    }
    if (n_ % EEG_EPOCH == 0) {
      finish_epoch(out);
      epochs_++;
      return true;
    }
    return false;
  }

  long epochs() const { return epochs_; }
  int last_window_count() const { return last_windows_; }
  long samples() const { return n_; }

  // The newest 1 s window's features, once per window (start sample in *start).
  bool take_window(float out[EEG_N_FEATURES], long* start = nullptr) {
    if (!new_window_) return false;
    new_window_ = false;
    memcpy(out, win_, sizeof win_);
    if (start) *start = win_start_;
    return true;
  }

 private:
  void reset_epoch() {
    memset(sum_, 0, sizeof sum_);
    memset(sumsq_, 0, sizeof sumsq_);
    ptp_max_ = -INFINITY;
    line_sum_ = 0;
    windows_ = 0;
  }

  void compute_window() {
    const int head = (int)(n_ % EEG_WIN);  // oldest sample of the last EEG_WIN
    for (int i = 0; i < EEG_WIN; i++) {
      const int k = (head + i) % EEG_WIN;
      wraw_[i] = raw_[k];
      wfilt_[i] = filt_[k];
    }
    wf_->compute(wfilt_, wraw_, line_freq_, adc_fs_, win_);
    win_start_ = n_ - EEG_WIN;
    new_window_ = true;
  }

  void add_window() {
    const float* f = win_;
    for (int i = 0; i < kSummarised; i++) {
      const double v = f[summarised_index(i)];
      sum_[i] += v;
      sumsq_[i] += v * v;
    }
    if (f[F_PTP] > ptp_max_) ptp_max_ = f[F_PTP];
    line_sum_ += f[F_LINE];
    windows_++;
  }

  void finish_epoch(float out[kEpochFeatures]) {
    last_windows_ = windows_;
    const double n = windows_ > 0 ? windows_ : 1;
    for (int i = 0; i < kSummarised; i++) {
      const double mean = sum_[i] / n;
      const double var = sumsq_[i] / n - mean * mean;
      out[i] = (float)mean;
      out[kSummarised + i] = (float)sqrt(var > 0 ? var : 0);
    }
    out[2 * kSummarised] = windows_ > 0 ? ptp_max_ : NAN;
    out[2 * kSummarised + 1] = (float)(line_sum_ / n);
    reset_epoch();
  }

  WindowFeatures* wf_;
  BiquadCascade chain_;
  float line_freq_ = 60.0f, adc_fs_ = 0.0f;
  long n_ = 0, epochs_ = 0;
  float raw_[EEG_WIN], filt_[EEG_WIN], wraw_[EEG_WIN], wfilt_[EEG_WIN];
  float win_[EEG_N_FEATURES];
  long win_start_ = 0;
  bool new_window_ = false;
  double sum_[kSummarised], sumsq_[kSummarised], line_sum_;
  float ptp_max_;
  int windows_ = 0, last_windows_ = 0;
};

class ModelInput {
 public:
  static constexpr int kWarm = SLEEP_MODEL_WARMUP_EPOCHS;
  static constexpr int kN = kEpochFeatures;

  void reset() { n_ = 0; memset(mean_, 0, sizeof mean_); memset(m2_, 0, sizeof m2_); }

  // Feed epoch t's features. Calls emit(epoch_index, float input[SLEEP_MODEL_N_INPUT]) for
  // every epoch that becomes ready: none during warm-up, kWarm at its end, then one per epoch.
  template <class Emit>
  void push(const float* x, Emit emit) {
    update(x);
    const long t = n_ - 1;
    if (t < kWarm) {
      memcpy(warm_[t], x, sizeof warm_[t]);
      if (n_ == kWarm) flush_warmup(emit);
    } else {
      float z[kN];
      standardise(x, z);
      emit_one(t, z, emit);
    }
  }

  // End of session shorter than the warm-up: score what there is with its own stats.
  template <class Emit>
  void finish(Emit emit) {
    if (n_ > 0 && n_ < kWarm) flush_warmup(emit);
  }

 private:
  void update(const float* x) {  // Welford, double
    n_++;
    for (int i = 0; i < kN; i++) {
      const double d = x[i] - mean_[i];
      mean_[i] += d / n_;
      m2_[i] += d * (x[i] - mean_[i]);
    }
  }

  void standardise(const float* x, float* z) const {
    for (int i = 0; i < kN; i++) {
      double sd = sqrt(m2_[i] / n_);
      if (sd < SLEEP_MODEL_SD_FLOOR) sd = SLEEP_MODEL_SD_FLOOR;
      double v = (x[i] - mean_[i]) / sd;
      if (v > SLEEP_MODEL_INPUT_CLIP) v = SLEEP_MODEL_INPUT_CLIP;
      if (v < -SLEEP_MODEL_INPUT_CLIP) v = -SLEEP_MODEL_INPUT_CLIP;
      z[i] = (float)v;
    }
  }

  template <class Emit>
  void flush_warmup(Emit emit) {
    for (long k = 0; k < n_; k++) {
      float z[kN];
      standardise(warm_[k], z);
      emit_one(k, z, emit);
    }
  }

  template <class Emit>
  void emit_one(long t, const float* z, Emit emit) {
    if (t == 0) { memcpy(prev1_, z, sizeof prev1_); memcpy(prev2_, z, sizeof prev2_); }
    float in[SLEEP_MODEL_N_INPUT];
    memcpy(in, z, sizeof(float) * kN);
    memcpy(in + kN, prev1_, sizeof(float) * kN);
    memcpy(in + 2 * kN, prev2_, sizeof(float) * kN);
    memcpy(prev2_, prev1_, sizeof prev2_);
    memcpy(prev1_, z, sizeof prev1_);
    emit(t, in);
  }

  long n_ = 0;
  double mean_[kN], m2_[kN];
  float warm_[kWarm][kN];
  float prev1_[kN], prev2_[kN];
};

// Quantise a float model input like eegml.sleep_model.Int8Runner.quantise: numpy 2 computes
// x / scale + zero_point in float32 (Python scalars don't widen a float32 array), then rounds
// half to even; clamp to int8.
inline int8_t quantise_input(float x, float scale, int zero_point) {
  const float v = x / scale + (float)zero_point;
  float q = nearbyintf(v);
  if (q > 127) q = 127;
  if (q < -128) q = -128;
  return (int8_t)q;
}

}  // namespace eeg
