#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

const char *ssid = "Columbia University";

const char *serverUrl = "http://10.206.107.110:12345/distance";

const int trigPin1 = 14;
const int echoPin1 = 13;

const int trigPin2 = 4;
const int echoPin2 = 16;

const int distanceThreshold = 3;

unsigned long sendInterval = 2000;
unsigned long previousSendMillis = 0;

unsigned long measureInterval = 10;
unsigned long previousMeasureMillis = 0;

bool closeDetected1 = false; // recyclable
bool closeDetected2 = false; // unrecyclable

int firstTriggered = 0;

int measureDistance(int trigPin, int echoPin)
{
  digitalWrite(trigPin, LOW);
  delayMicroseconds(2);
  digitalWrite(trigPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(trigPin, LOW);

  unsigned long duration = pulseIn(echoPin, HIGH, 30000); // 30ms超时
  if (duration > 0)
  {
    int dist = duration * 0.034 / 2;
    return dist;
  }
  return -1;
}

void sendStatus(int statusValue)
{
  if (WiFi.status() == WL_CONNECTED)
  {
    HTTPClient http;
    if (http.begin(serverUrl))
    {
      http.addHeader("Content-Type", "application/json");

      StaticJsonDocument<64> doc;
      doc["status"] = statusValue;
      String payload;
      serializeJson(doc, payload);

      int httpResponseCode = http.POST((uint8_t *)payload.c_str(), payload.length());
      if (httpResponseCode > 0)
      {
        String response = http.getString();
        Serial.printf("Status sent! Code: %d\n", httpResponseCode);
        Serial.println("Server Response:");
        Serial.println(response);
      }
      else
      {
        Serial.printf("Error sending status: %s\n", http.errorToString(httpResponseCode).c_str());
      }

      http.end();
    }
    else
    {
      Serial.println("Failed to begin HTTP connection for status endpoint.");
    }
  }
  else
  {
    Serial.println("WiFi disconnected, cannot send status.");
  }
}

void setup()
{
  Serial.begin(115200);
  pinMode(trigPin1, OUTPUT);
  pinMode(echoPin1, INPUT);
  pinMode(trigPin2, OUTPUT);
  pinMode(echoPin2, INPUT);

  WiFi.begin(ssid);
  WiFi.setSleep(false);
  while (WiFi.status() != WL_CONNECTED)
  {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi connected");
  Serial.println("Starting measurement...");
}

void loop()
{
  unsigned long currentMillis = millis();

  if (currentMillis - previousMeasureMillis >= measureInterval)
  {
    previousMeasureMillis = currentMillis;

    int dist1 = measureDistance(trigPin1, echoPin1);
    if (dist1 >= 0 && dist1 < distanceThreshold)
    {
      closeDetected1 = true;

      if (firstTriggered == 0)
      {
        firstTriggered = 1;
      }
      Serial.printf("Close detected (Recyclable): %d cm\n", dist1);
    }

    int dist2 = measureDistance(trigPin2, echoPin2);
    if (dist2 >= 0 && dist2 < distanceThreshold)
    {
      closeDetected2 = true;
      if (firstTriggered == 0)
      {
        firstTriggered = 2;
      }
      Serial.printf("Close detected (Non-Recyclable): %d cm\n", dist2);
    }
  }

  // 每2秒发送一次状态
  if (currentMillis - previousSendMillis >= sendInterval)
  {
    previousSendMillis = currentMillis;

    int statusToSend = 0;
    if (firstTriggered == 1)
    {
      statusToSend = 1;
    }
    else if (firstTriggered == 2)
    {
      statusToSend = 2;
    }
    else
    {
      // 没有事件
      statusToSend = 0;
    }

    sendStatus(statusToSend);

    closeDetected1 = false;
    closeDetected2 = false;
    firstTriggered = 0;
  }
}