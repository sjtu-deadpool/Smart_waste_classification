import gradio as gr
from flask import Flask, request, jsonify
from datetime import datetime
import os
from google.cloud import vision
from google.oauth2 import service_account
import io
import numpy as np
import threading
from queue import Queue
import time
import openai
import json
import websocket
import sounddevice as sd
import soundfile as sf
import whisper
import base64
import random
import cv2

from Smart_waste_classification.db import get_user_by_name, create_user, update_user_score_and_times, update_user_reminder_items, set_user_first_disposal

RECORDING_DURATION = 5
SAMPLE_RATE = 44100
CHANNELS = 1
AUDIO_FOLDER = 'recorded_audio'
if not os.path.exists(AUDIO_FOLDER):
    os.makedirs(AUDIO_FOLDER)

UPLOAD_FOLDER = 'captured_images'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

print("Loading Whisper model...")
whisper_model = whisper.load_model("base")

print("Loading YOLOv8 model...")
from ultralytics import YOLO
model = YOLO("yolov8trained.pt")

ESP8266_IP = "10.206.92.156"
PORT = 81
WS_URL = f"ws://{ESP8266_IP}:{PORT}/"

app = Flask(__name__)

CREDENTIALS_FILE = "/Users/zyp/Documents/CUEE/4764 IOT/project/coastal-glass-437800-e9-c0080f90e4ce.json"
credentials = service_account.Credentials.from_service_account_file(CREDENTIALS_FILE)
vision_client = vision.ImageAnnotatorClient(credentials=credentials)

openai.api_key = 'your_key_here'

class WSClient:
    def __init__(self):
        self.ws = None
        self.connected = False
        self.message_queue = Queue()
        self.connect()
        self.start_send_thread()
    
    def connect(self):
        try:
            self.ws = websocket.create_connection(WS_URL)
            self.connected = True
            print(f"Connected to WebSocket server at {WS_URL}")
        except Exception as e:
            print(f"Error connecting to WebSocket: {e}")
            self.connected = False
    
    def start_send_thread(self):
        self.send_thread = threading.Thread(target=self._send_message_worker, daemon=True)
        self.send_thread.start()
    
    def _send_message_worker(self):
        while True:
            try:
                message = self.message_queue.get()
                if message is None:
                    break
                if not self.connected:
                    self.connect()
                if self.connected:
                    self.ws.send(message)
                    print(f"Sent via WebSocket: {message}")
                else:
                    print("Failed to send message: not connected")
                time.sleep(0.1)
            except Exception as e:
                print(f"Error in send thread: {e}")
                self.connected = False
    
    def send_message(self, message):
        self.message_queue.put(message)
    
    def close(self):
        self.message_queue.put(None)
        if self.ws:
            try:
                self.ws.close()
            except Exception as e:
                print(f"Error closing connection: {e}")
        self.connected = False

class SharedState:
    def __init__(self):
        self.is_running = False
        self.last_image = None
        self.last_result = None
        self.last_text = None
        self.last_waste_text = None
        self.ws_client = WSClient()
        self.user_identity = None
        self.is_recording = False
        self.stop_requested = False
        self.last_close_status = None
        self.waiting_for_close_event = False
        self.has_received_image = False
        self.last_item_disposed = None
        self.last_item_class = None

state = SharedState()

def stop_recording():
    state.stop_requested = True
    return "Stop recording requested."

def transcribe_audio(audio_file):
    try:
        print("Transcribing audio...")
        result = whisper_model.transcribe(audio_file)
        return result["text"]
    except Exception as e:
        print(f"Error in transcription: {e}")
        return None

def analyze_identity(transcript):
    try:
        print("Analyzing identity from transcript...")
        prompt = f"""
The following text is a noisy speech transcription that may contain extra words or slightly corrupted phrases, but it usually includes the person's name and/or user ID.
Your tasks:
1. Identify and extract the person's name and/or user ID from the given text.
2. If the identified name contains non-English letters (e.g., Chinese characters), please transliterate or romanize them into plain English letters.
3. If you can identify a name, output "Name: [extracted name]"
4. If you can identify a numeric user ID, output "ID: [extracted number]"
5. If both found, output both lines
6. If neither is found, return "Unknown"

Speech content: {transcript}
        """.strip()

        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are an identity analysis assistant."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )

        identity = response.choices[0].message.content.strip()
        print(f"Identified user: {identity}")
        return identity
    except Exception as e:
        print(f"Error in identity analysis: {e}")
        return "Unknown"

