from flask import Flask, g, jsonify, request, send_from_directory, session
import json
import logging
import os
import re
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta
from functools import wraps
from uuid import uuid4
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Load API keys and settings from backend/.env before the analysis modules read them.
load_dotenv(os.path.join(BASE_DIR, ".env"))

from analysis import AnalysisError, analyze_recording, coach, evaluation, llm, modes, relevance, warm_up  # noqa: E402
from analysis.scoring import build_feedback  # noqa: E402
import progress  # noqa: E402

UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", os.path.join(BASE_DIR, "uploads"))
DB_FILE = os.getenv("DATABASE_PATH", os.path.join(BASE_DIR, "app_data.db"))
SECRET_KEY_FILE = os.path.join(BASE_DIR, ".secret_key")
FRONTEND_DIR = os.path.join(BASE_DIR, "..", "frontend")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

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
    wav_filename TEXT,
    details TEXT,
    mode TEXT
);

CREATE INDEX IF NOT EXISTS idx_analysis_records_user ON analysis_records (user_id, created_at);
"""

# Columns added after the first release; init_db adds them to older databases.
ADDED_COLUMNS = {"analysis_records": {"details": "TEXT", "mode": "TEXT"}}

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
    "details",
    "mode",
)

HISTORY_COLUMNS = (
    "created_at AS timestamp, topic, transcription, transcription_engine, duration, speaking_duration, "
    "minutes, seconds, word_count, wpm, filler_count, filler_ratio, emotion AS delivery, score, feedback, details, mode"
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
        for table, columns in ADDED_COLUMNS.items():
            existing = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
            for column, column_type in columns.items():
                if column not in existing:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")
        db.commit()
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
    entries = []
    for row in rows:
        entry = dict(row)
        details = json.loads(entry.pop("details") or "{}")
        entry["sub_scores"] = details.get("sub_scores")
        entries.append(entry)
    return entries


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
    cursor = db.execute(f"INSERT INTO analysis_records ({', '.join(columns)}) VALUES ({placeholders})", values)
    db.commit()
    count = db.execute("SELECT COUNT(*) FROM analysis_records WHERE user_id = ?", (user_id,)).fetchone()[0]
    return cursor.lastrowid, count


def get_user_record(user_id, record_id):
    return get_db().execute(
        "SELECT id, transcription, score, emotion, details, mode FROM analysis_records WHERE id = ? AND user_id = ?",
        (record_id, user_id),
    ).fetchone()


def update_record_details(record_id, details):
    db = get_db()
    db.execute("UPDATE analysis_records SET details = ? WHERE id = ?", (json.dumps(details), record_id))
    db.commit()


def discard_files(*paths):
    for path in paths:
        if os.path.exists(path):
            os.remove(path)


def split_duration(duration_seconds):
    total_seconds = max(0, int(round(duration_seconds or 0)))
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return minutes, seconds


def build_progress_note(user_id, score):
    previous_score = get_previous_score(user_id)
    if previous_score is None:
        return None
    delta = round(score - previous_score, 1)
    if delta > 0:
        return f"Progress update: your score improved by {delta} from your previous attempt."
    if delta < 0:
        return (
            f"Progress update: score dropped by {abs(delta)} from your last attempt. "
            "Focus on your weakest area in the next run."
        )
    return "Progress update: your score is stable compared to your previous attempt."


def build_topic_note(context, topic_match):
    if context["mode"] == "read":
        return None
    if topic_match is None:
        return "Topic check: no topic was provided for relevance scoring."
    if context["mode"] in ("interview", "pitch", "debate"):
        if topic_match["related"]:
            return "Relevance check: your answer addresses the prompt."
        return "Relevance check: your answer doesn't seem to address the prompt. Answer it directly first."
    if topic_match["related"]:
        return "Topic check: your speech stays on the selected topic."
    return "Topic check: your speech seems off-topic. Mention more topic-specific points in your response."


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


@app.route("/progress", methods=["GET"])
@login_required
def progress_summary():
    mode_filter = request.args.get("mode")
    return jsonify(progress.summarize(get_user_history(g.user["id"]), mode_filter if mode_filter in modes.MODES else None))


@app.route("/modes", methods=["GET"])
def mode_catalog():
    return jsonify({**modes.public_catalog(), "coach_available": llm.get_config() is not None})


@app.route("/analyze", methods=["POST"])
@login_required
def analyze():
    file = request.files.get("audio")
    if not file:
        return jsonify({"error": "Audio file is required."}), 400

    original_ext = os.path.splitext(file.filename or "")[1].lower() or ".webm"
    unique_id = f"{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}_{uuid4().hex[:8]}"
    audio_filename = f"{unique_id}{original_ext}"
    audio_path = os.path.join(UPLOAD_FOLDER, audio_filename)
    file.save(audio_path)

    try:
        base = analyze_recording(audio_path)
    except AnalysisError as error:
        discard_files(audio_path)
        return jsonify({"error": error.message}), error.status_code

    context = modes.build_context(request.form)
    mode = modes.get_mode(context["mode"])
    result = evaluation.evaluate(base, mode, context)
    metrics = result["metrics"]
    minutes, seconds = split_duration(metrics["duration"])
    feedback = build_feedback(
        result["score"],
        result["delivery"],
        result["sub_scores"],
        metrics,
        progress_note=build_progress_note(g.user["id"], result["score"]),
        topic_note=build_topic_note(context, result["topic_match"]),
        warnings=result["warnings"],
    )

    details = {
        **{key: base[key] for key in ("words", "pauses", "unclear_indexes", "uptalk", "timeline", "vocal_tone", "timings_ms")},
        **{key: result[key] for key in ("sub_scores", "metrics", "warnings", "topic_match", "language", "reading", "referee", "trends")},
        "context": context,
    }
    record_id, history_count = save_analysis_record(
        g.user["id"],
        {
            "topic": context["prompt"],
            "transcription": base["transcription"],
            "transcription_engine": base["transcription_model"],
            "duration": metrics["duration"],
            "speaking_duration": metrics["speaking_span"],
            "minutes": minutes,
            "seconds": seconds,
            "word_count": metrics["word_count"],
            "wpm": metrics["wpm"],
            "filler_count": metrics["filler_count"],
            "filler_ratio": round(metrics["filler_count"] / metrics["word_count"], 4),
            "emotion": result["delivery"],
            "score": result["score"],
            "feedback": feedback,
            "audio_filename": audio_filename,
            "wav_filename": None,
            "details": json.dumps(details),
            "mode": context["mode"],
        },
    )

    return jsonify(
        {
            **details,
            "id": record_id,
            "transcription": base["transcription"],
            "transcription_engine": base["transcription_model"],
            "minutes": minutes,
            "seconds": seconds,
            "score": result["score"],
            "delivery": result["delivery"],
            "feedback": feedback,
            "history_count": history_count,
            "coach_available": mode.get("coach") is not None and llm.get_config() is not None,
        }
    )


@app.route("/analyses/<int:record_id>/coach", methods=["POST"])
@login_required
def coach_analysis(record_id):
    """AI feedback on the content of a saved answer. Generated once, then served from the record."""
    record = get_user_record(g.user["id"], record_id)
    if record is None:
        return jsonify({"error": "Analysis not found."}), 404
    details = json.loads(record["details"] or "{}")
    if details.get("coach"):
        return jsonify({"coach": details["coach"], "cached": True})
    if "metrics" not in details:
        return jsonify({"error": "This session was recorded before AI coaching was available."}), 409

    context = details.get("context") or {"mode": modes.DEFAULT_MODE, "prompt": ""}
    mode = modes.get_mode(context.get("mode") or record["mode"])
    if mode.get("coach") is None:
        return jsonify({"error": f"AI coaching isn't available for {mode['label']} practice."}), 400
    config = llm.get_config()
    if config is None:
        return jsonify({"error": "The AI coach is not configured on this server.", "code": "coach_disabled"}), 503

    if not context.get("framework"):
        context["framework"] = modes.FRAMEWORKS.get(mode["framework"], modes.FRAMEWORKS["SPEECH"])
    analysis ={"metrics": details["metrics"], "score": record["score"], "delivery": record["emotion"]}
    try:
        coaching = coach.coach_answer(
            record["transcription"], context, analysis, config, mode["coach"], modes.coach_dimensions(mode)
        )
    except llm.LLMError as error:
        return jsonify({"error": error.message, "retryable": error.retryable}), error.status_code

    details["coach"] = coaching
    update_record_details(record_id, details)
    return jsonify({"coach": coaching, "cached": False})


def start_model_warm_up():
    def run():
        try:
            warm_up()
            relevance.warm_up()
        except Exception:
            app.logger.exception("Model warm-up failed; models will load on the first analysis instead.")

    threading.Thread(target=run, name="model-warm-up", daemon=True).start()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # With the debug reloader the script runs twice; only the serving child process loads models.
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        start_model_warm_up()
    app.run(debug=True)
