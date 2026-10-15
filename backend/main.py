from datetime import datetime
import threading, time, cv2, numpy as np
from bson import ObjectId
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
try:
    from backend.models import EventoEmocao, UsuarioCreate, UsuarioUpdate, CameraCreate, CameraUpdate
    from backend.database import colecao_eventos, colecao_usuarios, colecao_cameras
except ImportError:
    from models import EventoEmocao, UsuarioCreate, UsuarioUpdate, CameraCreate, CameraUpdate
    from database import colecao_eventos, colecao_usuarios, colecao_cameras

try:
    from deteccao import EmotionDetector
except ImportError:
    from backend.deteccao import EmotionDetector

app = FastAPI(title='API de Monitoramento Emocional')
app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:5173','http://127.0.0.1:5173'], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])
API_EVENT_URL = 'http://127.0.0.1:8000/evento'

def oid(id):
    try: return ObjectId(id)
    except Exception: raise HTTPException(status_code=400, detail='ID inválido')

def serializar(doc):
    doc['_id'] = str(doc['_id'])
    return doc

def normalizar_origem(origem):
    return int(origem) if isinstance(origem, str) and origem.isdigit() else origem

class CameraRuntime:
    def __init__(self, doc):
        self.camera_id = str(doc['_id'])
        self.nome = doc['nome']
        self.origem = doc['origem']
        self.modo_monitoramento = doc.get('modo_monitoramento', 'individual')
        self.cap = None
        self.latest_frame = None
        self.frame_lock = threading.Lock()
        self.stop_capture = threading.Event()
        self.capture_thread = None
        self.detector = None
        self.detector_lock = threading.Lock()
        self.last_detections = []
        self.active_viewers = 0
        self.viewers_lock = threading.Lock()
        self.release_timer = None

    def abrir(self):
        if self.cap and self.cap.isOpened(): return
        self.cap = cv2.VideoCapture(normalizar_origem(self.origem))

    def iniciar_captura(self):
        if self.capture_thread and self.capture_thread.is_alive(): return
        self.abrir()
        self.stop_capture.clear()
        self.capture_thread = threading.Thread(target=self.loop_captura, daemon=True)
        self.capture_thread.start()

    def loop_captura(self):
        while not self.stop_capture.is_set():
            if not self.cap or not self.cap.isOpened():
                time.sleep(0.5)
                if not self.stop_capture.is_set():
                    self.abrir()
                continue
            ok, frame = self.cap.read()
            if not ok:
                time.sleep(0.1); continue
            with self.frame_lock:
                self.latest_frame = frame.copy()
            time.sleep(0.01)

    def get_frame(self):
        with self.frame_lock:
            return None if self.latest_frame is None else self.latest_frame.copy()

    def set_detections(self, detections):
        self.last_detections = detections

    def iniciar_detector(self):
        with self.detector_lock:
            self.iniciar_captura()
            if self.detector and self.detector.is_running(): return
            self.detector = EmotionDetector(self.get_frame, API_EVENT_URL, update_detections_cb=self.set_detections, camera_id=self.camera_id, camera_nome=self.nome, modo_monitoramento=self.modo_monitoramento)
            self.detector.start()

    def parar_detector(self):
        with self.detector_lock:
            if self.detector and self.detector.is_running(): self.detector.stop()
            self.detector = None

    def alterar_modo(self, modo):
        self.modo_monitoramento = modo
        if self.detector: self.detector.set_modo_monitoramento(modo)

    def fechar(self):
        with self.viewers_lock:
            if self.release_timer:
                self.release_timer.cancel()
                self.release_timer = None
        self.parar_detector()
        self.stop_capture.set()
        if self.capture_thread and self.capture_thread.is_alive():
            self.capture_thread.join(timeout=1.5)
        self.capture_thread = None
        with self.frame_lock:
            if self.cap:
                if self.cap.isOpened():
                    self.cap.release()
                self.cap = None
            self.latest_frame = None
        print(f"[CAMERA] Câmera '{self.nome}' encerrada e webcam liberada com sucesso.")

    def adicionar_visualizador(self):
        with self.viewers_lock:
            if self.release_timer:
                self.release_timer.cancel()
                self.release_timer = None
            self.active_viewers += 1
            print(f"[CAMERA] Visualizador conectado ({self.nome}). Total de visualizadores ativos: {self.active_viewers}")
            self.iniciar_detector()

    def remover_visualizador(self):
        with self.viewers_lock:
            self.active_viewers = max(0, self.active_viewers - 1)
            print(f"[CAMERA] Visualizador desconectado ({self.nome}). Restantes: {self.active_viewers}")
            if self.active_viewers == 0:
                self._agendar_fechamento()

    def _agendar_fechamento(self):
        if self.release_timer:
            self.release_timer.cancel()
        self.release_timer = threading.Timer(2.0, self._desligar_se_sem_visualizadores)
        self.release_timer.daemon = True
        self.release_timer.start()

    def _desligar_se_sem_visualizadores(self):
        with self.viewers_lock:
            if self.active_viewers == 0:
                print(f"[CAMERA] Nenhum visualizador ativo há 2 segundos. Desligando hardware da câmera '{self.nome}'...")
                self.fechar()

    def renderizar(self):
        frame = self.get_frame()
        if frame is None:
            frame = 255 * np.ones((480, 640, 3), dtype=np.uint8)
            cv2.putText(frame, f'Sem sinal: {self.nome}', (40, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0,0,255), 2)
            return frame
        for det in self.last_detections:
            x, y, w, h = det['box']
            emo = max(det['emotions'], key=det['emotions'].get)
            color = (255,255,0)
            if emo == 'angry': color = (0,0,255)
            elif emo == 'sad': color = (255,0,0)
            elif emo == 'happy': color = (0,255,0)
            cv2.rectangle(frame, (x,y), (x+w,y+h), color, 2)
            cv2.putText(frame, emo, (x, y-10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
        cv2.putText(frame, self.nome, (10,30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,255,0), 2)
        return frame

runtimes = {}
runtimes_lock = threading.Lock()

def runtime_camera(camera_id):
    with runtimes_lock:
        doc = colecao_cameras.find_one({'_id': oid(camera_id)})
        if not doc: raise HTTPException(status_code=404, detail='Câmera não encontrada')
        if camera_id not in runtimes: runtimes[camera_id] = CameraRuntime(doc)
        return runtimes[camera_id]

@app.get('/')
def home(): return {'status':'ok'}

@app.post('/usuarios')
def criar_usuario(usuario: UsuarioCreate):
    doc = usuario.dict(); doc['created_at'] = datetime.utcnow(); doc['updated_at'] = datetime.utcnow()
    res = colecao_usuarios.insert_one(doc); doc['_id'] = str(res.inserted_id); return doc

@app.get('/usuarios')
def listar_usuarios(ativos: bool | None = None):
    filtro = {} if ativos is None else {'ativo': ativos}
    return [serializar(u) for u in colecao_usuarios.find(filtro).sort('nome', 1)]

@app.put('/usuarios/{usuario_id}')
def atualizar_usuario(usuario_id: str, usuario: UsuarioUpdate):
    dados = {k:v for k,v in usuario.dict().items() if v is not None}
    dados['updated_at'] = datetime.utcnow()
    r = colecao_usuarios.update_one({'_id': oid(usuario_id)}, {'$set': dados})
    if not r.matched_count: raise HTTPException(status_code=404, detail='Usuário não encontrado')
    return serializar(colecao_usuarios.find_one({'_id': oid(usuario_id)}))

@app.delete('/usuarios/{usuario_id}')
def remover_usuario(usuario_id: str):
    r = colecao_usuarios.update_one({'_id': oid(usuario_id)}, {'$set': {'ativo': False, 'updated_at': datetime.utcnow()}})
    if not r.matched_count: raise HTTPException(status_code=404, detail='Usuário não encontrado')
    return {'status':'ok'}

@app.post('/cameras')
def criar_camera(camera: CameraCreate):
    doc = camera.dict(); doc['created_at'] = datetime.utcnow(); doc['updated_at'] = datetime.utcnow()
    res = colecao_cameras.insert_one(doc); doc['_id'] = str(res.inserted_id); return doc

@app.get('/cameras')
def listar_cameras(): return [serializar(c) for c in colecao_cameras.find().sort('created_at', 1)]

@app.put('/cameras/{camera_id}')
def atualizar_camera(camera_id: str, camera: CameraUpdate):
    dados = {k:v for k,v in camera.dict().items() if v is not None}
    dados['updated_at'] = datetime.utcnow()
    r = colecao_cameras.update_one({'_id': oid(camera_id)}, {'$set': dados})
    if not r.matched_count: raise HTTPException(status_code=404, detail='Câmera não encontrada')
    with runtimes_lock:
        rt = runtimes.pop(camera_id, None)
        if rt: rt.fechar()
    return serializar(colecao_cameras.find_one({'_id': oid(camera_id)}))

@app.delete('/cameras/{camera_id}')
def remover_camera(camera_id: str):
    r = colecao_cameras.delete_one({'_id': oid(camera_id)})
    if not r.deleted_count: raise HTTPException(status_code=404, detail='Câmera não encontrada')
    with runtimes_lock:
        rt = runtimes.pop(camera_id, None)
        if rt: rt.fechar()
    return {'status':'ok'}

@app.post('/cameras/{camera_id}/start')
def iniciar(camera_id: str):
    rt = runtime_camera(camera_id)
    rt.iniciar_detector()
    return {'status': 'ok'}

@app.post('/cameras/{camera_id}/stop')
def parar(camera_id: str):
    rt = runtime_camera(camera_id)
    rt.parar_detector()
    with rt.viewers_lock:
        if rt.active_viewers == 0:
            rt.fechar()
    return {'status': 'ok'}

@app.post('/cameras/{camera_id}/release')
def liberar_camera(camera_id: str):
    with runtimes_lock:
        rt = runtimes.get(camera_id)
        if rt:
            rt.fechar()
    return {'status': 'ok'}

@app.put('/cameras/{camera_id}/modo')
def modo(camera_id: str, modo_monitoramento: str):
    if modo_monitoramento not in ['individual','sala']: raise HTTPException(status_code=400, detail='Modo inválido')
    colecao_cameras.update_one({'_id': oid(camera_id)}, {'$set': {'modo_monitoramento': modo_monitoramento, 'updated_at': datetime.utcnow()}})
    runtime_camera(camera_id).alterar_modo(modo_monitoramento)
    return {'status':'ok', 'modo_monitoramento': modo_monitoramento}

def gerar_mjpeg(camera_id):
    rt = runtime_camera(camera_id)
    rt.adicionar_visualizador()
    try:
        while True:
            frame = rt.renderizar()
            ok, buffer = cv2.imencode('.jpg', frame)
            if ok:
                yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n'
            time.sleep(0.04)
    except (GeneratorExit, Exception):
        pass
    finally:
        rt.remover_visualizador()

@app.get('/video_feed/{camera_id}')
def video_feed(camera_id: str): return StreamingResponse(gerar_mjpeg(camera_id), media_type='multipart/x-mixed-replace; boundary=frame')

@app.post('/evento')
def receber_evento(evento: EventoEmocao):
    doc = evento.dict()
    res = colecao_eventos.insert_one(doc)
    doc['_id'] = str(res.inserted_id)
    return {'status':'ok', 'evento_recebido': doc}

@app.get('/eventos')
def listar_eventos(limit: int = 10, camera_id: str | None = None, usuario_id: str | None = None):
    filtro = {}
    if camera_id: filtro['camera_id'] = camera_id
    if usuario_id: filtro['usuario_id'] = usuario_id
    return [serializar(e) for e in colecao_eventos.find(filtro).sort('timestamp', -1).limit(limit)]

@app.get('/relatorios/resumo')
def resumo():
    return {
        'total_eventos': colecao_eventos.count_documents({}),
        'total_alertas': colecao_eventos.count_documents({'comportamento': {'$in': ['potencialmente agressivo','agressivo']}}),
        'total_cameras': colecao_cameras.count_documents({}),
        'total_usuarios': colecao_usuarios.count_documents({'ativo': True}),
        'por_emocao': [{'name': i['_id'] or 'Indefinido', 'value': i['total']} for i in colecao_eventos.aggregate([{'$group': {'_id':'$expressao_dominante','total':{'$sum':1}}}])],
        'por_comportamento': [{'name': i['_id'] or 'Indefinido', 'value': i['total']} for i in colecao_eventos.aggregate([{'$group': {'_id':'$comportamento','total':{'$sum':1}}}])],
        'por_camera': [{'name': i['_id'] or 'Sem nome', 'value': i['total']} for i in colecao_eventos.aggregate([{'$group': {'_id':'$camera_nome','total':{'$sum':1}}}])],
    }

@app.get('/relatorios/usuarios')
def relatorio_usuarios():
    usuarios = list(colecao_usuarios.find({'ativo': True}).sort('nome', 1))
    resposta = []
    for u in usuarios:
        uid = str(u['_id'])
        eventos = list(colecao_eventos.find({'usuario_id': uid}).sort('timestamp', -1).limit(200))
        total = len(eventos)
        alertas = sum(1 for e in eventos if e.get('comportamento') in ['potencialmente agressivo','agressivo'])
        positivos = sum(1 for e in eventos if e.get('comportamento') == 'positivo')
        media = round(sum(float(e.get('pontuacao', 0)) for e in eventos) / total, 2) if total else 0
        resposta.append({'_id': uid, 'nome': u.get('nome'), 'email': u.get('email'), 'departamento': u.get('departamento'), 'total_eventos': total, 'alertas': alertas, 'positivos': positivos, 'pontuacao_media': media, 'ultimo_evento': eventos[0]['timestamp'] if eventos else None, 'status': 'warning' if alertas >= 3 else 'normal'})
    return resposta

@app.on_event('shutdown')
def shutdown():
    with runtimes_lock:
        for rt in runtimes.values(): rt.fechar()
        runtimes.clear()