def process_identity(identity_result):
    lines = identity_result.split('\n')
    recognized_name = None
    recognized_id = None

    if "Unknown" in identity_result:
        return "Unknown"

    for line in lines:
        line = line.strip()
        if line.lower().startswith("name:"):
            recognized_name = line.split(":",1)[1].strip().lower()
        elif line.lower().startswith("id:"):
            recognized_id_str = line.split(":",1)[1].strip()
            try:
                recognized_id = int(recognized_id_str)
            except:
                pass

    if recognized_name is None and recognized_id is None:
        return "Unknown"

    user_record = get_user_by_name(recognized_name)
    if not user_record:
        if recognized_id is None:
            recognized_id = 1000 # fallback if no ID provided
        create_user(recognized_name, recognized_id)

    result_lines = []
    if recognized_name is not None:
        result_lines.append(f"Name: {recognized_name}")
    if recognized_id is not None:
        result_lines.append(f"ID: {recognized_id}")
    return "\n".join(result_lines)

def classify_waste(items):
    excluded_items = ['finger','fingernail','hand','skin','technology','photograph',
                      'picture','image','photo','display','screen','snapshot',
                      'photography','text','font','line','symbol']
    filtered_items = [item for item in items if item.lower() not in excluded_items]

    prompt = f"""You are a waste classification assistant.
Which category do these items belong to: recyclable waste or non-recyclable waste?
One item per line "Item - Category".
If bottles or tissues detected, prioritize them.
Ignore colors.

{', '.join(filtered_items)}"""

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role":"system","content":"You are a waste classification assistant."},
                {"role":"user","content":prompt}
            ],
            temperature=0.7
        )
        response_content = response.choices[0].message.content.strip()
        classifications = []
        for line in response_content.split('\n'):
            if ' - ' in line:
                item, category = line.split(' - ')
                item=item.strip()
                category=category.strip()
                if category.lower() not in ["recyclable waste","non-recyclable waste"]:
                    category="Non-Recyclable Waste"
                classifications.append({"item":item,"category":category})
        return classifications
    except Exception as e:
        print(f"Error in waste classification: {e}")
        return []

def analyze_image_with_google_vision(image_path):
    print(f"Analyzing image with Google Vision: {image_path}")
    with io.open(image_path,'rb') as image_file:
        content=image_file.read()
        image=vision.Image(content=content)
    response=vision_client.label_detection(image=image)
    labels=response.label_annotations
    results=[]
    for label in labels:
        results.append({"description":label.description,"score":round(label.score*100,2)})
    return results

