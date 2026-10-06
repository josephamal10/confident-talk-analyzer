"""Deploys Confident Talk Analyzer on Modal (https://modal.com): modal deploy modal_app.py

The image bakes in every model (speech, emotion, embeddings), so a cold start downloads nothing. Settings
come from a Modal secret named "confident-talk-analyzer" with SECRET_KEY, DATABASE_URL (Postgres) and
GROQ_API_KEY. Recordings are kept on a Modal volume so sessions can be replayed after a restart.
"""
import modal

WHISPER_MODEL = "large-v3-turbo"
CPU_CORES = 4  # physical cores; the models use 2 threads per core
MINILM = "sentence-transformers/all-MiniLM-L6-v2"

image = (
    modal.Image.debian_slim(python_version="3.10")
    .apt_install("libgomp1")
    .pip_install_from_requirements("backend/requirements.txt")
    .pip_install("onnx")  # only for quantizing the emotion model below
    # Audeering's speech-emotion model (CC BY-NC-SA 4.0), downloaded and quantized to int8.
    .add_local_file("backend/scripts/prepare_emotion_model.py", "/build/scripts/prepare_emotion_model.py", copy=True)
    .run_commands(
        "cd /build && python scripts/prepare_emotion_model.py",
        "mkdir -p /models && mv /build/models/emotion-w2v2-int8.onnx /models/ && rm -rf /build",
    )
    .run_commands(
        f"python -c \"from faster_whisper.utils import download_model; download_model('{WHISPER_MODEL}')\"",
        f"python -c \"from huggingface_hub import hf_hub_download as get; get('{MINILM}', 'tokenizer.json'); "
        f"get('{MINILM}', 'onnx/model.onnx')\"",
    )
    .env({
        "WHISPER_MODEL": WHISPER_MODEL,
        "CPU_THREADS": str(CPU_CORES * 2),
        "OMP_NUM_THREADS": str(CPU_CORES * 2),
        "EMOTION_MODEL_PATH": "/models/emotion-w2v2-int8.onnx",
        "UPLOAD_FOLDER": "/data/uploads",
        "DATABASE_PATH": "/tmp/app_data.db",  # only used if DATABASE_URL is missing
    })
    .add_local_dir(
        "backend", "/app/backend",
        ignore=["venv", "venv/**", "**/__pycache__", "**/__pycache__/**", ".pytest_cache", "uploads", "uploads/**",
                "models", "models/**", "evals", "evals/**", "tests", "tests/**", "app_data.db*", ".env", ".secret_key"],
    )
    .add_local_dir("frontend", "/app/frontend")
)

app = modal.App("confident-talk-analyzer", image=image)
recordings = modal.Volume.from_name("confident-talk-analyzer-recordings", create_if_missing=True)


@app.function(
    cpu=CPU_CORES,
    memory=4096,
    secrets=[modal.Secret.from_name("confident-talk-analyzer")],
    volumes={"/data": recordings},
    # One container: analysis jobs are polled from memory, so every request must reach the same one.
    max_containers=1,
    scaledown_window=300,  # sleep after 5 idle minutes; the next visit wakes it (about 30 s)
    timeout=900,
)
@modal.concurrent(max_inputs=12)
@modal.wsgi_app()
def web():
    import os
    import sys

    sys.path.insert(0, "/app/backend")
    os.chdir("/app/backend")
    import app as flask_app

    flask_app.start_model_warm_up()
    return flask_app.app
