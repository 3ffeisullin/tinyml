// Sample acquisition on core 0 (task 7a; REQ-HW-02/03, REQ-ACQ-01..03).
//
// One FreeRTOS task, pinned to core 0 at the highest priority, wakes once per sample and
// pushes the sample (uV at the electrode) into a queue that the processing on core 1
// drains. It never touches Wi-Fi, TLS or flash (REQ-ACQ-03). Two sources feed the same path:
//   Adc   the ADS1115's ALERT/RDY pin (falling edge, one pulse per conversion at 250 SPS)
//         wakes the task, which reads the conversion register over I2C (REQ-ACQ-02).
//   Fake  a 250 Hz esp_timer stands in for ALERT/RDY and the task replays the reference
//         signal from feature_vectors_v1.h, so the live path can be checked against Python
//         before the hardware exists.
// Missed wake-ups (more than one pending when the task runs) are counted, never hidden.
#pragma once
#include <Arduino.h>
#include <Wire.h>

#include "eeg_config.h"
#include "esp_timer.h"
#include "feature_vectors_v1.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"

namespace acq {

// REQ-HW-03 pin map (XIAO ESP32-S3): D4 = GPIO5 SDA, D5 = GPIO6 SCL, D1 = GPIO2 ALERT/RDY.
constexpr int kPinSda = 5, kPinScl = 6, kPinRdy = 2;
constexpr uint8_t kRegConversion = 0x00, kRegConfig = 0x01, kRegLoThresh = 0x02, kRegHiThresh = 0x03;
constexpr int kQueueLen = 1024;  // ~4 s of samples: room for core 1 to fall behind briefly

enum class Source { None, Adc, AdcSingleEnded, Fake };

struct Stats {
  volatile uint32_t samples = 0;     // pushed into the queue
  volatile uint32_t missed = 0;      // wake-ups that arrived while the previous was pending
  volatile uint32_t i2c_errors = 0;
  volatile uint32_t queue_full = 0;  // samples dropped because core 1 fell behind
  volatile uint32_t timeouts = 0;    // no wake-up within 50 ms while running
};

class Ads1115 {
 public:
  bool begin(TwoWire& wire) {
    wire_ = &wire;
    wire_->begin(kPinSda, kPinScl, EEG_ADC_I2C_HZ);
    wire_->beginTransmission(EEG_ADC_I2C_ADDR);
    present_ = wire_->endTransmission() == 0;
    return present_;
  }
  bool present() const { return present_; }

  // Continuous conversion with ALERT/RDY as conversion-ready: Hi_thresh MSB 1, Lo_thresh MSB 0.
  bool configure(uint16_t config) {
    if (!present_) return false;
    if (!write(kRegLoThresh, 0x0000) || !write(kRegHiThresh, 0x8000) || !write(kRegConfig, config)) return false;
    uint16_t back = 0;
    return read_reg(kRegConfig, &back) && (back & 0x7FFF) == (config & 0x7FFF);  // bit 15 reads as status
  }
  bool read(int16_t* counts) {
    uint16_t v;
    if (!read_reg(kRegConversion, &v)) return false;
    *counts = (int16_t)v;
    return true;
  }
  bool read_reg(uint8_t reg, uint16_t* v) {
    wire_->beginTransmission(EEG_ADC_I2C_ADDR);
    wire_->write(reg);
    if (wire_->endTransmission(false) != 0) return false;
    if (wire_->requestFrom((uint8_t)EEG_ADC_I2C_ADDR, (uint8_t)2) != 2) return false;
    *v = (uint16_t)(wire_->read() << 8);
    *v |= (uint16_t)wire_->read();
    return true;
  }

 private:
  bool write(uint8_t reg, uint16_t v) {
    wire_->beginTransmission(EEG_ADC_I2C_ADDR);
    wire_->write(reg);
    wire_->write((uint8_t)(v >> 8));
    wire_->write((uint8_t)(v & 0xFF));
    return wire_->endTransmission() == 0;
  }
  TwoWire* wire_ = nullptr;
  bool present_ = false;
};

class Acquisition {
 public:
  bool begin() {
    queue_ = xQueueCreate(kQueueLen, sizeof(float));
    if (!queue_) return false;
    esp_timer_create_args_t args = {};
    args.callback = &Acquisition::fake_tick;
    args.arg = this;
    args.name = "fake_rdy";
    if (esp_timer_create(&args, &fake_timer_) != ESP_OK) return false;
    adc_.begin(Wire);
    pinMode(kPinRdy, INPUT_PULLUP);  // ALERT/RDY is open-drain
    return xTaskCreatePinnedToCore(&Acquisition::task_entry, "acq", 4096, this,
                                   configMAX_PRIORITIES - 1, &task_, 0) == pdPASS;
  }

