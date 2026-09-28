"""Semantic topic relevance with a sentence-embedding model.

Model: sentence-transformers/all-MiniLM-L6-v2 (Apache-2.0), run as ONNX with mean pooling, the
same way sentence-transformers computes it. Unlike keyword overlap, it recognises that a talk
about "global warming" is on the topic "climate change". Falls back to keyword overlap if the
model can't be loaded.
"""
import logging
import re
import threading

import numpy as np

from .topic import is_topic_related

logger = logging.getLogger(__name__)

MODEL_REPO = "sentence-transformers/all-MiniLM-L6-v2"
MAX_TOKENS = 256
# Cosine-similarity cut-offs calibrated on sample recordings: on-topic speeches scored 0.45-0.77
# against their topic and unrelated ones mostly below 0.30. Answers to interview questions rarely
# restate the question, so good answers scored only 0.25-0.34 (off-topic ones about 0.0).
TOPIC_THRESHOLD = 0.35
QUESTION_THRESHOLD = 0.15

_model = None
_model_lock = threading.Lock()
_load_failed = False


def _load_model():
    global _model, _load_failed
    with _model_lock:
        if _model is None and not _load_failed:
            try:
                import onnxruntime
                from huggingface_hub import hf_hub_download
                from tokenizers import Tokenizer

                tokenizer = Tokenizer.from_file(hf_hub_download(MODEL_REPO, "tokenizer.json"))
                tokenizer.enable_truncation(MAX_TOKENS)
                tokenizer.enable_padding()
                session = onnxruntime.InferenceSession(
                    hf_hub_download(MODEL_REPO, "onnx/model.onnx"), providers=["CPUExecutionProvider"]
                )
                _model = (tokenizer, session)
            except Exception:
                logger.exception("Could not load the embedding model; using keyword topic matching instead.")
                _load_failed = True
    return _model


def embed(texts):
    """Returns L2-normalised sentence embeddings, shape (len(texts), 384)."""
    tokenizer, session = _load_model()
    encodings = tokenizer.encode_batch(texts)
    inputs = {
        "input_ids": np.array([e.ids for e in encodings], dtype=np.int64),
        "attention_mask": np.array([e.attention_mask for e in encodings], dtype=np.int64),
        "token_type_ids": np.array([e.type_ids for e in encodings], dtype=np.int64),
    }
    token_vectors = session.run(None, inputs)[0]
    mask = inputs["attention_mask"][..., np.newaxis]
    pooled = (token_vectors * mask).sum(axis=1) / np.maximum(mask.sum(axis=1), 1)
    return pooled / np.linalg.norm(pooled, axis=1, keepdims=True)


def split_sentences(text):
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if len(s.split()) >= 3]


def topic_relevance(topic, transcript, threshold=TOPIC_THRESHOLD):
    """Returns {"related", "similarity", "method"} for a topic, or None when no topic was given."""
    topic = (topic or "").strip()
    if not topic:
        return None
    if _load_model() is None:
        related, _matches, coverage = is_topic_related(topic, transcript)
        return {"related": related, "similarity": coverage, "method": "keywords"}

    # Score the whole answer and each sentence; a focused answer with one off-topic aside still counts.
    passages = [transcript] + split_sentences(transcript)
    vectors = embed([topic] + passages)
    similarities = vectors[1:] @ vectors[0]
    best_sentences = np.sort(similarities[1:])[-3:] if len(similarities) > 1 else similarities[:1]
    similarity = float(max(similarities[0], best_sentences.mean()))
    return {"related": similarity >= threshold, "similarity": round(similarity, 3), "method": "embeddings"}


def warm_up():
    _load_model()
