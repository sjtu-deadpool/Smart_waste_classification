# Smart waste classification

This project integrates YOLOv8 object detection with Whisper audio transcription, Google Cloud Vision fallback recognition, ultrasonic sensor-based distance detection, and LED signaling. The system identifies users by voice, classifies the disposed garbage, tracks user scores, and communicates with both an ESP32 (for ultrasonic sensors and camera) and an ESP8266 (for LED signaling and full-bin alerts).

## Features

- **Voice-based User Identification**:  
  Records a short audio clip, transcribes it using Whisper, and uses GPT-4 to extract user name and ID.  
  If the user does not exist in the database, a new user is created without an initial score. The user’s first disposal determines their initial score (100 if correct, 0 if incorrect).

- **Object Detection & Classification**:  
  Attempts to identify the disposed item using a pre-trained YOLOv8 model 
  If YOLO does not detect any object, falls back to Google Cloud Vision API for object recognition.

- **Waste Classification**:  
  Uses GPT-4 to classify identified items into "Recyclable Waste" or "Non-Recyclable Waste."

- **Ultrasonic Sensor Distance Input (ESP32)**:  
  The ESP32 is connected to ultrasonic sensors for each bin (e.g., one for recyclable and one for non-recyclable bin).  
  The ESP32 posts status signals every 2 seconds:
  - `status=1`: A close event in the recyclable bin  
  - `status=2`: A close event in the non-recyclable bin  
  - `status=0`: No event

  Based on these signals, the server decides if disposal is correct or incorrect.

- **LED Signaling and Full-bin Alerts (ESP8266)**:  
  An ESP8266 device is connected to an LED to indicate system status.  
  Additionally, the ESP8266 can send alerts when a bin is full, prompting the system or user to handle the situation.

- **User Scoring and Reminders**:  
  For the user's first disposal:
  - If correct: initial score = 100, complete_times = 1  
  - If incorrect: initial score = 0, complete_times = 1  
  Subsequent disposals update the score using:
  - Correct: `(old_score * old_times + 100) / (old_times + 1)`
  - Incorrect: `(old_score * old_times) / (old_times + 1)`

  Incorrect disposals add the disposed item to the user's reminder list. If the user tries to dispose of a "reminded" item incorrectly again, a warning message is shown.

- **Database Integration**:  
  User data is stored in a SQL database (e.g., SQLite). Operations for user retrieval, creation, updating score, and reminder items are handled via `db.py`.

- **Web Interface & API**:  
  A Gradio-based web UI for live monitoring.  
  A Flask API handles `/image` and `/distance` endpoints from the ESP32-CAM (for image input) and the ESP32 (for distance signals).

## Requirements

- Python 3.8+
- Dependencies (install via `pip install -r requirements.txt`):
  - `flask`
  - `gradio`
  - `whisper`
  - `openai`
  - `ultralytics` (for YOLOv8)
  - `opencv-python`
  - `google-cloud-vision`
  - `sounddevice`
  - `soundfile`
  - `websocket-client`
  - `sqlite3` (usually included with Python)
- `yolov8trained.pt` in the project root.
- Google Cloud Vision credentials file `credentials.json` (adjust path in `server.py`).
- A `users.db` SQLite database with a `users` table containing at least:  
  `name (TEXT PRIMARY KEY)`, `id (INT)`, `score (REAL)`, `reminder_items (TEXT)`, `complete_times (INT)`
