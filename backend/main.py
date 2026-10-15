from datetime import datetime
import threading, time, cv2, numpy as np
from bson import ObjectId
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import os
from fastapi.staticfiles import StaticFiles

try:
    from backend.models import EventoEmocao, UsuarioCreate, UsuarioUpdate, CameraCreate, CameraUpdate
    from backend.database import colecao_eventos, colecao_usuarios, colecao_cameras, colecao_alertas, colecao_config_alertas
    from backend.alerts_service import (
        obter_config_alertas, atualizar_config_alertas,
        enviar_email_alerta, registrar_alerta_raiva, ALERTA_IMG_DIR
    )
except ImportError:
    from models import EventoEmocao, UsuarioCreate, UsuarioUpdate, CameraCreate, CameraUpdate
    from database import colecao_eventos, colecao_usuarios, colecao_cameras, colecao_alertas, colecao_config_alertas
    from alerts_service import (
        obter_config_alertas, atualizar_config_alertas,
        enviar_email_alerta, registrar_alerta_raiva, ALERTA_IMG_DIR
    )

try:
    from backend.deteccao import EmotionDetector
except ImportError:
    from deteccao import EmotionDetector

app = FastAPI(title='API de Monitoramento Emocional')
app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:5173','http://127.0.0.1:5173'], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])

os.makedirs(ALERTA_IMG_DIR, exist_ok=True)
app.mount('/imagens_alerta', StaticFiles(directory=ALERTA_IMG_DIR), name='imagens_alerta')

API_EVENT_URL = 'http://127.0.0.1:8000/evento'

def oid(id):
    try: return ObjectId(id)
    except Exception: raise HTTPException(status_code=400, detail='ID inválido')

def serializar(doc):
    doc['_id'] = str(doc['_id'])
    return doc

def normalizar_origem(origem):
    if isinstance(origem, int):
        return origem
    if isinstance(origem, str) and origem.strip().isdigit():
        return int(origem.strip())
    return origem

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
        if self.cap and self.cap.isOpened():
            return
        src = normalizar_origem(self.origem)
        if isinstance(src, int):
            self.cap = cv2.VideoCapture(src, cv2.CAP_DSHOW)
            if not self.cap or not self.cap.isOpened():
                self.cap = cv2.VideoCapture(src)
        else:
            self.cap = cv2.VideoCapture(src)
        if self.cap and self.cap.isOpened():
            print(f"[CAMERA] Hardware aberto com sucesso: '{self.nome}' (origem: {self.origem})")
        else:
            print(f"[CAMERA] AVISO: Não foi possível abrir dispositivo: '{self.nome}' (origem: {self.origem})")

    def iniciar_captura(self):
        self.stop_capture.clear()
        if self.capture_thread and self.capture_thread.is_alive():
            if not self.cap or not self.cap.isOpened():
                self.abrir()
            return
        self.abrir()
        self.capture_thread = threading.Thread(target=self.loop_captura, daemon=True)
        self.capture_thread.start()

    def loop_captura(self):
        while not self.stop_capture.is_set():
            if not self.cap or not self.cap.isOpened():
                time.sleep(0.3)
                if not self.stop_capture.is_set():
                    self.abrir()
                continue
            ok, frame = self.cap.read()
            if not ok or frame is None:
                time.sleep(0.05)
                continue
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
            if self.detector:
                try:
                    self.detector.stop()
                except Exception as e:
                    print(f"[DETECTOR] Erro ao parar detector: {e}")
                self.detector = None

    def alterar_modo(self, modo):
        self.modo_monitoramento = modo
        if self.detector: self.detector.set_modo_monitoramento(modo)

    def fechar(self):
        print(f"[CAMERA] Encerrando câmera '{self.nome}'...")
        with self.viewers_lock:
            if self.release_timer:
                self.release_timer.cancel()
                self.release_timer = None
            self.active_viewers = 0
        self.stop_capture.set()
        self.parar_detector()
        if self.capture_thread and self.capture_thread.is_alive():
            self.capture_thread.join(timeout=1.0)
        self.capture_thread = None
        with self.frame_lock:
            if self.cap:
                try:
                    if self.cap.isOpened():
                        self.cap.release()
                except Exception as e:
                    print(f"[CAMERA] Erro ao liberar cap: {e}")
                self.cap = None
            self.latest_frame = None
        print(f"[CAMERA] Câmera '{self.nome}' encerrada e hardware liberado com sucesso.")

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
    with runtimes_lock:
        rt = runtimes.pop(camera_id, None)
        if rt:
            rt.fechar()
    try:
        colecao_cameras.delete_one({'_id': oid(camera_id)})
    except Exception as e:
        print(f"[CAMERAS] Aviso ao deletar no banco: {e}")
    return {'status': 'ok'}