def process_image(image):
    try:
        timestamp=datetime.now().strftime('%Y%m%d_%H%M%S')
        original_filename=os.path.join(UPLOAD_FOLDER,f"original_{timestamp}.jpg")
        cv2.imwrite(original_filename,image)

        results = model(source=original_filename, conf=0.5)
        detections = results[0].boxes if results else []

        if detections and len(detections)>0:
            # YOLO success
            items=[]
            annotated_image=image.copy()
            for box in detections:
                class_id=int(box.cls)
                confidence=float(box.conf)
                x1,y1,x2,y2=map(int,box.xyxy[0].tolist())
                items.append(model.names[class_id])
                cv2.rectangle(annotated_image,(x1,y1),(x2,y2),(0,255,0),2)
                label=f"{model.names[class_id]} {confidence:.2f}"
                cv2.putText(annotated_image,label,(x1,y1-10),cv2.FONT_HERSHEY_SIMPLEX,0.8,(0,255,0),2)

            classifications=classify_waste(items)
            state.last_image=image
            state.last_result=annotated_image
            yolo_text="YOLO detection results:\n"+ "\n".join(items)
            state.last_text=yolo_text

            best_box=max(detections,key=lambda b:float(b.conf))
            best_class_id=int(best_box.cls)
            best_item_name=model.names[best_class_id]

            best_item_class=None
            for c in classifications:
                if c['item'].lower().replace(" ","_")==best_item_name.lower().replace(" ","_"):
                    best_item_class=c['category']
                    break
            if not best_item_class:
                best_item_class="Non-Recyclable Waste"

            warning_message=""
            if state.user_identity and state.user_identity!="Unknown":
                user_name_line=[l for l in state.user_identity.split('\n') if l.lower().startswith("name:")]
                if user_name_line:
                    recognized_user_name=user_name_line[0].split(":",1)[1].strip().lower()
                    user_record=get_user_by_name(recognized_user_name)
                    if user_record:
                        reminder_items=user_record["reminder_items"]
                        if best_item_name.lower() in reminder_items:
                            warning_message=f"warning: {best_item_name}: please note it is {best_item_class}"

            waste_text_lines=["Waste Classification Results:"]
            for c in classifications:
                waste_text_lines.append(f"{c['item']} - {c['category']}")
            if warning_message:
                waste_text_lines.append(warning_message)
            state.last_waste_text="\n".join(waste_text_lines)

            msg_to_send=f"{best_item_name}:{best_item_class}"
            if warning_message:
                msg_to_send+=";warning"
            state.ws_client.send_message(msg_to_send)

            state.last_item_disposed=best_item_name
            state.last_item_class=best_item_class
        else:
            # YOLO no result, use Vision
            vision_labels=analyze_image_with_google_vision(original_filename)
            if vision_labels:
                best_label=max(vision_labels, key=lambda l:l['score'])
                best_item_name=best_label['description']
                items=[l['description'] for l in vision_labels]
                classifications=classify_waste(items)
                vision_result=image.copy()
                y_position=30
                for lbl in vision_labels:
                    txt=f"{lbl['description']}: {lbl['score']}%"
                    cv2.putText(vision_result,txt,(10,y_position),cv2.FONT_HERSHEY_SIMPLEX,0.7,(0,255,0),2)
                    y_position+=30

                state.last_image=image
                state.last_result=vision_result
                state.last_text="Google Vision Detection Results:\n"+ "\n".join([f"{l['description']}: {l['score']}%" for l in vision_labels])

                best_item_class=None
                for c in classifications:
                    if c['item'].lower().replace(" ","_")==best_item_name.lower().replace(" ","_"):
                        best_item_class=c['category']
                        break
                if not best_item_class:
                    best_item_class="Non-Recyclable Waste"

                warning_message=""
                if state.user_identity and state.user_identity!="Unknown":
                    user_name_line=[l for l in state.user_identity.split('\n') if l.lower().startswith("name:")]
                    if user_name_line:
                        recognized_user_name=user_name_line[0].split(":",1)[1].strip().lower()
                        user_record=get_user_by_name(recognized_user_name)
                        if user_record:
                            reminder_items=user_record["reminder_items"]
                            if best_item_name.lower() in reminder_items:
                                warning_message=f"warning: {best_item_name}: please note it is {best_item_class}"

                waste_text_lines=["Waste Classification Results:"]
                for c in classifications:
                    waste_text_lines.append(f"{c['item']} - {c['category']}")
                if warning_message:
                    waste_text_lines.append(warning_message)
                state.last_waste_text="\n".join(waste_text_lines)

                msg_to_send=f"{best_item_name}:{best_item_class}"
                if warning_message:
                    msg_to_send+=";warning"
                state.ws_client.send_message(msg_to_send)

                state.last_item_disposed=best_item_name
                state.last_item_class=best_item_class
            else:
                best_item_name="unknown_object"
                best_item_class="Non-Recyclable Waste"

                state.last_image=image
                state.last_result=image.copy()
                state.last_text="No object detected"
                state.last_waste_text="No waste classification results"

                state.ws_client.send_message(f"{best_item_name}:{best_item_class}")
                state.last_item_disposed=best_item_name
                state.last_item_class=best_item_class

        state.has_received_image=True
        state.waiting_for_close_event=True

        return {'status':'success','message':'Image processed and best item info sent.'}

    except Exception as e:
        print(f"Error processing image: {str(e)}")
        return {'status':'error','message':str(e)}