  bool adc_present() const { return adc_.present(); }

  // Microvolts at the electrode per ADC count (REQ-ACQ-01; EEG_PILL_GAIN is a placeholder).
  static float uv_per_count(bool single_ended) {
    return (single_ended ? EEG_ADC_LSB_UV_SINGLE : EEG_ADC_LSB_UV_DIFF) / EEG_PILL_GAIN;
  }
  // ADC full scale in uV at the electrode, for the clip-fraction metric (REQ-FEAT-08).
  static float full_scale_uv(bool single_ended) { return uv_per_count(single_ended) * 32768.0f; }

  // Start a source from a clean state. Returns false if the ADC is absent or won't configure.
  bool start(Source s) {
    stop();
    stats_ = Stats();
    fake_idx_ = 0;
    xQueueReset(queue_);
    if (s == Source::Fake) {
      source_ = s;
      started_ms_ = millis();
      return esp_timer_start_periodic(fake_timer_, 1000000 / EEG_ADC_SPS) == ESP_OK;
    }
    if (s == Source::Adc || s == Source::AdcSingleEnded) {
      single_ = s == Source::AdcSingleEnded;
      if (!adc_.configure(single_ ? EEG_ADC_CONFIG_SINGLE : EEG_ADC_CONFIG_DIFF)) return false;
      uv_per_count_ = uv_per_count(single_);
      source_ = s;
      started_ms_ = millis();
      attachInterruptArg(digitalPinToInterrupt(kPinRdy), &Acquisition::rdy_isr, this, FALLING);
      return true;
    }
    return true;
  }

  void stop() {
    if (source_ == Source::Fake) esp_timer_stop(fake_timer_);
    if (source_ == Source::Adc || source_ == Source::AdcSingleEnded) detachInterrupt(digitalPinToInterrupt(kPinRdy));
    source_ = Source::None;
  }

  bool next(float* uv) { return xQueueReceive(queue_, uv, 0) == pdTRUE; }
  Source source() const { return source_; }
  const Stats& stats() const { return stats_; }
  float rate_hz() const {
    const uint32_t ms = millis() - started_ms_;
    return ms ? 1000.0f * stats_.samples / ms : 0.0f;
  }

 private:
  static void IRAM_ATTR rdy_isr(void* self) {
    BaseType_t woken = pdFALSE;
    vTaskNotifyGiveFromISR(static_cast<Acquisition*>(self)->task_, &woken);
    portYIELD_FROM_ISR(woken);
  }
  static void fake_tick(void* self) { xTaskNotifyGive(static_cast<Acquisition*>(self)->task_); }
  static void task_entry(void* self) { static_cast<Acquisition*>(self)->run(); }

  void run() {
    for (;;) {
      const uint32_t n = ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(50));
      const Source s = source_;
      if (s == Source::None) continue;
      if (n == 0) { stats_.timeouts++; continue; }
      if (n > 1) stats_.missed += n - 1;  // only the newest conversion is readable
      float uv;
      if (s == Source::Fake) {
        uv = tv_raw_uv[fake_idx_];
        fake_idx_ = (fake_idx_ + 1) % TV_N_SAMPLES;
      } else {
        int16_t counts;
        if (!adc_.read(&counts)) { stats_.i2c_errors++; continue; }
        uv = counts * uv_per_count_;
      }
      if (xQueueSend(queue_, &uv, 0) == pdTRUE) stats_.samples++;
      else stats_.queue_full++;
    }
  }

  Ads1115 adc_;
  QueueHandle_t queue_ = nullptr;
  TaskHandle_t task_ = nullptr;
  esp_timer_handle_t fake_timer_ = nullptr;
  volatile Source source_ = Source::None;
  Stats stats_;
  int fake_idx_ = 0;
  bool single_ = false;
  float uv_per_count_ = 0.0f;
  uint32_t started_ms_ = 0;
};

}  // namespace acq
