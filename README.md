# Análise de Emoções e Comportamento com OpenCV + FER + MongoDB

Este projeto detecta expressões faciais em tempo real via webcam, classifica o comportamento emocional e envia os dados para o Banco de dados mongodb. Ideal para aplicações em monitoramento, segurança, UX e pesquisa comportamental.

---

## Funcionalidades

- Captura de vídeo em tempo real com OpenCV (múltiplas câmeras e feeds)
- Detecção de emoções faciais com [FER](https://github.com/justinshenk/fer)
- Classificação de comportamento emocional (ex: positivo, potencialmente agressivo, depressivo, neutro)
- Modo de monitoramento por câmera: **Individual (faces)** ou **Sala (emoção geral do ambiente)**
- Gerenciamento completo de câmeras (`POST/GET/PUT/DELETE /cameras`)
- Início e parada de detecção por câmera (`/cameras/{id}/start` e `/stop`)
- Cadastro de usuários organizacionais (`POST/GET/PUT/DELETE /usuarios`)
- Stream individual de vídeo por câmera (`/video_feed/{camera_id}`)
- Relatórios dinâmicos e agregados (`/relatorios/resumo` e `/relatorios/usuarios`)
- Armazenamento e indexação otimizada no MongoDB

---

## 📌 Rotas da API

### Câmeras
- `POST /cameras` - Cadastra uma nova câmera
- `GET /cameras` - Lista as câmeras cadastradas
- `PUT /cameras/{camera_id}` - Atualiza configurações da câmera
- `DELETE /cameras/{camera_id}` - Remove a câmera
- `POST /cameras/{camera_id}/start` - Inicia detector na câmera
- `POST /cameras/{camera_id}/stop` - Para detector na câmera
- `PUT /cameras/{camera_id}/modo` - Altera o modo (`individual` ou `sala`)
- `GET /video_feed/{camera_id}` - Stream de vídeo MJPEG com anotações de emoção

### Usuários
- `POST /usuarios` - Cadastra usuário organizacional
- `GET /usuarios` - Lista usuários
- `PUT /usuarios/{usuario_id}` - Atualiza usuário
- `DELETE /usuarios/{usuario_id}` - Desativa usuário

### Eventos e Relatórios
- `POST /evento` - Recebe evento de detecção
- `GET /eventos` - Lista últimos eventos salvos
- `GET /relatorios/resumo` - Resumo estatístico geral (por emoção, comportamento, câmera)
- `GET /relatorios/usuarios` - Métricas consolidadas por usuário

---

## Requisitos

- Python 3.9 ou superior
- MongoDB instalado e em execução (porta padrão `27017` ou configurado via `MONGO_URI`)
- Câmera/webcam conectada ou URL de stream RTSP/HTTP

---

## 💻 Instalação e Execução Local

### 1. Clone o repositório
```bash
git clone https://github.com/richardsoapsoup/analise_emo
cd analise_emocao



```

### 2. Crie um ambiente virtual(recomendado)
```bash
python -m venv venv
source venv/bin/activate     # Linux/macOS
venv\Scripts\activate        # Windows
```
### 3. Instale as dependencias
```bash
pip install -r requirements.txt
```

### 4. Execute o programa
```bash
uvicorn backend.main:app --reload    

```