@app.route('/distance', methods=['POST'])
def receive_distance():
    try:
        data=request.get_json(force=True)
        status=data.get("status",None)
        if status is not None:
            state.last_close_status=status
            if state.waiting_for_close_event and (status==1 or status==2):
                user_identity=state.user_identity
                user_id_num=None
                user_name=None
                user_score_display="invalid"
                user_str="user_unknown"

                if user_identity and user_identity!="Unknown":
                    for line in user_identity.split('\n'):
                        if line.lower().startswith("id:"):
                            line_id=line.split(':',1)[1].strip()
                            try:
                                user_id_num=int(line_id)
                            except:
                                pass
                        if line.lower().startswith("name:"):
                            user_name=line.split(":",1)[1].strip().lower()

                user_record=None
                if user_name:
                    user_record=get_user_by_name(user_name)

                if state.last_item_class is None:
                    correct="incorrect"
                else:
                    if status==1:
                        correct="correct" if state.last_item_class.lower()=="recyclable waste" else "incorrect"
                    elif status==2:
                        correct="correct" if state.last_item_class.lower()=="non-recyclable waste" else "incorrect"
                    else:
                        correct="incorrect"

                if user_record:
                    old_score=user_record["score"]
                    old_times=user_record["complete_times"]
                    reminder_items=user_record["reminder_items"]
                    if old_score is None:
                        # first disposal
                        new_score=100.0 if correct=="correct" else 0.0
                        new_times=1
                    else:
                        # subsequent disposal
                        if correct=="correct":
                            new_score=(old_score*old_times+100)/(old_times+1)
                        else:
                            new_score=(old_score*old_times)/(old_times+1)
                        new_score=round(new_score,3)
                        new_times=old_times+1

                    if correct=="incorrect":
                        item_name_lower=(state.last_item_disposed or "").lower()
                        if item_name_lower and item_name_lower not in reminder_items:
                            reminder_items.append(item_name_lower)

                    update_user_score_and_times(user_record['name'],new_score,new_times)
                    update_user_reminder_items(user_record['name'],reminder_items)

                    user_score_display=str(round(new_score,3))
                    user_str=f"user{user_record['id']} name_{user_record['name']}"
                else:
                    # unknown user
                    # first disposal unknown user means invalid score
                    # no database update
                    user_score_display="invalid"

                user_msg=f"{user_str} disposal_{correct} current_score_{user_score_display}"
                state.ws_client.send_message(user_msg)

                if state.last_waste_text is None:
                    state.last_waste_text=""
                state.last_waste_text+=f"\nDisposal: {correct}\nScore: {user_score_display}"

                state.is_running=False
                state.waiting_for_close_event=False

            return jsonify({'status':'success','message':'Status data received'}),200
        else:
            return jsonify({'status':'error','message':'Invalid data'}),400
    except Exception as e:
        print(f"Error processing distance data: {str(e)}")
        return jsonify({'status':'error','message':str(e)}),500

@app.route('/image',methods=['POST'])
def receive_image():
    if not state.is_running:
        return jsonify({'status':'error','message':'System not running'}),403

    if not state.user_identity or state.user_identity=="Unknown":
        return jsonify({'status':'error','message':"User identity not recognized yet."}),403

    if state.has_received_image:
        return jsonify({'status':'error','message':'Image already received and processed for this session'}),403

    print("Receiving image from ESP32-CAM...")
    image_data=request.data
    nparr=np.frombuffer(image_data,np.uint8)
    image=cv2.imdecode(nparr,cv2.IMREAD_COLOR)

    if image is None:
        return jsonify({'status':'error','message':"Invalid image format"}),400

    result=process_image(image)
    return jsonify(result)

@app.route('/test',methods=['GET'])
def test():
    return 'Server is running!',200

def start_detection():
    state.is_running=True
    state.user_identity=None
    state.last_image=None
    state.last_result=None
    state.last_text=None
    state.last_waste_text=None
    state.waiting_for_close_event=False
    state.has_received_image=False
    state.last_item_disposed=None
    state.last_item_class=None
    return None,None,"System started. Please start recording to identify the user ID...","",""

