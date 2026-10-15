from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, Field

class EventoEmocao(BaseModel):
    id_evento: str
    timestamp: datetime
    camera_id: str
    camera_nome: Optional[str] = None
    usuario_id: Optional[str] = None
    usuario_nome: Optional[str] = None
    modo_monitoramento: Literal['individual', 'sala'] = 'individual'
    expressao_dominante: str
    pontuacao: float
    media_emocoes: float
    comportamento: str
    pessoas_unicas_ate_agora: int

class UsuarioCreate(BaseModel):
    nome: str = Field(..., min_length=2)
    email: Optional[str] = None
    departamento: Optional[str] = None
    observacao: Optional[str] = None
    ativo: bool = True

class UsuarioUpdate(BaseModel):
    nome: Optional[str] = Field(default=None, min_length=2)
    email: Optional[str] = None
    departamento: Optional[str] = None
    observacao: Optional[str] = None
    ativo: Optional[bool] = None

class CameraCreate(BaseModel):
    nome: str = Field(..., min_length=2)
    origem: str = Field(..., description='0 para webcam local, URL RTSP/HTTP ou arquivo de vídeo')
    ativa: bool = True
    modo_monitoramento: Literal['individual', 'sala'] = 'individual'

class CameraUpdate(BaseModel):
    nome: Optional[str] = Field(default=None, min_length=2)
    origem: Optional[str] = None
    ativa: Optional[bool] = None
    modo_monitoramento: Optional[Literal['individual', 'sala']] = None
