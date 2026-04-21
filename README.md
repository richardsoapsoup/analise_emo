# Análise de Emoções e Comportamento com OpenCV + FER + MongoDB

Este projeto detecta expressões faciais em tempo real via webcam, classifica o comportamento emocional e envia os dados para o Banco de dados mongodb. Ideal para aplicações em monitoramento, segurança, UX e pesquisa comportamental.

---

## Funcionalidades

- Captura de vídeo em tempo real com OpenCV
- Detecção de emoções com a biblioteca [FER](https://github.com/justinshenk/fer)
- Classificação de comportamento (ex: positivo, agressivo, depressivo)
- Envio de dados para banco de dados com mongodb
- Visualização com anotação de emoção na tela

---

## Requisitos

- Python 3.7 ou superior
- Mongodb instalado
- Webcam conectada e funcional

---

## 💻 Instalação e Execução Local

### 1. Clone o repositório
```bash
git clone https://github.com/richardsoapsoup/analise_emocao
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

