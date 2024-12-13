#include "esp_camera.h"
#include <WiFi.h>
#include <HTTPClient.h>

#define CAMERA_MODEL_AI_THINKER
#include "camera_pins.h"

const char *ssid = "Columbia University";

const char *serverUrl = "http://10.206.107.110:12345/image";

unsigned long interval = 5000;
unsigned long previousMillis = 0;

void setup_camera()
{
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;

  // 使用较高分辨率和质量（根据需要调整）
  config.frame_size = FRAMESIZE_UXGA;
  config.jpeg_quality = 10;
  config.fb_count = 1;

  // 如果有PSRAM，可以使用更高质量和双缓冲
  if (psramFound())
  {
    config.jpeg_quality = 8;
    config.fb_count = 2;
    config.grab_mode = CAMERA_GRAB_LATEST;
  }
  else
  {
    // 无PSRAM则降低分辨率或使用更高质量值(数字越大质量越低)
    // config.frame_size = FRAMESIZE_VGA;
  }

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK)
  {
    Serial.printf("Camera init failed with error 0x%x\n", err);
    return;
  }
}

void sendImage()
{
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb)
  {
    Serial.println("Camera capture failed");
    return;
  }

  if (WiFi.status() == WL_CONNECTED)
  {
    HTTPClient http;
    if (http.begin(serverUrl))
    {
      http.addHeader("Content-Type", "image/jpeg");

      Serial.println("Sending image to server...");
      Serial.printf("Image size: %d bytes\n", fb->len);

      int httpResponseCode = http.POST(fb->buf, fb->len);

      if (httpResponseCode > 0)
      {
        String response = http.getString();
        Serial.printf("HTTP Response code: %d\n", httpResponseCode);
        Serial.println("Server Response:");
        Serial.println(response);
      }
      else
      {
        Serial.printf("Error occurred: %s\n", http.errorToString(httpResponseCode).c_str());
      }

      http.end();
    }
    else
    {
      Serial.println("Failed to begin HTTP connection");
    }
  }
  else
  {
    Serial.println("WiFi not connected, cannot send image");
  }

  esp_camera_fb_return(fb);
}

void setup()
{
  Serial.begin(115200);
  Serial.setDebugOutput(true);
  Serial.println();

  setup_camera();

  WiFi.begin(ssid);
  WiFi.setSleep(false);

  while (WiFi.status() != WL_CONNECTED)
  {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi connected");
  Serial.println("Camera ready, will send images every 10 seconds...");
}

void loop()
{
  unsigned long currentMillis = millis();
  if (currentMillis - previousMillis >= interval)
  {
    previousMillis = currentMillis;
    sendImage();
  }
}