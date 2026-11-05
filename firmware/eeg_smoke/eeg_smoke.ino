// Toolchain smoke test for XIAO ESP32-S3: runs the INT8 model from scripts/smoke_test.py
// on two embedded test windows (alpha / beta) and prints predictions + inference time.
#include <Chirale_TensorFlowLite.h>
#include "model.h"
#include "tensorflow/lite/micro/all_ops_resolver.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/schema/schema_generated.h"

constexpr int kTensorArenaSize = 32 * 1024;
alignas(16) uint8_t tensor_arena[kTensorArenaSize];

tflite::MicroInterpreter* interpreter = nullptr;
TfLiteTensor* input = nullptr;
TfLiteTensor* output = nullptr;

void classify(const char* name, const int8_t* window, unsigned int len) {
  memcpy(input->data.int8, window, len);
  uint32_t t0 = micros();
  if (interpreter->Invoke() != kTfLiteOk) { Serial.println("Invoke failed"); return; }
  uint32_t dt = micros() - t0;
  int8_t a = output->data.int8[0], b = output->data.int8[1];
  Serial.printf("%s window -> predicted %s (scores %d/%d), %lu us\n",
                name, a > b ? "ALPHA" : "BETA", a, b, (unsigned long)dt);
}

void setup() {
  Serial.begin(115200);
  delay(2000);
  Serial.println("\n=== EEG TinyML smoke test ===");

  const tflite::Model* model = tflite::GetModel(g_model);
  if (model->version() != TFLITE_SCHEMA_VERSION) { Serial.println("Schema mismatch"); while (true) delay(1000); }

  static tflite::AllOpsResolver resolver;
  static tflite::MicroInterpreter static_interpreter(model, resolver, tensor_arena, kTensorArenaSize);
  interpreter = &static_interpreter;
  if (interpreter->AllocateTensors() != kTfLiteOk) { Serial.println("AllocateTensors failed"); while (true) delay(1000); }

  input = interpreter->input(0);
  output = interpreter->output(0);
  Serial.printf("Model %u bytes, arena used %u / %d bytes\n",
                g_model_len, (unsigned)interpreter->arena_used_bytes(), kTensorArenaSize);
}

void loop() {
  classify("Alpha", g_sample_alpha, g_sample_alpha_len);
  classify("Beta ", g_sample_beta, g_sample_beta_len);
  delay(3000);
}
