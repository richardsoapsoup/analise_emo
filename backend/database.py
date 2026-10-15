import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017')
client = MongoClient(MONGO_URI)
db = client['emocao_db']
colecao_eventos = db['eventos']
colecao_usuarios = db['usuarios']
colecao_cameras = db['cameras']
colecao_alertas = db['alertas']
colecao_config_alertas = db['config_alertas']
colecao_eventos.create_index('timestamp')
colecao_eventos.create_index('camera_id')
colecao_eventos.create_index('usuario_id')
colecao_eventos.create_index('comportamento')
colecao_usuarios.create_index('nome')
colecao_cameras.create_index('nome')
colecao_alertas.create_index('timestamp')
colecao_alertas.create_index('status')
