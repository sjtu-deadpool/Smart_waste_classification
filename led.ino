#include <ESP8266WiFi.h>
#include <WebSocketsServer.h>
#include <TFT_eSPI.h>
#include <ESP8266HTTPClient.h>

// Wi-Fi credentials
const char *ssid = "Columbia University";

// IFTTT Webhooks URL
const char *ifttt_url = "https://maker.ifttt.com/trigger/can_full/with/key/c9FfBtbZxJVn632cU40SJv";

// WebSocket server
WebSocketsServer webSocket(81);

// Display instance
TFT_eSPI tft = TFT_eSPI();

// Variables
String displayedText = "Ready..."; // For WebSocket messages

// Ultrasonic sensor pins
#define TRIG_PIN 5 // Trig pin
#define ECHO_PIN 4 // Echo pin

// State variables for ultrasonic logic
bool notification_sent = false;
unsigned long startTime = 0;
const unsigned long triggerDuration = 3000; // Duration for sustained detection (3 seconds)

// Function to connect to Wi-Fi
void connectWiFi()
{
  tft.setCursor(10, 10);
  tft.println("Connecting to Wi-Fi...");
  Serial.println("Connecting to Wi-Fi...");

  WiFi.begin(ssid);
  while (WiFi.status() != WL_CONNECTED)
  {
    delay(500);
    Serial.print(".");
  }

  // Clear "Connecting to Wi-Fi" message
  tft.fillRect(0, 10, 480, 20, TFT_BLACK);

  // Display Wi-Fi connection info
  Serial.println("\nWi-Fi Connected!");
  Serial.print("IP Address: ");
  Serial.println(WiFi.localIP());

  tft.setCursor(10, 10);
  tft.println("Wi-Fi Connected!");
  tft.setCursor(10, 30);
  tft.printf("IP: %s", WiFi.localIP().toString().c_str());
}

// Function to display arrows and message with enhanced formatting
void displayMessageWithArrow(const String &message, bool isRecyclable)
{
  tft.fillRect(0, 60, 480, 180, TFT_BLACK); // Clear previous area

  // Display message
  tft.setTextColor(TFT_GREEN);
  tft.setTextSize(3); // Regular message size
  tft.setCursor(20, 80);
  tft.println(message);

  // Display arrow larger and centered
  tft.setTextSize(5); // Larger font for arrow
  tft.setCursor(100, 140);
  if (isRecyclable)
  {
    tft.println("<--"); // Left arrow
  }
  else
  {
    tft.println("-->"); // Right arrow
  }
}

// Function to split and display text with line breaks
void displaySplitMessage(const String &message)
{
  tft.fillRect(0, 60, 480, 180, TFT_BLACK); // Clear previous display
  tft.setTextColor(TFT_CYAN);
  tft.setTextSize(3);

  int cursorX = 10, cursorY = 80;
  for (size_t i = 0; i < message.length(); i++)
  {
    if (message[i] == ' ')
    {
      cursorX = 10;  // Reset X position for a new line
      cursorY += 40; // Move to the next line
    }
    else
    {
      tft.setCursor(cursorX, cursorY);
      tft.print(message[i]);
      cursorX += 20; // Move cursor for next character
    }

    // Wrap to next line if the text reaches the right edge
    if (cursorX > 450)
    {
      cursorX = 10;
      cursorY += 40;
    }
  }
}

// WebSocket event handler
void onWebSocketEvent(uint8_t num, WStype_t type, uint8_t *payload, size_t length)
{
  switch (type)
  {
  case WStype_TEXT:                          // When a text message is received
    payload[length] = '\0';                  // Ensure null termination
    displayedText = String((char *)payload); // Update displayed content
    Serial.println("Received: " + displayedText);

    // Check message content
    if (displayedText.indexOf("Non") != -1)
    {
      displayMessageWithArrow(displayedText, false); // Non-recyclable
    }
    else if (displayedText.indexOf(":Recyc") != -1)
    {
      displayMessageWithArrow(displayedText, true); // Recyclable
    }
    else
    {
      displaySplitMessage(displayedText); // Default behavior: Split and display
    }
    break;

  case WStype_CONNECTED: // Client connected
    Serial.printf("Client %u connected.\n", num);
    break;

  case WStype_DISCONNECTED: // Client disconnected
    Serial.printf("Client %u disconnected.\n", num);
    break;

  default:
    break;
  }
}

// Function to measure distance using ultrasonic sensor
float measureDistance(int trigPin, int echoPin)
{
  digitalWrite(trigPin, LOW);
  delayMicroseconds(2);
  digitalWrite(trigPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(trigPin, LOW);

  long duration = pulseIn(echoPin, HIGH); // Read high-level time
  float distance = duration * 0.034 / 2;  // Convert to distance (cm)
  return distance;
}

// Function to send IFTTT notification
void sendNotification()
{
  if (WiFi.status() == WL_CONNECTED)
  {
    WiFiClientSecure client;
    client.setInsecure(); // Disable SSL verification for testing
    HTTPClient http;

    Serial.println("Sending notification to IFTTT...");
    http.begin(client, ifttt_url);
    http.addHeader("Content-Type", "application/json");

    String jsonPayload = "{\"value1\":\"The can is full\"}";
    int httpResponseCode = http.POST(jsonPayload);

    if (httpResponseCode > 0)
    {
      Serial.printf("Notification sent! HTTP code: %d\n", httpResponseCode);
      String payload = http.getString();
      Serial.println("Response payload: " + payload);
      updateNotificationStatus("Notification Sent!");
    }
    else
    {
      Serial.printf("Failed to send notification. Error: %s\n", http.errorToString(httpResponseCode).c_str());
      updateNotificationStatus("Notification Failed!");
    }
    http.end();
  }
  else
  {
    Serial.println("Wi-Fi Disconnected. Cannot send notification.");
    updateNotificationStatus("Wi-Fi Disconnected!");
  }
}

// Function to update the notification status on the display
void updateNotificationStatus(const char *status)
{
  tft.fillRect(0, 50, 480, 20, TFT_BLACK); // Clear notification area
  tft.setCursor(10, 50);
  tft.setTextColor(TFT_YELLOW);
  tft.setTextSize(2);
  tft.println(status);
}

void setup()
{
  // Initialize serial communication
  Serial.begin(115200);

  // Initialize ultrasonic sensor pins
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);

  // Initialize display
  tft.init();
  tft.setRotation(1);
  tft.fillScreen(TFT_BLACK);
  tft.setTextColor(TFT_WHITE);
  tft.setTextSize(2);

  // Connect to Wi-Fi
  connectWiFi();

  // Initialize WebSocket
  webSocket.begin();
  webSocket.onEvent(onWebSocketEvent);
  Serial.println("WebSocket server started! Listening for clients...");
}

void loop()
{
  // WebSocket handling
  webSocket.loop();

  // Ultrasonic sensor logic
  float distance = measureDistance(TRIG_PIN, ECHO_PIN);

  // Check if distance is less than 5cm
  if (distance < 5)
  {
    if (startTime == 0)
    {
      startTime = millis();
    }
    else if (millis() - startTime >= triggerDuration && !notification_sent)
    {
      sendNotification();
      notification_sent = true;
    }
  }
  else
  {
    startTime = 0;
    notification_sent = false;
    updateNotificationStatus("Normal");
  }

  delay(100); // Add a short delay to avoid excessive resource usage
}
