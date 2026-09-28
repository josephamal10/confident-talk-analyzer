from flask import Flask, g, jsonify, request, send_from_directory, session
import speech_recognition as sr
import os
import re
import secrets
import sqlite3
import librosa
import numpy as np
from datetime import datetime, timedelta
from functools import wraps
from uuid import uuid4
from pydub import AudioSegment, effects
from scipy.ndimage import binary_opening
from werkzeug.security import generate_password_hash, check_password_hash

try:
    import whisper
except Exception:
    whisper = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
DB_FILE = os.path.join(BASE_DIR, "app_data.db")
SECRET_KEY_FILE = os.path.join(BASE_DIR, ".secret_key")
FRONTEND_DIR = os.path.join(BASE_DIR, "..", "frontend")
TRANSCRIPTION_ENGINE = os.getenv("TRANSCRIPTION_ENGINE", "auto").strip().lower()
WHISPER_MODEL_NAME = os.getenv("WHISPER_MODEL", "base").strip() or "base"
# Whisper normally cleans "um"/"uh" out of its output; a prompt written in the same
# disfluent style makes it keep them (and set "like," off with commas).
WHISPER_FILLER_PROMPT = "Um, well, uh, I was, like, thinking about it, you know. Hmm, okay, so."
MIN_SPEECH_SECONDS = 0.5
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
HESITATION_PATTERN = re.compile(r"\b(?:u+h+m*|u+m+|h+m+|e+r+m*|a+h+)\b")
DISCOURSE_FILLERS = {"like", "actually", "basically", "literally", "you know", "i mean"}
CLAUSE_SPLIT_PATTERN = re.compile(r"[,.;:!?—…]+")
TOPIC_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "your",
    "about",
    "into",
    "their",
    "there",
    "have",
    "will",
    "would",
    "should",
    "could",
    "what",
    "when",
    "where",
    "which",
    "while",
    "who",
    "whom",
    "why",
    "how",
    "are",
    "was",
    "were",
    "has",
    "had",
    "been",
    "being",
    "can",
    "just",
    "than",
    "then",
    "them",
    "they",
    "you",
    "our",
    "out",
    "all",
    "any",
    "too",
    "very",
    "its",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    signup_ip TEXT,
    signup_user_agent TEXT,
    created_at TEXT NOT NULL,
    last_login_at TEXT,
    last_login_ip TEXT,
    last_login_user_agent TEXT
);

CREATE TABLE IF NOT EXISTS analysis_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    topic TEXT,
    transcription TEXT NOT NULL,
    transcription_engine TEXT,
    duration REAL NOT NULL,
    speaking_duration REAL,
    minutes INTEGER NOT NULL DEFAULT 0,
    seconds INTEGER NOT NULL DEFAULT 0,
    word_count INTEGER NOT NULL,
    wpm INTEGER NOT NULL,
    filler_count INTEGER NOT NULL,
    filler_ratio REAL NOT NULL,
    emotion TEXT NOT NULL,
    score REAL NOT NULL,
    feedback TEXT NOT NULL,
    audio_filename TEXT,
    wav_filename TEXT
);