def record_and_identify():
    if not state.is_running:
        yield "Please start the system first.","",""
        return

    state.stop_requested=False
    state.is_recording=True

    audio_data=sd.rec(int(RECORDING_DURATION*SAMPLE_RATE),samplerate=SAMPLE_RATE,channels=CHANNELS)
    start_time=time.time()
    while True:
        elapsed=time.time()-start_time
        if elapsed>=RECORDING_DURATION or state.stop_requested:
            break
        remaining=RECORDING_DURATION-elapsed
        yield f"Recording... {int(remaining)} seconds remaining.","",""
        time.sleep(1)

    sd.stop()

    actual_duration=time.time()-start_time
    recorded_samples=int(actual_duration*SAMPLE_RATE)
    if recorded_samples<=0:
        state.is_recording=False
        yield "No valid audio recorded.","","Unknown"
        state.has_received_image=False
        return

    if not os.path.exists(AUDIO_FOLDER):
        os.makedirs(AUDIO_FOLDER)
    timestamp=datetime.now().strftime('%Y%m%d_%H%M%S')
    filename=os.path.join(AUDIO_FOLDER,f"recording_{timestamp}.wav")
    sf.write(filename,audio_data[:recorded_samples],SAMPLE_RATE)

    state.is_recording=False
    yield "Recording finished, transcribing...","",""

    transcript=transcribe_audio(filename)

    if transcript and transcript.strip():
        raw_identity=analyze_identity(transcript)
        identity_processed=process_identity(raw_identity)
        state.user_identity=identity_processed
        yield ("User identity recognized." if identity_processed!="Unknown" else "Unknown user"), transcript, state.user_identity
    else:
        state.user_identity="Unknown"
        yield "Recognition failed: Unknown user", transcript if transcript else "", "Unknown"

    state.has_received_image=False

def get_latest_result():
    user_id_display=f"User Identity: {state.user_identity if state.user_identity else 'Not recognized'}"

    if state.last_close_status is not None:
        close_text=f"Ultrasonic status: {'Object detected close' if state.last_close_status in [1,2] else 'No close object detected'}"
    else:
        close_text="No ultrasonic data"

    if state.last_image is None:
        return None,None,f"{user_id_display}\nWaiting for ESP32-CAM image...\n{close_text}","",None

    detection_text=f"{user_id_display}\n\n{state.last_text}\n\n{close_text}"
    return state.last_image, state.last_result, detection_text, state.last_waste_text, None

def cleanup():
    if hasattr(state,'ws_client'):
        state.ws_client.close()

def run_flask():
    app.run(host='0.0.0.0',port=12345,debug=False,use_reloader=False)

with gr.Blocks() as demo:
    gr.Markdown("# ESP32-CAM Image Detection and Waste Classification System (Enhanced with YOLOv8 and DB)")

    with gr.Row():
        start_btn=gr.Button("Start System")
        stop_btn=gr.Button("Stop Recording")

    with gr.Row():
        with gr.Column():
            record_btn=gr.Button("Start Recording to Identify User ID")
            identity_status=gr.Textbox(label="Status/Progress",lines=2)
            transcript_output=gr.Textbox(label="Transcription Result",lines=3)
            identity_output=gr.Textbox(label="Recognized User ID",lines=1)
        with gr.Column():
            input_image=gr.Image(label="Received Image")
            output_image=gr.Image(label="Detection Results")

    with gr.Row():
        text_output=gr.Textbox(label="Detection and Distance Information",lines=5)
        waste_output=gr.Textbox(label="Waste Classification Results",lines=5)

    start_btn.click(
        fn=start_detection,
        inputs=[],
        outputs=[input_image,output_image,text_output,waste_output,transcript_output]
    )

    record_event=record_btn.click(
        fn=record_and_identify,
        inputs=[],
        outputs=[identity_status,transcript_output,identity_output],
        queue=True
    )

    stop_btn.click(
        fn=stop_recording,
        inputs=[],
        outputs=identity_status
    )

    demo.load(
        fn=get_latest_result,
        inputs=[],
        outputs=[input_image,output_image,text_output,waste_output],
        every=1
    )

if __name__=="__main__":
    try:
        import atexit
        atexit.register(cleanup)

        flask_thread=threading.Thread(target=run_flask)
        flask_thread.daemon=True
        flask_thread.start()
        print("Flask server started on port 12345")

        demo.queue()
        print("Starting Gradio interface...")
        demo.launch(
            server_name="0.0.0.0",
            server_port=7860,
            share=False,
            debug=True
        )
    except Exception as e:
        print(f"Error starting the server: {e}")
        if hasattr(state,'ws_client'):
            state.ws_client.close()