
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from datetime import datetime
import threading
import time
import cv2

import numpy as np


from deteccao import EmotionDetector  




from backend.models import EventoEmocao
from backend.database import colecao_eventos 

app = FastAPI(title="API de Monitoramento Emocional")

origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


cap = cv2.VideoCapture(0)
if not cap.isOpened():
    print("[ERROR] Não foi possível abrir a câmera (device 0).")
    


latest_frame = None
frame_lock = threading.Lock()
capture_thread = None
capture_thread_stop = threading.Event()
last_detections = [] 

def capture_loop():
    
    global latest_frame
    while not capture_thread_stop.is_set():
        success, frame = cap.read()
        if not success:
           
            time.sleep(0.2)
            continue
        with frame_lock:
            latest_frame = frame.copy()
       
        time.sleep(0.01)

def start_capture_thread():
    global capture_thread
    if capture_thread is None or not capture_thread.is_alive():
        capture_thread_stop.clear()
        capture_thread = threading.Thread(target=capture_loop, daemon=True)
        capture_thread.start()
        print("[CAPTURE] Capture thread iniciada.")

def stop_capture_thread():
    global capture_thread
    capture_thread_stop.set()
    if capture_thread:
        capture_thread.join(timeout=2)
    print("[CAPTURE] Capture thread parada.")


start_capture_thread()


detector = None  
detector_lock = threading.Lock()


API_EVENT_URL = "http://127.0.0.1:8000/evento"


def set_last_detections(detections):
   
    global last_detections
    last_detections = detections


@app.post("/start_detector")
def start_detector():
    global detector
    with detector_lock:
        if detector and detector.is_running():
            return JSONResponse({"status": "aviso", "mensagem": "Detector já rodando."})
        
        def get_frame():
            with frame_lock:
                if latest_frame is None:
                    return None
                return latest_frame.copy()
        
        
        detector = EmotionDetector(
            get_frame=get_frame, 
            api_url=API_EVENT_URL, 
            update_detections_cb=set_last_detections
        )
        detector.start()
        return {"status": "ok", "mensagem": "Detector iniciado."}

@app.post("/stop_detector")
def stop_detector():
    global detector
    with detector_lock:
        if not detector or not detector.is_running():
            return JSONResponse({"status": "aviso", "mensagem": "Nenhum detector em execução."})
        detector.stop()
        detector = None
        return {"status": "ok", "mensagem": "Detector parado."}


@app.post("/evento")
def receber_evento(evento: EventoEmocao):
    colecao_eventos.insert_one(evento.dict())
    return {"status": "ok", "evento_recebido": evento.dict()}

@app.get("/eventos")
def listar_eventos(limit: int = 10):
    eventos = list(colecao_eventos.find().sort("timestamp", -1).limit(limit))
    for e in eventos:
        e["_id"] = str(e["_id"])
    return eventos


def mjpeg_generator():
    

    global last_detections
    while True:
        with frame_lock:
            frame = None if latest_frame is None else latest_frame.copy()
        if frame is None:
            
            blank = 255 * np.ones((480, 640, 3), dtype=np.uint8)
            ret, buffer = cv2.imencode('.jpg', blank)
            frame_bytes = buffer.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            time.sleep(0.1)
            continue

       
        if last_detections:
            for det in last_detections:
                (x, y, w, h) = det["box"]
                emotion = max(det["emotions"], key=det["emotions"].get)
                color = (0, 255, 0)
                if emotion == "angry":
                    color = (0, 0, 255)
                elif emotion == "sad":
                    color = (255, 0, 0)
                elif emotion == "happy":
                    color = (0, 255, 0)
                else:
                    color = (255, 255, 0)

                cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
                cv2.putText(frame, emotion, (x, y - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)

        
        cv2.putText(frame, datetime.now().strftime("%H:%M:%S"),
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0,255,0), 2)

        ret, buffer = cv2.imencode('.jpg', frame)
        frame_bytes = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
       
        time.sleep(0.033)

@app.get("/video_feed")
def video_feed():
    global detector
    
    with detector_lock:
        if not (detector and detector.is_running()):
            
            try:
                
                def get_frame():
                    with frame_lock:
                        if latest_frame is None:
                            return None
                        return latest_frame.copy()
                
                
                detector = EmotionDetector(
                    get_frame=get_frame, 
                    api_url=API_EVENT_URL,
                    update_detections_cb=set_last_detections
                )
                detector.start()
                print("[VIDEO_FEED] Detector iniciado automaticamente.")
            except Exception as e:
                print("[VIDEO_FEED] Falha ao iniciar detector automaticamente:", e)

    return StreamingResponse(mjpeg_generator(), media_type="multipart/x-mixed-replace; boundary=frame")


@app.on_event("shutdown")
def shutdown_event():
    print("[SHUTDOWN] Encerrando servidor...")
    
    with detector_lock:
        if detector and detector.is_running():
            detector.stop()
    
    try:
        stop_capture_thread()
    except Exception:
        pass
    
    try:
        if cap.isOpened():
            cap.release()
    except Exception:
        pass
    print("[SHUTDOWN] Recursos liberados.")