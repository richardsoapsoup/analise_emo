import threading
import time
from fer import FER
from datetime import datetime
import uuid
import math
import requests
import cv2
import os


MIN_FACE_SIZE = 80
DISTANCIA_MAX = 80
TEMPO_MAX_INATIVO = 3
COOLDOWN_RAIVA_EXTREMA = 10

class EmotionDetector:
    def __init__(self, get_frame, api_url="http://127.0.0.1:8000/evento", mtcnn=True, poll_interval=0.5, update_detections_cb=None):
        
        self.get_frame = get_frame
        self.api_url = api_url
        self.mtcnn = mtcnn
        self.poll_interval = poll_interval
        self.update_detections_cb = update_detections_cb 

        self._thread = None
        self._stop_event = threading.Event()
        self._running = False

        
        self.detector = FER(mtcnn=self.mtcnn)

        
        self.rostos_detectados = []
        self.eventos_negativos = []
        self.historico_humor = []
        self.ultimo_registro_raiva_extrema = 0

    def start(self):
        if self._running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._running = True
        print("[DETECTOR] Thread do detector iniciada.")

    def stop(self):
        if not self._running:
            return
        self._stop_event.set()
        self._thread.join(timeout=3)
        self._running = False
        print("[DETECTOR] Detector parado.")

    def is_running(self):
        return self._running

    
    def distancia(self, p1, p2):
        return math.sqrt((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)

    def calcular_media_humor(self):
        total = len(self.historico_humor)
        if total == 0:
            return "Indefinido"
        positivo = sum(1 for emo in self.historico_humor if emo == "happy")
        negativo = sum(1 for emo in self.historico_humor if emo in ["angry", "sad"])
        if positivo / total > 0.5:
            return "Ambiente Positivo"
        elif negativo / total > 0.5:
            return "Ambiente Negativo"
        else:
            return "Ambiente Neutro"

    def enviar_evento_backend(self, doc):
        try:
            payload = {
                "id_evento": doc["id_evento"],
                "timestamp": doc["timestamp"],
                "camera_id": doc["camera_id"],
                "expressao_dominante": doc["expressao_dominante"],
                "pontuacao": float(doc["pontuacao"]),
                "media_emocoes": float(doc["media_emocoes"]),
                "comportamento": doc["comportamento"],
                "pessoas_unicas_ate_agora": int(doc["pessoas_unicas_ate_agora"])
            }
            r = requests.post(self.api_url, json=payload, timeout=3)
            if r.status_code == 200:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] [API] Evento enviado: {payload['expressao_dominante']} ({payload['comportamento']})")
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] [API] Erro {r.status_code}: {r.text}")
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [API] Falha ao enviar evento: {e}")

    def _run(self):
        print("[DETECTOR] Loop de detecção iniciando...")
        while not self._stop_event.is_set():
            frame = self.get_frame()
            if frame is None:
                time.sleep(0.2)
                continue

            try:
                results = self.detector.detect_emotions(frame)
                
                
                if self.update_detections_cb:
                    self.update_detections_cb(results)
               

            except Exception as e:
                print("[DETECTOR] Erro ao detectar emoções:", e)
                time.sleep(self.poll_interval)
                continue

            agora = time.time()
            novo_rostos = []
            alerta_raiva = False

            
            self.rostos_detectados = [(centro, t) for centro, t in self.rostos_detectados if agora - t < TEMPO_MAX_INATIVO]

            for result in results:
                (x, y, w, h) = result["box"]
                if w < MIN_FACE_SIZE or h < MIN_FACE_SIZE:
                    continue
                centro_atual = (x + w//2, y + h//2)

                rosto_existente = False
                for i, (centro, t) in enumerate(self.rostos_detectados):
                    if self.distancia(centro_atual, centro) < DISTANCIA_MAX:
                        self.rostos_detectados[i] = (centro_atual, agora)
                        rosto_existente = True
                        break

                if not rosto_existente:
                    self.rostos_detectados.append((centro_atual, agora))

                emotions = result["emotions"]
                top_emotion = max(emotions, key=emotions.get)
                score = emotions[top_emotion]

                if top_emotion == "angry" and score > 0.6:
                    comportamento = "potencialmente agressivo"
                elif top_emotion == "sad" and score > 0.6:
                    comportamento = "depressivo"
                elif top_emotion == "happy" and score > 0.6:
                    comportamento = "positivo"
                else:
                    comportamento = "neutro"

                if top_emotion == "angry" and score > 0.8:
                    alerta_raiva = True

                if top_emotion == "angry" and score > 0.9:
                    if agora - self.ultimo_registro_raiva_extrema >= COOLDOWN_RAIVA_EXTREMA:
                        
                        filename = f"imagens_alerta/alerta_raiva_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.jpg"
                        try:
                            
                            if not os.path.exists("imagens_alerta"):
                                os.makedirs("imagens_alerta")
                            cv2.imwrite(filename, frame)
                            print(f"[{datetime.now().strftime('%H:%M:%S')}] [SALVO] Frame de raiva extrema salvo como {filename}")
                        except Exception:
                            pass
                        self.ultimo_registro_raiva_extrema = agora

                if top_emotion in ["angry", "sad"] and score > 0.6:
                    self.eventos_negativos.append(agora)

                doc = {
                    "id_evento": str(uuid.uuid4()),
                    "timestamp": datetime.utcnow().isoformat(),
                    "camera_id": "entrada_1",
                    "expressao_dominante": top_emotion,
                    "pontuacao": round(score, 2),
                    "media_emocoes": round(sum(emotions.values()) / len(emotions), 2),
                    "comportamento": comportamento,
                    "pessoas_unicas_ate_agora": len(self.rostos_detectados)
                }

                
                self.enviar_evento_backend(doc)

                self.historico_humor.append(top_emotion)

            
            agora = time.time()
            ultimos_minuto = [t for t in self.eventos_negativos if agora - t < 60]
            if len(ultimos_minuto) >= 3:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] [ALERTA GERAL] Pico de Stress no Ambiente!")

            if alerta_raiva:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] [ALERTA] Pessoa com Raiva Alta detectada.")

           
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [DETECTOR] Pessoas únicas: {len(self.rostos_detectados)} | Histórico tamanho: {len(self.historico_humor)}")

            time.sleep(self.poll_interval)

        print("[DETECTOR] Loop encerrado.")