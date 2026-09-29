from flask import Flask, g, jsonify, redirect, request, send_from_directory, session
import json
import logging
import os
import re
import secrets
import sqlite3
import tempfile
import threading
from datetime import datetime, timedelta
from functools import wraps
from uuid import uuid4
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Load API keys and settings from backend/.env before the analysis modules read them.
load_dotenv(os.path.join(BASE_DIR, ".env"))

from analysis import AnalysisError, analyze_recording, coach, evaluation, llm, modes, relevance, slides, warm_up  # noqa: E402
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

CREATE TABLE IF NOT EXISTS decks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    filename TEXT NOT NULL,
    topic TEXT,
    target_seconds INTEGER,
    content TEXT NOT NULL,
    checks TEXT NOT NULL,
    review TEXT
);
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
        "SELECT * FROM analysis_records WHERE id = ? AND user_id = ?", (record_id, user_id)
    ).fetchone()


AUDIO_TYPES = {".webm": "audio/webm", ".ogg": "audio/ogg", ".mp4": "audio/mp4", ".wav": "audio/wav"}


def session_payload(record):
    """A saved session in the same shape as the /analyze response, so the UI renders both the same way."""
    details = json.loads(record["details"] or "{}")
    mode = modes.get_mode((details.get("context") or {}).get("mode") or record["mode"])
    audio = record["audio_filename"]
    has_audio = bool(audio) and os.path.isfile(os.path.join(UPLOAD_FOLDER, audio))
    return {
        **details,
        "id": record["id"],
        "timestamp": record["created_at"],
        "mode": mode["id"],
        "topic": record["topic"],
        "transcription": record["transcription"],
        "transcription_engine": record["transcription_engine"],
        "minutes": record["minutes"],
        "seconds": record["seconds"],
        "score": record["score"],
        "delivery": record["emotion"],
        "feedback": record["feedback"],
        "metrics": details.get("metrics")
        or {"wpm": record["wpm"], "filler_count": record["filler_count"], "speaking_span": record["speaking_duration"] or 0},
        "audio_url": f"/analyses/{record['id']}/audio" if has_audio else None,
        "coach_available": mode.get("coach") is not None and llm.get_config() is not None and "metrics" in details,
    }


def get_user_deck(user_id, deck_id):
    return get_db().execute("SELECT * FROM decks WHERE id = ? AND user_id = ?", (deck_id, user_id)).fetchone()


def deck_summary(deck_row):
    deck = json.loads(deck_row["content"])
    return {
        "id": deck_row["id"],
        "filename": deck["filename"],
        "format": deck["format"],
        "topic": deck_row["topic"],
        "target_seconds": deck_row["target_seconds"],
        "slides": [
            {key: slide[key] for key in ("number", "title", "word_count", "bullets", "images")} for slide in deck["slides"]
        ],
        "checks": json.loads(deck_row["checks"]),
        "review": json.loads(deck_row["review"]) if deck_row["review"] else None,
        "review_available": llm.get_config() is not None,
    }


def parse_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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
    return redirect("/#/progress")


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
    deck = None
    deck_id = parse_int(request.form.get("deck_id"))
    if mode["prompt"].get("slides") and deck_id:
        deck_row = get_user_deck(g.user["id"], deck_id)
        if deck_row:
            deck = json.loads(deck_row["content"])
            context["deck"] = {
                "id": deck_row["id"],
                "filename": deck["filename"],
                "slide_count": len(deck["slides"]),
                "outline": slides.outline(deck),
            }
    result = evaluation.evaluate(base, mode, context, deck)
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
        **{
            key: result[key]
            for key in ("sub_scores", "metrics", "warnings", "topic_match", "language", "reading", "referee", "trends", "slides_match")
        },
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
    return jsonify({**session_payload(get_user_record(g.user["id"], record_id)), "history_count": history_count})


@app.route("/analyses/<int:record_id>", methods=["GET"])
@login_required
def analysis_detail(record_id):
    record = get_user_record(g.user["id"], record_id)
    if record is None:
        return jsonify({"error": "Session not found."}), 404
    return jsonify(session_payload(record))


