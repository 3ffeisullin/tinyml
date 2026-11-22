// On-device filters and window features (REQ-FEAT-01..05, REQ-FEAT-08, REQ-FEAT-09).
//
// A line-by-line port of eegml/filters.py and eegml/features.py. Constants come from
// eeg_config.h, generated from eegml/config.py by scripts/export_test_vectors.py.
//   * Filters: cascade of biquads, transposed direct form II, double precision, zero initial
//     state. float32 was tried first: samples within 6e-5 of full scale, but skew went to 2.3x
//     its tolerance (task 6, 2026-11-21). Double is software on the ESP32-S3 but cheap at 250 Hz.
//   * Window features: demean the filtered window, symmetric Hann, zero-pad to NFFT, real FFT,
//     band power = sum |X[k]|^2 / sum w^2 over bins f_k in [lo, hi); log10(P + EPS); relative
//     power vs 0.5-30 Hz; ratios; population skew / excess kurtosis of the demeaned filtered
//     window; quality: filtered peak-to-peak, mains ratio on the unfiltered window, clip fraction.
//   Sums and moments accumulate in double so the result doesn't depend on summation order.
#pragma once
#include <math.h>
#include <stdint.h>
#include <string.h>

#include "eeg_config.h"

namespace eeg {

// Feature indices (same order as eegml.features.FEATURE_NAMES).
enum : int {
  F_LOGP = 0, F_REL = EEG_N_BANDS, F_RATIO_DB = 2 * EEG_N_BANDS, F_RATIO_AB, F_RATIO_TA,
  F_SKEW, F_KURT, F_PTP, F_LINE, F_CLIP, F_COUNT
};
static_assert(F_COUNT == EEG_N_FEATURES, "feature layout differs from eegml");
// Band order in eeg_config.h: delta, theta, alpha, sigma, beta, gamma.
enum : int { B_DELTA = 0, B_THETA, B_ALPHA, B_SIGMA, B_BETA, B_GAMMA };

class BiquadCascade {
 public:
  static constexpr int kMaxSections = 8;

  // sos: n rows of (b0, b1, b2, a0, a1, a2), as scipy's SOS layout.
  bool init(const double* sos, int n) {
    if (n > kMaxSections) return false;
    n_ = n;
    for (int s = 0; s < n; s++) {
      const double* r = sos + 6 * s;
      const double a0 = r[3];
      b0_[s] = r[0] / a0; b1_[s] = r[1] / a0; b2_[s] = r[2] / a0;
      a1_[s] = r[4] / a0; a2_[s] = r[5] / a0;
    }
    reset();
    return true;
  }
  void reset() { memset(z1_, 0, sizeof z1_); memset(z2_, 0, sizeof z2_); }

  float process(float in) {
    double x = in;
    for (int s = 0; s < n_; s++) {
      const double y = b0_[s] * x + z1_[s];
      z1_[s] = b1_[s] * x - a1_[s] * y + z2_[s];
      z2_[s] = b2_[s] * x - a2_[s] * y;
      x = y;
    }
    return (float)x;
  }

 private:
  int n_ = 0;
  double b0_[kMaxSections], b1_[kMaxSections], b2_[kMaxSections];
  double a1_[kMaxSections], a2_[kMaxSections];
  double z1_[kMaxSections], z2_[kMaxSections];
};

class WindowFeatures {
 public:
  WindowFeatures() {
    double w2 = 0;
    for (int n = 0; n < EEG_WIN; n++) {
      const double w = 0.5 - 0.5 * cos(2.0 * M_PI * n / (EEG_WIN - 1));
      hann_[n] = (float)w;
      w2 += w * w;
    }
    inv_w2_ = 1.0 / w2;
    for (int k = 0; k < EEG_NFFT / 2; k++) {
      cos_[k] = (float)cos(2.0 * M_PI * k / EEG_NFFT);
      sin_[k] = (float)-sin(2.0 * M_PI * k / EEG_NFFT);
    }
  }

