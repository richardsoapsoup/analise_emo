import os, time, smtplib, cv2
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
import threading

try:
    from backend.database import colecao_alertas, colecao_config_alertas
except ImportError:
    from database import colecao_alertas, colecao_config_alertas

ALERTA_IMG_DIR = os.path.join(os.getcwd(), 'imagens_alerta')
os.makedirs(ALERTA_IMG_DIR, exist_ok=True)

ultimo_alerta_timestamp = {}
alerta_lock = threading.Lock()

DEFAULT_CONFIG = {
    'email_destino': '',
    'ativo': True,
    'limiar_raiva': 0.75,
    'cooldown_segundos': 30,
    'enviar_email': False,
    'smtp_host': 'smtp.gmail.com',
    'smtp_port': 587,
    'smtp_user': '',
    'smtp_pass': '',
    'smtp_remetente': '',
    'notificacao_sonora': True,
    'updated_at': datetime.utcnow()
}

def obter_config_alertas():
    config = colecao_config_alertas.find_one({'tipo': 'config_geral'})
    if not config:
        cfg = DEFAULT_CONFIG.copy()
        cfg['tipo'] = 'config_geral'
        colecao_config_alertas.insert_one(cfg)
        config = cfg
    config['_id'] = str(config['_id'])
    return config

def atualizar_config_alertas(novos_dados: dict):
    novos_dados['updated_at'] = datetime.utcnow()
    novos_dados.pop('_id', None)
    novos_dados.pop('tipo', None)
    colecao_config_alertas.update_one(
        {'tipo': 'config_geral'},
        {'$set': novos_dados},
        upsert=True
    )
    return obter_config_alertas()