@app.route("/analyses/<int:record_id>/audio", methods=["GET"])
@login_required
def analysis_audio(record_id):
    record = get_user_record(g.user["id"], record_id)
    filename = record["audio_filename"] if record else None
    if not filename or not os.path.isfile(os.path.join(UPLOAD_FOLDER, filename)):
        return jsonify({"error": "Recording not available."}), 404
    mimetype = AUDIO_TYPES.get(os.path.splitext(filename)[1].lower(), "application/octet-stream")
    return send_from_directory(UPLOAD_FOLDER, filename, mimetype=mimetype, conditional=True)


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
    dimensions = list(modes.coach_dimensions(mode))
    if context.get("deck"):
        dimensions.append(("alignment", "Matches your slides"))
    analysis = {
        "metrics": details["metrics"],
        "score": record["score"],
        "delivery": record["emotion"],
        "slides_match": details.get("slides_match"),
    }
    try:
        coaching = coach.coach_answer(record["transcription"], context, analysis, config, mode["coach"], dimensions)
    except llm.LLMError as error:
        return jsonify({"error": error.message, "retryable": error.retryable}), error.status_code

    details["coach"] = coaching
    update_record_details(record_id, details)
    return jsonify({"coach": coaching, "cached": False})


@app.route("/decks", methods=["POST"])
@login_required
def upload_deck():
    """Parses an uploaded .pptx/.pdf and runs the instant checks. Only the extracted text is kept."""
    file = request.files.get("deck")
    if not file or not file.filename:
        return jsonify({"error": "Choose a .pptx or .pdf file to upload."}), 400
    extension = os.path.splitext(file.filename)[1].lower()
    if extension not in slides.SUPPORTED_EXTENSIONS:
        return jsonify({"error": "Upload a PowerPoint (.pptx) or PDF file."}), 400

    topic = (request.form.get("topic") or "").strip()[: modes.MAX_CUSTOM_PROMPT]
    target_seconds = parse_int(request.form.get("target_seconds"))
    handle, temp_path = tempfile.mkstemp(suffix=extension)
    os.close(handle)
    try:
        file.save(temp_path)
        deck = slides.parse_deck(temp_path, file.filename)
    except slides.DeckError as error:
        return jsonify({"error": str(error)}), 400
    finally:
        discard_files(temp_path)

    checks = slides.check_deck(deck, topic, target_seconds)
    db = get_db()
    cursor = db.execute(
        "INSERT INTO decks (user_id, created_at, filename, topic, target_seconds, content, checks) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (g.user["id"], current_timestamp(), deck["filename"], topic, target_seconds, json.dumps(deck), json.dumps(checks)),
    )
    db.commit()
    return jsonify(deck_summary(get_user_deck(g.user["id"], cursor.lastrowid))), 201


@app.route("/decks/<int:deck_id>/review", methods=["POST"])
@login_required
def review_deck(deck_id):
    """AI review of the slides against the topic; regenerated only when the topic or target changes."""
    deck_row = get_user_deck(g.user["id"], deck_id)
    if deck_row is None:
        return jsonify({"error": "Slides not found."}), 404
    payload = request.get_json(silent=True) or {}
    topic = (payload.get("topic") or deck_row["topic"] or "").strip()[: modes.MAX_CUSTOM_PROMPT]
    target_seconds = parse_int(payload.get("target_seconds")) or deck_row["target_seconds"]
    deck = json.loads(deck_row["content"])

    db = get_db()
    if topic != (deck_row["topic"] or "") or target_seconds != deck_row["target_seconds"]:
        checks = slides.check_deck(deck, topic, target_seconds)
        db.execute(
            "UPDATE decks SET topic = ?, target_seconds = ?, checks = ?, review = NULL WHERE id = ?",
            (topic, target_seconds, json.dumps(checks), deck_id),
        )
        db.commit()
        deck_row = get_user_deck(g.user["id"], deck_id)
    elif deck_row["review"]:
        return jsonify(deck_summary(deck_row))

    config = llm.get_config()
    if config is None:
        return jsonify({"error": "The AI coach is not configured on this server.", "code": "coach_disabled"}), 503
    try:
        review = coach.review_deck(slides.outline(deck, max_chars=3000), topic, target_seconds, json.loads(deck_row["checks"]), config)
    except llm.LLMError as error:
        return jsonify({"error": error.message, "retryable": error.retryable}), error.status_code
    db.execute("UPDATE decks SET review = ? WHERE id = ?", (json.dumps(review), deck_id))
    db.commit()
    return jsonify(deck_summary(get_user_deck(g.user["id"], deck_id)))


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