  // filt, raw: EEG_WIN samples (uV). adc_full_scale_uv <= 0 means "unknown" (clip fraction 0).
  void compute(const float* filt, const float* raw, float line_freq, float adc_full_scale_uv,
               float out[EEG_N_FEATURES]) {
    // Band powers of the demeaned, Hann-weighted filtered window.
    double mean = 0;
    for (int n = 0; n < EEG_WIN; n++) mean += filt[n];
    mean /= EEG_WIN;
    power_spectrum(filt, mean);
    double p[EEG_N_BANDS], p_tot = 0;
    for (int b = 0; b < EEG_N_BANDS; b++) p[b] = band_sum(EEG_BAND_LO[b], EEG_BAND_HI[b]);
    p_tot = band_sum(EEG_TOTAL_LO, EEG_TOTAL_HI);
    for (int b = 0; b < EEG_N_BANDS; b++) {
      out[F_LOGP + b] = (float)log10(p[b] + EEG_EPS);
      out[F_REL + b] = p_tot > 0 ? (float)(p[b] / p_tot) : 0.0f;
    }
    out[F_RATIO_DB] = (float)(p[B_DELTA] / (p[B_BETA] + EEG_EPS));
    out[F_RATIO_AB] = (float)(p[B_ALPHA] / (p[B_BETA] + EEG_EPS));
    out[F_RATIO_TA] = (float)(p[B_THETA] / (p[B_ALPHA] + EEG_EPS));

    // Population skew and excess kurtosis; peak-to-peak of the filtered window.
    double m2 = 0, m3 = 0, m4 = 0;
    float lo = filt[0], hi = filt[0];
    for (int n = 0; n < EEG_WIN; n++) {
      const double d = filt[n] - mean, d2 = d * d;
      m2 += d2; m3 += d2 * d; m4 += d2 * d2;
      if (filt[n] < lo) lo = filt[n];
      if (filt[n] > hi) hi = filt[n];
    }
    m2 /= EEG_WIN; m3 /= EEG_WIN; m4 /= EEG_WIN;
    out[F_SKEW] = m2 > 0 ? (float)(m3 / pow(m2, 1.5)) : 0.0f;
    out[F_KURT] = m2 > 0 ? (float)(m4 / (m2 * m2) - 3.0) : 0.0f;
    out[F_PTP] = hi - lo;

    // Mains ratio on the unfiltered window.
    double rmean = 0;
    for (int n = 0; n < EEG_WIN; n++) rmean += raw[n];
    rmean /= EEG_WIN;
    power_spectrum(raw, rmean);
    const double line = band_sum(line_freq - EEG_LINE_HALF_WIDTH, line_freq + EEG_LINE_HALF_WIDTH);
    const bool has_line = (line_freq + EEG_LINE_HALF_WIDTH) > 0 && (line_freq - EEG_LINE_HALF_WIDTH) < EEG_FS / 2;
    out[F_LINE] = has_line ? (float)(line / (band_sum(EEG_TOTAL_LO, EEG_TOTAL_HI) + EEG_EPS)) : 0.0f;

    int clipped = 0;
    if (adc_full_scale_uv > 0)
      for (int n = 0; n < EEG_WIN; n++) clipped += fabsf(raw[n]) >= 0.98f * adc_full_scale_uv;
    out[F_CLIP] = (float)clipped / EEG_WIN;
  }

 private:
  // |FFT((x - mean) * hann, zero-padded to NFFT)|^2 / sum(w^2) into pow_[0..NFFT/2].
  void power_spectrum(const float* x, double mean) {
    for (int n = 0; n < EEG_NFFT; n++) {
      re_[n] = n < EEG_WIN ? (float)((x[n] - mean) * hann_[n]) : 0.0f;
      im_[n] = 0.0f;
    }
    fft();
    for (int k = 0; k <= EEG_NFFT / 2; k++)
      pow_[k] = ((double)re_[k] * re_[k] + (double)im_[k] * im_[k]) * inv_w2_;
  }

  // Sum of pow_ over bins with f_k = k * FS / NFFT in [lo, hi). f_k is exact in float.
  double band_sum(float lo, float hi) const {
    double s = 0;
    for (int k = 0; k <= EEG_NFFT / 2; k++) {
      const float f = (float)k * EEG_FS / EEG_NFFT;
      if (f >= lo && f < hi) s += pow_[k];
    }
    return s;
  }

  // In-place iterative radix-2 complex FFT on re_/im_ (forward, no scaling, like numpy).
  void fft() {
    for (int i = 1, j = 0; i < EEG_NFFT; i++) {  // bit reversal
      int bit = EEG_NFFT >> 1;
      for (; j & bit; bit >>= 1) j ^= bit;
      j ^= bit;
      if (i < j) { float t = re_[i]; re_[i] = re_[j]; re_[j] = t; t = im_[i]; im_[i] = im_[j]; im_[j] = t; }
    }
    for (int len = 2; len <= EEG_NFFT; len <<= 1) {
      const int half = len >> 1, step = EEG_NFFT / len;
      for (int i = 0; i < EEG_NFFT; i += len)
        for (int k = 0; k < half; k++) {
          const float wr = cos_[k * step], wi = sin_[k * step];
          const int a = i + k, b = a + half;
          const float xr = re_[b] * wr - im_[b] * wi, xi = re_[b] * wi + im_[b] * wr;
          re_[b] = re_[a] - xr; im_[b] = im_[a] - xi;
          re_[a] += xr; im_[a] += xi;
        }
    }
  }

  float hann_[EEG_WIN];
  double inv_w2_;
  float cos_[EEG_NFFT / 2], sin_[EEG_NFFT / 2];
  float re_[EEG_NFFT], im_[EEG_NFFT];
  double pow_[EEG_NFFT / 2 + 1];
};

}  // namespace eeg