def enviar_email_alerta(alerta: dict, config: dict, image_path: str = None) -> dict:
    email_destino = config.get('email_destino', '').strip()
    if not email_destino:
        return {'status': 'aviso', 'mensagem': 'Nenhum e-mail de destino configurado.'}

    smtp_host = config.get('smtp_host', '').strip()
    smtp_port = int(config.get('smtp_port') or 587)
    smtp_user = config.get('smtp_user', '').strip()
    smtp_pass = config.get('smtp_pass', '').strip()
    smtp_remetente = config.get('smtp_remetente', '').strip() or smtp_user or 'alertas@monitoramento.local'

    raiva_percent = round(float(alerta.get('score', 0)) * 100, 1)
    camera_nome = alerta.get('camera_nome', 'Câmera Desconhecida')
    data_formatada = datetime.utcnow().strftime('%d/%m/%Y às %H:%M:%S (UTC)')

    assunto = f"🚨 ALERTA CRÍTICO: Raiva Extrema ({raiva_percent}%) na Câmera {camera_nome}"

    corpo_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #0f172a; color: #f8fafc; padding: 20px; }}
        .card {{ background-color: #1e293b; border-radius: 16px; border: 1px solid #dc2626; max-width: 600px; margin: 0 auto; overflow: hidden; box-shadow: 0 10px 25px rgba(220, 38, 38, 0.2); }}
        .header {{ background: linear-gradient(135deg, #b91c1c, #dc2626); color: white; padding: 24px; text-align: center; }}
        .header h1 {{ margin: 0; font-size: 20px; font-weight: bold; text-transform: uppercase; letter-spacing: 1px; }}
        .header p {{ margin: 6px 0 0; font-size: 13px; opacity: 0.9; }}
        .content {{ padding: 24px; }}
        .metric-box {{ background-color: #0f172a; border-radius: 12px; padding: 16px; margin-bottom: 20px; border-left: 4px solid #ef4444; }}
        .metric-row {{ display: flex; justify-content: space-between; margin-bottom: 8px; font-size: 14px; }}
        .metric-label {{ color: #94a3b8; font-weight: 500; }}
        .metric-value {{ color: #f8fafc; font-weight: bold; }}
        .badge {{ background-color: #7f1d1d; color: #fca5a5; padding: 3px 10px; border-radius: 20px; font-size: 13px; font-weight: bold; border: 1px solid #ef4444; }}
        .image-container {{ text-align: center; margin: 20px 0; background-color: #000; border-radius: 12px; overflow: hidden; border: 1px solid #334155; }}
        .image-container img {{ max-width: 100%; height: auto; display: block; margin: 0 auto; }}
        .footer {{ text-align: center; padding: 16px; font-size: 12px; color: #64748b; border-top: 1px solid #334155; }}
      </style>
    </head>
    <body>
      <div class="card">
        <div class="header">
          <h1>🚨 Alerta de Raiva Extrema</h1>
          <p>Sistema Inteligente de Monitoramento Emocional</p>
        </div>
        <div class="content">
          <div class="metric-box">
            <div class="metric-row">
              <span class="metric-label">Câmera:</span>
              <span class="metric-value">{camera_nome}</span>
            </div>
            <div class="metric-row">
              <span class="metric-label">Nível de Raiva Detectado:</span>
              <span class="badge">{raiva_percent}%</span>
            </div>
            <div class="metric-row">
              <span class="metric-label">Data e Hora:</span>
              <span class="metric-value">{data_formatada}</span>
            </div>
            <div class="metric-row">
              <span class="metric-label">Status do Incidente:</span>
              <span class="metric-value" style="color: #f87171;">Atenção Requerida</span>
            </div>
          </div>

          <p style="font-size: 14px; line-height: 1.5; color: #cbd5e1;">
            Foi detectado um pico de expressão facial de raiva acima do limite configurado ({int(config.get('limiar_raiva', 0.85) * 100)}%). A imagem capturada no momento da detecção está anexada abaixo.
          </p>

          <div class="image-container">
            <img src="cid:foto_alerta" alt="Registro Visual da Raiva Extrema" />
          </div>
        </div>
        <div class="footer">
          Mensagem automática gerada pelo Sistema de Monitoramento Emocional.<br>
          Para gerenciar limiares e destinatários, acesse o painel de configurações.
        </div>
      </div>
    </body>
    </html>
    """

    msg = MIMEMultipart('related')
    msg['Subject'] = assunto
    msg['From'] = smtp_remetente
    msg['To'] = email_destino

    part_html = MIMEText(corpo_html, 'html', 'utf-8')
    msg.attach(part_html)

    # Anexa a imagem com Content-ID para visualização direta no corpo do e-mail
    if image_path and os.path.exists(image_path):
        try:
            with open(image_path, 'rb') as f:
                img_data = f.read()
                img_part = MIMEImage(img_data)
                img_part.add_header('Content-ID', '<foto_alerta>')
                img_part.add_header('Content-Disposition', 'inline', filename=os.path.basename(image_path))
                msg.attach(img_part)
        except Exception as e:
            print(f"[ALERTA EMAIL] Erro ao anexar imagem: {e}")

    # Se não houver credenciais SMTP completas, loga e simula com sucesso
    if not smtp_host or not smtp_user or not smtp_pass:
        print(f"[ALERTA EMAIL] Modo Simulação: E-mail para '{email_destino}' gerado com sucesso!")
        print(f"               Assunto: {assunto}")
        return {
            'status': 'simulado',
            'mensagem': f"Alerta registrado e e-mail simulado para {email_destino} (Credenciais SMTP não preenchidas)."
        }

    # Envio real via SMTP
    try:
        server = smtplib.SMTP(smtp_host, smtp_port, timeout=10)
        server.ehlo()
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_remetente, [email_destino], msg.as_string())
        server.quit()
        print(f"[ALERTA EMAIL] E-mail enviado com sucesso para: {email_destino}")
        return {'status': 'sucesso', 'mensagem': f'E-mail enviado com sucesso para {email_destino}'}
    except Exception as e:
        print(f"[ALERTA EMAIL] Falha ao enviar via SMTP: {e}")
        return {'status': 'erro', 'mensagem': f'Erro ao enviar via SMTP: {str(e)}'}

def registrar_alerta_raiva(camera_id: str, camera_nome: str, score: float, frame=None) -> dict:
    config = obter_config_alertas()
    if not config.get('ativo', True):
        return None

    limiar = float(config.get('limiar_raiva', 0.85))
    if score < limiar:
        return None

    cooldown = int(config.get('cooldown_segundos', 60))
    agora = time.time()

    with alerta_lock:
        ultimo = ultimo_alerta_timestamp.get(camera_id, 0)
        if agora - ultimo < cooldown:
            return None
        ultimo_alerta_timestamp[camera_id] = agora

    # Salva imagem do snapshot de alerta
    filename = f"alerta_raiva_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{camera_id[:6]}.jpg"
    filepath = os.path.join(ALERTA_IMG_DIR, filename)
    imagem_url = f"/imagens_alerta/{filename}"

    if frame is not None:
        try:
            cv2.imwrite(filepath, frame)
        except Exception as e:
            print(f"[ALERTA] Falha ao salvar frame de raiva: {e}")
            filepath = None
            imagem_url = None
    else:
        filepath = None
        imagem_url = None

    doc = {
        'camera_id': camera_id,
        'camera_nome': camera_nome,
        'tipo': 'raiva_extrema',
        'score': round(float(score), 2),
        'pontuacao_percentual': round(float(score) * 100, 1),
        'timestamp': datetime.utcnow(),
        'imagem_url': imagem_url,
        'status': 'novo', # 'novo' | 'reconhecido' | 'resolvido'
        'email_enviado': False,
        'email_destinatario': config.get('email_destino', '')
    }

    res = colecao_alertas.insert_one(doc)
    doc['_id'] = str(res.inserted_id)
    doc['timestamp'] = doc['timestamp'].isoformat()

    # Dispara e-mail em background se configurado
    if config.get('enviar_email', False) and config.get('email_destino'):
        def _enviar():
            res_email = enviar_email_alerta(doc, config, filepath)
            sucesso = res_email.get('status') in ['sucesso', 'simulado']
            colecao_alertas.update_one(
                {'_id': res.inserted_id},
                {'$set': {'email_enviado': sucesso, 'email_retorno': res_email.get('mensagem')}}
            )
        threading.Thread(target=_enviar, daemon=True).start()

    print(f"[ALERTA CRÍTICO] Raiva Extrema detectada na câmera '{camera_nome}'! Nível: {doc['pontuacao_percentual']}%")
    return doc
