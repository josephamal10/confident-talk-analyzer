# Confident Talk Analyzer: one container serving the Flask API and the frontend.
# Port 7860, runs as uid 1000. For Hugging Face Spaces add CROSS_SITE_COOKIES=1 (the app is shown in an iframe).

# Stage 1: download audeering's speech-emotion model (CC BY-NC-SA 4.0) and quantize it to int8.
FROM python:3.10-slim AS emotion-model
WORKDIR /build
RUN pip install --no-cache-dir onnxruntime onnx numpy
COPY backend/scripts/prepare_emotion_model.py scripts/
RUN python scripts/prepare_emotion_model.py

# Stage 2: the app.
FROM python:3.10-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
RUN useradd -m -u 1000 user

ARG WHISPER_MODEL=large-v3-turbo
ENV HOME=/home/user \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/home/user/.cache/huggingface \
    WHISPER_MODEL=${WHISPER_MODEL} \
    UPLOAD_FOLDER=/tmp/uploads \
    DATABASE_PATH=/tmp/app_data.db \
    CROSS_SITE_COOKIES=1 \
    PORT=7860

WORKDIR /home/user/app
COPY backend/requirements.txt backend/
RUN pip install --no-cache-dir -r backend/requirements.txt gunicorn

USER user
# Bake the speech and embedding models into the image, so a cold start doesn't download them.
RUN python -c "from faster_whisper.utils import download_model; download_model('${WHISPER_MODEL}')" \
 && python -c "from huggingface_hub import hf_hub_download as get; \
repo = 'sentence-transformers/all-MiniLM-L6-v2'; get(repo, 'tokenizer.json'); get(repo, 'onnx/model.onnx')"
COPY --chown=user --from=emotion-model /build/models/emotion-w2v2-int8.onnx backend/models/
COPY --chown=user backend backend
COPY --chown=user frontend frontend

WORKDIR /home/user/app/backend
EXPOSE 7860
CMD ["gunicorn", "--config", "gunicorn.conf.py", "app:app"]
