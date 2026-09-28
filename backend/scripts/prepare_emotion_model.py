"""Download audeering's dimensional speech-emotion model and quantize it to int8 ONNX.

Model: wav2vec2-large-robust (12 layers) fine-tuned on MSP-Podcast; predicts arousal,
dominance and valence (~0..1) from raw 16 kHz audio. Source: doi:10.5281/zenodo.6221127
License: CC BY-NC-SA 4.0 (non-commercial use only).

Dynamic int8 quantization of the transformer MatMuls shrinks the model from ~660 MB to
~200 MB and roughly halves CPU inference time; the convolutional feature encoder stays
in float32 because quantized convolutions are slow on most CPUs.

Usage:  python scripts/prepare_emotion_model.py
"""
import hashlib
import os
import sys
import urllib.request
import zipfile

from onnxruntime.quantization import QuantType, quantize_dynamic

MODEL_URL = "https://zenodo.org/records/6221127/files/w2v2-L-robust-12.6bc4a7fd-1.1.0.zip?download=1"
MODEL_MD5 = "76fef8c090addd7fcee60c64e9536ced"

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(BACKEND_DIR, "models")
ARCHIVE_PATH = os.path.join(MODELS_DIR, "w2v2-L-robust-12.zip")
FLOAT_MODEL_PATH = os.path.join(MODELS_DIR, "w2v2-L-robust-12", "model.onnx")
INT8_MODEL_PATH = os.path.join(MODELS_DIR, "emotion-w2v2-int8.onnx")


def md5(path):
    digest = hashlib.md5()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    os.makedirs(MODELS_DIR, exist_ok=True)
    if os.path.exists(INT8_MODEL_PATH):
        print(f"Already prepared: {INT8_MODEL_PATH}")
        return

    if not os.path.exists(FLOAT_MODEL_PATH):
        if not os.path.exists(ARCHIVE_PATH):
            print("Downloading emotion model (~610 MB) from Zenodo...")
            urllib.request.urlretrieve(MODEL_URL, ARCHIVE_PATH)
        if md5(ARCHIVE_PATH) != MODEL_MD5:
            sys.exit(f"Checksum mismatch for {ARCHIVE_PATH}; delete it and try again.")
        with zipfile.ZipFile(ARCHIVE_PATH) as archive:
            archive.extractall(os.path.dirname(FLOAT_MODEL_PATH))

    print("Quantizing to int8...")
    quantize_dynamic(
        FLOAT_MODEL_PATH,
        INT8_MODEL_PATH,
        op_types_to_quantize=["MatMul"],
        weight_type=QuantType.QInt8,
    )
    size_mb = os.path.getsize(INT8_MODEL_PATH) / 1e6
    print(f"Wrote {INT8_MODEL_PATH} ({size_mb:.0f} MB)")


if __name__ == "__main__":
    main()