CREATE INDEX IF NOT EXISTS idx_analysis_records_user ON analysis_records (user_id, created_at);
"""

ANALYSIS_COLUMNS = (
    "topic",
    "transcription",
    "transcription_engine",
    "duration",
    "speaking_duration",
    "minutes",
    "seconds",
    "word_count",
    "wpm",
    "filler_count",
    "filler_ratio",
    "emotion",
    "score",
    "feedback",
    "audio_filename",
    "wav_filename",
)

HISTORY_COLUMNS = (
    "created_at AS timestamp, topic, transcription, transcription_engine, duration, speaking_duration, "
    "minutes, seconds, word_count, wpm, filler_count, filler_ratio, emotion, score, feedback"
)

USER_COLUMNS = "id, name, email, password_hash"


def load_secret_key():
    env_key = os.getenv("SECRET_KEY", "").strip()
    if env_key:
        return env_key
    if os.path.exists(SECRET_KEY_FILE):
        with open(SECRET_KEY_FILE, "r", encoding="utf-8") as file:
            saved_key = file.read().strip()
        if saved_key:
            return saved_key
    new_key = secrets.token_hex(32)
    with open(SECRET_KEY_FILE, "w", encoding="utf-8") as file:
        file.write(new_key)
    return new_key


app = Flask(__name__)
app.config.update(
    SECRET_KEY=load_secret_key(),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    MAX_CONTENT_LENGTH=25 * 1024 * 1024,
)

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

if whisper is None and TRANSCRIPTION_ENGINE != "google":
    app.logger.warning(
        "Whisper is not installed, so Google Speech Recognition will be used. "
        "Google removes filler words, so filler counts will be close to zero."
    )

_WHISPER_MODEL = None


def current_timestamp():
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def get_client_ip():
    forwarded = request.headers.get("X-Forwarded-For", "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or ""


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_FILE, timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_FILE)
    try:
        db.executescript(SCHEMA)
    finally:
        db.close()


def get_user_by_email(email):
    return get_db().execute(f"SELECT {USER_COLUMNS} FROM users WHERE email = ?", (email,)).fetchone()


def get_user_by_id(user_id):
    return get_db().execute(f"SELECT {USER_COLUMNS} FROM users WHERE id = ?", (user_id,)).fetchone()


def create_user(name, email, password_hash, ip_address, user_agent):
    db = get_db()
    try:
        db.execute(
            "INSERT INTO users (name, email, password_hash, signup_ip, signup_user_agent, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, email, password_hash, ip_address, user_agent, current_timestamp()),
        )
        db.commit()
    except sqlite3.IntegrityError:
        return False
    return True


def record_login(user_id, ip_address, user_agent):
    db = get_db()
    db.execute(
        "UPDATE users SET last_login_at = ?, last_login_ip = ?, last_login_user_agent = ? WHERE id = ?",
        (current_timestamp(), ip_address, user_agent, user_id),
    )
    db.commit()


def public_user(user):
    return {"name": user["name"], "email": user["email"]}


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        user_id = session.get("user_id")
        user = get_user_by_id(user_id) if user_id is not None else None
        if user is None:
            session.clear()
            return jsonify({"error": "Please log in to continue."}), 401
        g.user = user
        return view(*args, **kwargs)

    return wrapped_view


def get_user_history(user_id):
    rows = get_db().execute(
        f"SELECT {HISTORY_COLUMNS} FROM analysis_records WHERE user_id = ? ORDER BY created_at, id",
        (user_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_previous_score(user_id):
    row = get_db().execute(
        "SELECT score FROM analysis_records WHERE user_id = ? ORDER BY created_at DESC, id DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    return row["score"] if row else None


def save_analysis_record(user_id, record):
    columns = ("user_id", "created_at") + ANALYSIS_COLUMNS
    values = [user_id, current_timestamp()] + [record[column] for column in ANALYSIS_COLUMNS]
    placeholders = ", ".join("?" for _ in columns)

    db = get_db()
    db.execute(f"INSERT INTO analysis_records ({', '.join(columns)}) VALUES ({placeholders})", values)
    db.commit()
    return db.execute("SELECT COUNT(*) FROM analysis_records WHERE user_id = ?", (user_id,)).fetchone()[0]


def discard_files(*paths):
    for path in paths:
        if os.path.exists(path):
            os.remove(path)


def get_whisper_model():
    global _WHISPER_MODEL
    if whisper is None:
        return None
    if _WHISPER_MODEL is None:
        _WHISPER_MODEL = whisper.load_model(WHISPER_MODEL_NAME)
    return _WHISPER_MODEL


def convert_to_wav(input_path, output_path):
    audio = AudioSegment.from_file(input_path)
    audio = audio.set_channels(1).set_frame_rate(16000).set_sample_width(2)
    audio = audio.high_pass_filter(70).low_pass_filter(7600)
    # Speech detection needs the real levels; normalizing would make silence look loud.
    filtered_audio = audio
    audio = effects.compress_dynamic_range(audio, threshold=-20.0, ratio=3.0, attack=5, release=50)
    audio = effects.normalize(audio)
    audio.export(output_path, format="wav")
    return filtered_audio


def measure_speech(audio):
    samples = np.array(audio.get_array_of_samples(), dtype=np.float32) / 32768.0
    duration = len(samples) / audio.frame_rate
    hop = audio.frame_rate // 100
    if len(samples) < hop * 3:
        return duration, 0.0, 0.0

    rms = librosa.feature.rms(y=samples, frame_length=hop * 3, hop_length=hop)[0]
    levels = librosa.amplitude_to_db(np.maximum(rms, 1e-10), ref=1.0, top_db=None)
    # A 10 ms frame is speech when it is well above the background noise and within 35 dB of the loudest part.
    threshold = max(np.percentile(levels, 10) + 10, levels.max() - 35, -55)
    # Drop blips shorter than 100 ms (mouse clicks, desk taps).
    voiced = binary_opening(levels > threshold, structure=np.ones(10))
    voiced_frames = np.flatnonzero(voiced)
    if len(voiced_frames) == 0:
        return duration, 0.0, 0.0

    frame_seconds = hop / audio.frame_rate
    speaking_span = (voiced_frames[-1] - voiced_frames[0] + 1) * frame_seconds
    voiced_seconds = len(voiced_frames) * frame_seconds
    return duration, speaking_span, voiced_seconds


def transcribe_with_google(audio_path):
    recognizer = sr.Recognizer()
    with sr.AudioFile(audio_path) as source:
        audio = recognizer.record(source)

    try:
        detailed = recognizer.recognize_google(audio, show_all=True)
        if isinstance(detailed, dict):
            alternatives = detailed.get("alternative", [])
            if alternatives:
                best = max(alternatives, key=lambda alt: alt.get("confidence", 0))
                text = best.get("transcript", "")
                if text:
                    return text
        return recognizer.recognize_google(audio)
    except sr.UnknownValueError:
        return ""
    except Exception:
        app.logger.exception("Google transcription failed.")
        return ""


def is_repetition_loop(whisper_result):
    # Whisper reports a high compression ratio when it gets stuck repeating a phrase.
    return any(segment.get("compression_ratio", 0) > 2.4 for segment in whisper_result.get("segments", []))


def transcribe_with_whisper(audio_path):
    try:
        model = get_whisper_model()
        if model is None:
            return ""
        options = dict(fp16=False, temperature=0.0, beam_size=5, best_of=3, condition_on_previous_text=True)
        result = model.transcribe(audio_path, initial_prompt=WHISPER_FILLER_PROMPT, **options) or {}
        # The filler prompt occasionally causes a loop ("Good morning. Good morning. ..."); retry without it.
        if is_repetition_loop(result):
            result = model.transcribe(audio_path, **options) or {}
        if is_repetition_loop(result):
            return ""
        return result.get("text", "")
    except Exception:
        app.logger.exception("Whisper transcription failed; falling back to Google.")
        return ""


def clean_transcription_text(text):
    cleaned = re.sub(r"\s+", " ", (text or "")).strip()
    cleaned = re.sub(r"\s+([,.;!?])", r"\1", cleaned)
    return cleaned


def speech_to_text(audio_path):
    if TRANSCRIPTION_ENGINE != "google":
        whisper_text = clean_transcription_text(transcribe_with_whisper(audio_path))
        if whisper_text:
            return whisper_text, "whisper"
    return clean_transcription_text(transcribe_with_google(audio_path)), "google"


def split_duration(duration_seconds):
    total_seconds = max(0, int(round(duration_seconds or 0)))
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return minutes, seconds


def calculate_wpm(word_count, speaking_seconds):
    return round(word_count / (speaking_seconds / 60)) if speaking_seconds > 0 else 0


def count_fillers(text):
    text_lower = (text or "").lower()
    hesitations = len(HESITATION_PATTERN.findall(text_lower))
    # "like", "actually", "you know"... only count when set off on their own ("it was, like, great"),
    # so normal use such as "I like nature" or "what actually happened" is not penalised.
    discourse_fillers = sum(
        1 for clause in CLAUSE_SPLIT_PATTERN.split(text_lower) if clause.strip() in DISCOURSE_FILLERS
    )
    return hesitations + discourse_fillers


def detect_emotion(wpm, filler_ratio, word_count):
    if word_count < 8:
        return "Under-Prepared"
    if wpm > 190 and filler_ratio > 0.08:
        return "Rushed and Uncertain"
    if wpm > 185:
        return "Rushed"
    if wpm < 90 and filler_ratio > 0.10:
        return "Very Hesitant"
    if wpm < 100:
        return "Cautious"
    if filler_ratio > 0.12:
        return "Nervous"
    if filler_ratio > 0.07:
        return "Slightly Hesitant"
    if 115 <= wpm <= 165 and filler_ratio < 0.05:
        return "Confident"
    return "Steady"


def calculate_confidence(wpm, filler_ratio, word_count):
    score = 10.0
    if word_count < 8:
        score -= 2.5
    if wpm < 100 or wpm > 185:
        score -= 1.5
    elif 115 <= wpm <= 165:
        score += 0.3

    score -= min(3.2, filler_ratio * 22)
    return round(max(0, min(score, 10)), 1)


def extract_topic_tokens(text):
    tokens = re.findall(r"[a-zA-Z0-9']+", (text or "").lower())
    return [token for token in tokens if len(token) > 2 and token not in TOPIC_STOPWORDS]


def is_topic_related(topic, transcription):
    topic_clean = (topic or "").strip().lower()
    transcription_clean = (transcription or "").strip().lower()

    if not topic_clean:
        return True, [], 1.0
    if not transcription_clean:
        return False, [], 0.0
    if topic_clean in transcription_clean:
        return True, extract_topic_tokens(topic_clean), 1.0

    topic_tokens = set(extract_topic_tokens(topic_clean))
    speech_tokens = set(extract_topic_tokens(transcription_clean))

    if not topic_tokens:
        return True, [], 1.0

    overlap = sorted(topic_tokens.intersection(speech_tokens))
    coverage = len(overlap) / len(topic_tokens)
    minimum_overlap = 1 if len(topic_tokens) <= 2 else 2
    related = coverage >= 0.4 or len(overlap) >= minimum_overlap
    return related, overlap, round(coverage, 2)


def build_feedback(
    emotion,
    wpm,
    filler_count,
    filler_ratio,
    score,
    progress_note=None,
    topic_note=None,
):
    filler_percent = round(filler_ratio * 100, 1)

    if emotion == "Confident":
        line_one = f"Strong delivery. Your pace is {wpm} WPM and confidence score is {score}/10."
    elif emotion in {"Rushed", "Rushed and Uncertain"}:
        line_one = f"You are speaking fast at {wpm} WPM, which can reduce clarity."
    elif emotion in {"Very Hesitant", "Cautious", "Nervous", "Slightly Hesitant"}:
        line_one = f"Your delivery sounds hesitant, with {filler_count} fillers ({filler_percent}%)."
    else:
        line_one = f"Your delivery is stable, with an overall confidence score of {score}/10."

    if wpm > 185:
        pace_tip = "Slow down slightly and use short pauses after key points."
    elif wpm < 100:
        pace_tip = "Increase your pace a little and keep sentence rhythm consistent."
    else:
        pace_tip = "Your pace is workable; focus on consistent emphasis."

    filler_tip = (
        f"Reduce filler words from {filler_count} to improve fluency and authority."
        if filler_count > 0
        else "Great filler control; maintain this verbal clarity."
    )

    line_two = f"{pace_tip} {filler_tip}"
    line_three = progress_note or "Practice a focused 60-second run daily and track score trend over time."
    line_four = topic_note or "Topic check: no topic was provided for relevance scoring."
    return "\n".join([line_one, line_two, line_three, line_four])


init_db()


@app.errorhandler(413)
def recording_too_large(_error):
    return jsonify({"error": "The recording is too large. Please keep it under 25 MB."}), 413


@app.route("/", methods=["GET"])
def serve_index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/tracker", methods=["GET"])
def serve_tracker():
    return send_from_directory(FRONTEND_DIR, "tracker.html")


@app.route("/<path:filename>", methods=["GET"])
def serve_frontend_assets(filename):
    asset_path = os.path.join(FRONTEND_DIR, filename)
    if os.path.isfile(asset_path):
        return send_from_directory(FRONTEND_DIR, filename)
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/register", methods=["POST"])
def register():
    payload = request.get_json(silent=True) or {}
    name = payload.get("name", "").strip()
    email = payload.get("email", "").strip().lower()
    password = payload.get("password", "")

    if len(name) < 2:
        return jsonify({"error": "Name must be at least 2 characters."}), 400
    if not EMAIL_PATTERN.match(email):
        return jsonify({"error": "Please provide a valid email address."}), 400
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters."}), 400

    ip_address = get_client_ip()
    user_agent = request.headers.get("User-Agent", "")
    if not create_user(name, email, generate_password_hash(password), ip_address, user_agent):
        return jsonify({"error": "An account with this email already exists."}), 409

    return jsonify(
        {
            "message": "Registration successful.",
            "user": {"name": name, "email": email},
        }
    ), 201


@app.route("/login", methods=["POST"])
def login():
    payload = request.get_json(silent=True) or {}
    email = payload.get("email", "").strip().lower()
    password = payload.get("password", "")

    user = get_user_by_email(email)
    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Invalid email or password."}), 401

    session.clear()
    session["user_id"] = user["id"]
    session.permanent = True
    record_login(user["id"], get_client_ip(), request.headers.get("User-Agent", ""))
    return jsonify(
        {
            "message": "Login successful.",
            "user": public_user(user),
        }
    )


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"message": "Logged out."})


@app.route("/me", methods=["GET"])
@login_required
def me():
    return jsonify({"user": public_user(g.user)})


@app.route("/history", methods=["GET"])
@login_required
def history():
    entries = get_user_history(g.user["id"])
    return jsonify({"history": entries, "count": len(entries)})


@app.route("/analyze", methods=["POST"])
@login_required
def analyze():
    file = request.files.get("audio")
    if not file:
        return jsonify({"error": "Audio file is required."}), 400

    original_ext = os.path.splitext(file.filename or "")[1].lower() or ".webm"
    unique_id = f"{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}_{uuid4().hex[:8]}"
    audio_filename = f"{unique_id}{original_ext}"
    wav_filename = f"{unique_id}.wav"

    audio_path = os.path.join(UPLOAD_FOLDER, audio_filename)
    wav_path = os.path.join(UPLOAD_FOLDER, wav_filename)

    file.save(audio_path)
    try:
        filtered_audio = convert_to_wav(audio_path, wav_path)
    except Exception:
        app.logger.exception("Could not decode the uploaded recording.")
        discard_files(audio_path, wav_path)
        return jsonify({"error": "The recording could not be read. Please record again."}), 400

    duration_seconds, speaking_seconds, voiced_seconds = measure_speech(filtered_audio)
    if voiced_seconds < MIN_SPEECH_SECONDS:
        discard_files(audio_path, wav_path)
        return jsonify({"error": "No speech was detected. Check your microphone and try again."}), 422

    text, engine = speech_to_text(wav_path)
    word_count = len(text.split())
    if word_count == 0:
        discard_files(audio_path, wav_path)
        return jsonify(
            {"error": "Your speech could not be transcribed. Please speak clearly and try again."}
        ), 422

    minutes, seconds = split_duration(duration_seconds)
    wpm = calculate_wpm(word_count, speaking_seconds)
    fillers = count_fillers(text)
    filler_ratio = fillers / word_count

    emotion = detect_emotion(wpm, filler_ratio, word_count)
    score = calculate_confidence(wpm, filler_ratio, word_count)

    topic = request.form.get("topic", "").strip()
    topic_related, topic_matches, topic_match_ratio = is_topic_related(topic, text)
    if topic:
        if topic_related:
            topic_note = "Topic check: your speech appears related to the selected topic."
        else:
            topic_note = (
                "Topic check: your speech seems off-topic. Mention more topic-specific points "
                "in your response."
            )
    else:
        topic_note = "Topic check: no topic was provided for relevance scoring."

    progress_note = None
    previous_score = get_previous_score(g.user["id"])
    if previous_score is not None:
        delta = round(score - previous_score, 1)
        if delta > 0:
            progress_note = f"Progress update: your score improved by {delta} from your previous attempt."
        elif delta < 0:
            progress_note = (
                f"Progress update: score dropped by {abs(delta)} from your last attempt. "
                "Focus on pace and reduce fillers in your next run."
            )
        else:
            progress_note = "Progress update: your score is stable compared to your previous attempt."

    feedback = build_feedback(
        emotion=emotion,
        wpm=wpm,
        filler_count=fillers,
        filler_ratio=filler_ratio,
        score=score,
        progress_note=progress_note,
        topic_note=topic_note,
    )

    history_count = save_analysis_record(
        g.user["id"],
        {
            "topic": topic,
            "transcription": text,
            "transcription_engine": engine,
            "duration": round(duration_seconds, 2),
            "speaking_duration": round(speaking_seconds, 2),
            "minutes": minutes,
            "seconds": seconds,
            "word_count": word_count,
            "wpm": wpm,
            "filler_count": fillers,
            "filler_ratio": round(filler_ratio, 4),
            "emotion": emotion,
            "score": score,
            "feedback": feedback,
            "audio_filename": audio_filename,
            "wav_filename": wav_filename,
        },
    )

    return jsonify(
        {
            "transcription": text,
            "transcription_engine": engine,
            "minutes": minutes,
            "seconds": seconds,
            "speaking_seconds": round(speaking_seconds, 1),
            "wpm": wpm,
            "word_count": word_count,
            "filler_count": fillers,
            "filler_ratio": round(filler_ratio, 4),
            "emotion": emotion,
            "score": score,
            "confidence_score": score,
            "topic_related": topic_related,
            "topic_match_ratio": topic_match_ratio,
            "topic_matched_words": topic_matches[:5],
            "feedback": feedback,
            "history_count": history_count,
        }
    )


if __name__ == "__main__":
    app.run(debug=True)