@app.post('/cameras/{camera_id}/start')
def iniciar(camera_id: str):
    rt = runtime_camera(camera_id)
    rt.iniciar_detector()
    return {'status': 'ok'}

@app.post('/cameras/{camera_id}/stop')
def parar(camera_id: str):
    with runtimes_lock:
        rt = runtimes.get(camera_id)
        if rt:
            rt.parar_detector()
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
        while not rt.stop_capture.is_set():
            frame = rt.renderizar()
            ok, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            if ok:
                yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n'
            time.sleep(0.033)
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

@app.get('/alertas')
def listar_alertas(limit: int = 50, status: str | None = None):
    filtro = {} if not status else {'status': status}
    docs = list(colecao_alertas.find(filtro).sort('timestamp', -1).limit(limit))
    return [serializar(d) for d in docs]

@app.put('/alertas/{alerta_id}/status')
def atualizar_status_alerta(alerta_id: str, status: str):
    if status not in ['novo', 'reconhecido', 'resolvido']:
        raise HTTPException(status_code=400, detail='Status inválido')
    r = colecao_alertas.update_one({'_id': oid(alerta_id)}, {'$set': {'status': status, 'updated_at': datetime.utcnow()}})
    if not r.matched_count:
        raise HTTPException(status_code=404, detail='Alerta não encontrado')
    return serializar(colecao_alertas.find_one({'_id': oid(alerta_id)}))

@app.delete('/alertas/{alerta_id}')
def remover_alerta(alerta_id: str):
    doc = colecao_alertas.find_one({'_id': oid(alerta_id)})
    if doc and doc.get('imagem_url'):
        fname = os.path.basename(doc['imagem_url'])
        fpath = os.path.join(ALERTA_IMG_DIR, fname)
        if os.path.exists(fpath):
            try: os.remove(fpath)
            except Exception: pass
    colecao_alertas.delete_one({'_id': oid(alerta_id)})
    return {'status': 'ok'}

@app.get('/alertas/config')
def get_alerta_config():
    return obter_config_alertas()

@app.put('/alertas/config')
def put_alerta_config(dados: dict):
    return atualizar_config_alertas(dados)

@app.post('/alertas/testar')
def testar_alerta_manual():
    frame = None
    with runtimes_lock:
        for rt in runtimes.values():
            f = rt.get_frame()
            if f is not None:
                frame = f.copy()
                break
    if frame is None:
        frame = 240 * np.ones((480, 640, 3), dtype=np.uint8)
        cv2.rectangle(frame, (20, 20), (620, 460), (0, 0, 220), 4)
        cv2.putText(frame, "SIMULACAO: RAIVA EXTREMA DETECTADA", (40, 220), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 0, 255), 2)
        cv2.putText(frame, f"Nivel: 96% | {datetime.utcnow().strftime('%d/%m/%Y %H:%M:%S UTC')}", (40, 260), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (50, 50, 50), 2)

    config = obter_config_alertas()
    filename = f"alerta_raiva_teste_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.jpg"
    filepath = os.path.join(ALERTA_IMG_DIR, filename)
    cv2.imwrite(filepath, frame)

    doc = {
        'camera_id': 'teste_manual',
        'camera_nome': 'Disparo Manual de Teste',
        'tipo': 'raiva_extrema',
        'score': 0.96,
        'pontuacao_percentual': 96.0,
        'timestamp': datetime.utcnow(),
        'imagem_url': f"/imagens_alerta/{filename}",
        'status': 'novo',
        'email_enviado': False,
        'email_destinatario': config.get('email_destino', '')
    }
    res = colecao_alertas.insert_one(doc)
    doc['_id'] = str(res.inserted_id)
    doc['timestamp'] = doc['timestamp'].isoformat()

    retorno_email = None
    if config.get('email_destino'):
        retorno_email = enviar_email_alerta(doc, config, filepath)
        sucesso = retorno_email.get('status') in ['sucesso', 'simulado']
        colecao_alertas.update_one({'_id': res.inserted_id}, {'$set': {'email_enviado': sucesso, 'email_retorno': retorno_email.get('mensagem')}})

    return {'status': 'ok', 'alerta': doc, 'email_resultado': retorno_email}

@app.on_event('shutdown')
def shutdown():
    with runtimes_lock:
        for rt in runtimes.values(): rt.fechar()
        runtimes.clear()
