import threading, time, uuid, math, requests, cv2, os
from datetime import datetime
from fer import FER

try:
    from backend.alerts_service import registrar_alerta_raiva
except ImportError:
    try:
        from alerts_service import registrar_alerta_raiva
    except ImportError:
        registrar_alerta_raiva = None

MIN_FACE_SIZE = 80
DISTANCIA_MAX = 80
TEMPO_MAX_INATIVO = 3
COOLDOWN_RAIVA_EXTREMA = 10

class EmotionDetector:
    def __init__(self, get_frame, api_url='http://127.0.0.1:8000/evento', mtcnn=True,
                 poll_interval=0.5, update_detections_cb=None, camera_id='camera_1',
                 camera_nome='Câmera 1', modo_monitoramento='individual'):
        self.get_frame = get_frame
        self.api_url = api_url
        self.poll_interval = poll_interval
        self.update_detections_cb = update_detections_cb
        self.camera_id = camera_id
        self.camera_nome = camera_nome
        self.modo_monitoramento = modo_monitoramento
        self.detector = FER(mtcnn=mtcnn)
        self.rostos_detectados = []
        self.eventos_negativos = []
        self.historico_humor = []
        self.ultimo_registro_raiva_extrema = 0
        self._thread = None
        self._stop_event = threading.Event()
        self._running = False

    def start(self):
        if self._running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._running = True
        print(f'[DETECTOR] Iniciado: {self.camera_nome}')

    def stop(self):
        self._stop_event.set()
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        self._thread = None
        print(f'[DETECTOR] Parado: {self.camera_nome}')

    def is_running(self):
        return self._running

    def set_modo_monitoramento(self, modo):
        if modo in ['individual', 'sala']:
            self.modo_monitoramento = modo

    def distancia(self, p1, p2):
        return math.sqrt((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)

    def classificar_comportamento(self, emocao, score):
        if emocao == 'angry' and score > 0.6:
            return 'potencialmente agressivo'
        if emocao == 'sad' and score > 0.6:
            return 'depressivo'
        if emocao == 'happy' and score > 0.6:
            return 'positivo'
        return 'neutro'

    def atualizar_rostos(self, results):
        agora = time.time()
        self.rostos_detectados = [(c, t) for c, t in self.rostos_detectados if agora - t < TEMPO_MAX_INATIVO]
        for result in results:
            x, y, w, h = result['box']
            if w < MIN_FACE_SIZE or h < MIN_FACE_SIZE:
                continue
            centro_atual = (x + w // 2, y + h // 2)
            existe = False
            for i, (centro, _) in enumerate(self.rostos_detectados):
                if self.distancia(centro_atual, centro) < DISTANCIA_MAX:
                    self.rostos_detectados[i] = (centro_atual, agora)
                    existe = True
                    break
            if not existe:
                self.rostos_detectados.append((centro_atual, agora))

    def salvar_frame_raiva_extrema(self, frame, score=0.9):
        if registrar_alerta_raiva:
            try:
                registrar_alerta_raiva(self.camera_id, self.camera_nome, score, frame)
            except Exception as e:
                print(f"[ALERTA] Erro ao registrar alerta: {e}")
        else:
            agora = time.time()
            if agora - self.ultimo_registro_raiva_extrema < COOLDOWN_RAIVA_EXTREMA:
                return
            self.ultimo_registro_raiva_extrema = agora
            os.makedirs('imagens_alerta', exist_ok=True)
            filename = f"imagens_alerta/alerta_raiva_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.jpg"
            cv2.imwrite(filename, frame)

    def enviar_evento_backend(self, doc):
        try:
            r = requests.post(self.api_url, json=doc, timeout=3)
            if r.status_code != 200:
                print('[API] Erro:', r.status_code, r.text)
        except Exception as e:
            print('[API] Falha ao enviar evento:', e)

    def evento_individual(self, result, frame):
        emotions = result['emotions']
        top = max(emotions, key=emotions.get)
        score = emotions[top]
        if top == 'angry' and score >= 0.60:
            self.salvar_frame_raiva_extrema(frame, score)
        return {
            'id_evento': str(uuid.uuid4()),
            'timestamp': datetime.utcnow().isoformat(),
            'camera_id': self.camera_id,
            'camera_nome': self.camera_nome,
            'usuario_id': None,
            'usuario_nome': None,
            'modo_monitoramento': 'individual',
            'expressao_dominante': top,
            'pontuacao': round(float(score), 2),
            'media_emocoes': round(sum(emotions.values()) / len(emotions), 2),
            'comportamento': self.classificar_comportamento(top, score),
            'pessoas_unicas_ate_agora': len(self.rostos_detectados),
        }

    def evento_sala(self, results, frame):
        soma, faces = {}, 0
        for result in results:
            x, y, w, h = result['box']
            if w < MIN_FACE_SIZE or h < MIN_FACE_SIZE:
                continue
            faces += 1
            for emo, score in result['emotions'].items():
                soma[emo] = soma.get(emo, 0) + score
        if faces == 0:
            return None
        medias = {emo: val / faces for emo, val in soma.items()}
        top = max(medias, key=medias.get)
        score = medias[top]
        if top == 'angry' and score >= 0.60:
            self.salvar_frame_raiva_extrema(frame, score)
        return {
            'id_evento': str(uuid.uuid4()),
            'timestamp': datetime.utcnow().isoformat(),
            'camera_id': self.camera_id,
            'camera_nome': self.camera_nome,
            'usuario_id': None,
            'usuario_nome': 'Sala / Ambiente',
            'modo_monitoramento': 'sala',
            'expressao_dominante': top,
            'pontuacao': round(float(score), 2),
            'media_emocoes': round(sum(medias.values()) / len(medias), 2),
            'comportamento': self.classificar_comportamento(top, score),
            'pessoas_unicas_ate_agora': len(self.rostos_detectados),
        }

    def _run(self):
        while not self._stop_event.is_set():
            frame = self.get_frame()
            if frame is None or self._stop_event.is_set():
                time.sleep(0.1)
                continue
            try:
                results = self.detector.detect_emotions(frame)
                if self.update_detections_cb and not self._stop_event.is_set():
                    self.update_detections_cb(results)
            except Exception as e:
                if not self._stop_event.is_set():
                    print('[DETECTOR] Erro:', e)
                time.sleep(self.poll_interval)
                continue
            if self._stop_event.is_set():
                break
            self.atualizar_rostos(results)
            if self.modo_monitoramento == 'sala':
                evento = self.evento_sala(results, frame)
                if evento and not self._stop_event.is_set():
                    self.enviar_evento_backend(evento)
            else:
                for result in results:
                    if self._stop_event.is_set():
                        break
                    x, y, w, h = result['box']
                    if w >= MIN_FACE_SIZE and h >= MIN_FACE_SIZE:
                        self.enviar_evento_backend(self.evento_individual(result, frame))
            time.sleep(self.poll_interval)
