import os
import hashlib
import threading
import json
import time
import math
import random

from flask import Flask, request, jsonify, send_from_directory, abort

from database import init_db, get_db, row_to_dict

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(__file__)
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
WAVEFORM_DIR = os.path.join(BASE_DIR, "waveforms")
STATIC_DIR = os.path.join(BASE_DIR, "static")
ALLOWED_EXTENSIONS = {".mp3", ".aac", ".m4a"}

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 200 MB

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(WAVEFORM_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def allowed_file(filename: str) -> bool:
    return os.path.splitext(filename.lower())[1] in ALLOWED_EXTENSIONS


def file_md5(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_metadata(path: str, ext: str) -> dict:
    """Extract audio metadata using mutagen."""
    meta = {
        "title": "",
        "artist": "",
        "duration": 0.0,
        "sample_rate": 0,
        "channels": 0,
        "bitrate": 0,
        "format": ext.lstrip(".").upper(),
    }
    try:
        from mutagen import File as MutaFile
        audio = MutaFile(path, easy=True)
        if audio is None:
            return meta

        # Duration / info
        if hasattr(audio, "info"):
            info = audio.info
            meta["duration"] = round(getattr(info, "length", 0.0), 2)
            meta["sample_rate"] = getattr(info, "sample_rate", 0)
            meta["channels"] = getattr(info, "channels", 0)
            meta["bitrate"] = getattr(info, "bitrate", 0)

        # Tags
        tags = audio.tags or {}
        title_tag = tags.get("title") or tags.get("TIT2") or []
        artist_tag = tags.get("artist") or tags.get("TPE1") or []
        if isinstance(title_tag, list):
            meta["title"] = str(title_tag[0]) if title_tag else ""
        else:
            meta["title"] = str(title_tag)
        if isinstance(artist_tag, list):
            meta["artist"] = str(artist_tag[0]) if artist_tag else ""
        else:
            meta["artist"] = str(artist_tag)
    except Exception as exc:
        app.logger.warning("mutagen error: %s", exc)

    return meta


# ---------------------------------------------------------------------------
# Waveform generation (background thread)
# ---------------------------------------------------------------------------

WAVEFORM_POINTS = 1000


def _generate_waveform_mock(song_id: int, duration: float) -> list:
    """Produce a convincing mock waveform when audio decoding is unavailable."""
    random.seed(song_id)
    pts = []
    for i in range(WAVEFORM_POINTS):
        t = i / WAVEFORM_POINTS
        # Combine several sine waves to look music-like
        val = (
            0.5 * math.sin(2 * math.pi * t * 3)
            + 0.3 * math.sin(2 * math.pi * t * 7 + 1.2)
            + 0.2 * math.sin(2 * math.pi * t * 15 + 0.5)
        )
        # Add slight randomness
        val += random.gauss(0, 0.05)
        # Soft clamp to [-1, 1]
        val = max(-1.0, min(1.0, val))
        pts.append(round(val, 4))
    return pts


def _generate_waveform_real(path: str) -> list:
    """Try to decode audio and compute amplitude envelope."""
    import numpy as np

    # Try soundfile first (lossless-friendly)
    try:
        import soundfile as sf
        data, sr = sf.read(path, dtype="float32", always_2d=True)
        mono = data.mean(axis=1)
    except Exception:
        # Fall back to pydub
        from pydub import AudioSegment
        seg = AudioSegment.from_file(path)
        samples = np.array(seg.get_array_of_samples(), dtype="float32")
        if seg.channels == 2:
            samples = samples.reshape(-1, 2).mean(axis=1)
        peak = float(2 ** (seg.sample_width * 8 - 1))
        mono = samples / peak

    # Downsample to WAVEFORM_POINTS via RMS chunks
    n = len(mono)
    chunk = max(1, n // WAVEFORM_POINTS)
    pts = []
    for i in range(WAVEFORM_POINTS):
        start = i * chunk
        end = min(start + chunk, n)
        if start >= n:
            pts.append(0.0)
        else:
            rms = float(np.sqrt(np.mean(mono[start:end] ** 2)))
            pts.append(round(rms, 4))

    # Normalise to [0, 1] (RMS is always non-negative)
    mx = max(pts) or 1.0
    pts = [round(v / mx, 4) for v in pts]
    return pts


def _waveform_worker(song_id: int, file_path: str, duration: float):
    waveform_file = os.path.join(WAVEFORM_DIR, f"{song_id}.json")
    db = get_db()
    try:
        db.execute(
            "UPDATE songs SET status='waveform_generating' WHERE id=?", (song_id,)
        )
        db.commit()

        try:
            pts = _generate_waveform_real(file_path)
            source = "real"
        except Exception as exc:
            app.logger.warning("Real waveform failed (%s), using mock", exc)
            pts = _generate_waveform_mock(song_id, duration)
            source = "mock"

        payload = {"song_id": song_id, "points": pts, "source": source}
        with open(waveform_file, "w") as f:
            json.dump(payload, f)

        db.execute(
            "UPDATE songs SET status='waveform_ready' WHERE id=?", (song_id,)
        )
        db.execute(
            """UPDATE analysis_tasks SET status='done', result_json=?, updated_at=CURRENT_TIMESTAMP
               WHERE song_id=? AND task_type='waveform'""",
            (json.dumps({"points": len(pts), "source": source}), song_id),
        )
    except Exception as exc:
        app.logger.error("Waveform worker error song %d: %s", song_id, exc)
        db.execute(
            "UPDATE songs SET status='analysis_failed', error_message=? WHERE id=?",
            (str(exc), song_id),
        )
        db.execute(
            """UPDATE analysis_tasks SET status='failed', updated_at=CURRENT_TIMESTAMP
               WHERE song_id=? AND task_type='waveform'""",
            (song_id,),
        )
    finally:
        db.commit()
        db.close()


def start_waveform_task(song_id: int, file_path: str, duration: float):
    db = get_db()
    db.execute(
        "INSERT INTO analysis_tasks (song_id, task_type, status) VALUES (?,?,?)",
        (song_id, "waveform", "pending"),
    )
    db.commit()
    db.close()
    t = threading.Thread(
        target=_waveform_worker, args=(song_id, file_path, duration), daemon=True
    )
    t.start()


# ---------------------------------------------------------------------------
# Routes – static
# ---------------------------------------------------------------------------


@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


# ---------------------------------------------------------------------------
# API – upload
# ---------------------------------------------------------------------------


@app.route("/api/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"error": "No file part"}), 400

    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "No selected file"}), 400

    original_name = f.filename
    ext = os.path.splitext(original_name.lower())[1]
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({"error": f"Unsupported format: {ext}. Allowed: mp3, aac, m4a"}), 400

    # Save to temp location to compute hash
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext, dir=UPLOAD_DIR) as tmp:
        f.save(tmp.name)
        tmp_path = tmp.name

    file_size = os.path.getsize(tmp_path)
    file_hash = file_md5(tmp_path)

    # Duplicate detection
    db = get_db()
    existing = db.execute(
        "SELECT s.id, s.title, s.artist, s.status FROM songs s "
        "JOIN audio_assets a ON a.song_id = s.id "
        "WHERE s.file_hash=? AND s.file_size=?",
        (file_hash, file_size),
    ).fetchone()
    if existing:
        os.unlink(tmp_path)
        db.close()
        return jsonify({"duplicate": True, "song": row_to_dict(existing)}), 409

    meta = extract_metadata(tmp_path, ext)

    title = meta["title"] or os.path.splitext(original_name)[0]
    artist = meta["artist"] or "Unknown Artist"

    # Rename to stable name
    safe_name = f"{file_hash}{ext}"
    dest_path = os.path.join(UPLOAD_DIR, safe_name)
    os.rename(tmp_path, dest_path)

    song_id = db.execute(
        """INSERT INTO songs
           (title, artist, duration, file_size, format, sample_rate, channels, bitrate,
            file_hash, status, source)
           VALUES (?,?,?,?,?,?,?,?,?,'parsed','local')""",
        (
            title, artist,
            meta["duration"], file_size, meta["format"],
            meta["sample_rate"], meta["channels"], meta["bitrate"],
            file_hash,
        ),
    ).lastrowid

    db.execute(
        "INSERT INTO audio_assets (song_id, file_path, file_name, original_file_name) VALUES (?,?,?,?)",
        (song_id, dest_path, safe_name, original_name),
    )
    db.execute(
        "INSERT OR IGNORE INTO user_library_items (song_id, user_id) VALUES (?, 'default_user')",
        (song_id,),
    )
    db.commit()
    db.close()

    # Start async waveform generation
    start_waveform_task(song_id, dest_path, meta["duration"])

    return jsonify({"success": True, "song_id": song_id, "title": title, "artist": artist}), 201


# ---------------------------------------------------------------------------
# API – library
# ---------------------------------------------------------------------------


@app.route("/api/library")
def get_library():
    db = get_db()
    rows = db.execute(
        """SELECT s.*, uli.added_at
           FROM user_library_items uli
           JOIN songs s ON s.id = uli.song_id
           WHERE uli.user_id = 'default_user'
           ORDER BY uli.added_at DESC"""
    ).fetchall()
    db.close()
    return jsonify([row_to_dict(r) for r in rows])


@app.route("/api/song/<int:song_id>")
def get_song(song_id):
    db = get_db()
    row = db.execute("SELECT * FROM songs WHERE id=?", (song_id,)).fetchone()
    db.close()
    if row is None:
        return jsonify({"error": "Not found"}), 404
    return jsonify(row_to_dict(row))


@app.route("/api/waveform/<int:song_id>")
def get_waveform(song_id):
    waveform_file = os.path.join(WAVEFORM_DIR, f"{song_id}.json")
    if not os.path.exists(waveform_file):
        db = get_db()
        row = db.execute("SELECT status FROM songs WHERE id=?", (song_id,)).fetchone()
        db.close()
        if row is None:
            return jsonify({"error": "Song not found"}), 404
        return jsonify({"status": row["status"], "points": []}), 202
    with open(waveform_file) as f:
        data = json.load(f)
    return jsonify(data)


@app.route("/api/library/<int:song_id>", methods=["DELETE"])
def remove_from_library(song_id):
    db = get_db()
    db.execute(
        "DELETE FROM user_library_items WHERE song_id=? AND user_id='default_user'",
        (song_id,),
    )
    db.commit()
    db.close()
    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# API – search
# ---------------------------------------------------------------------------


@app.route("/api/search")
def search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"my_library": [], "platform": []})

    like = f"%{q}%"
    db = get_db()

    my_rows = db.execute(
        """SELECT s.*
           FROM songs s
           JOIN user_library_items uli ON uli.song_id = s.id
           WHERE uli.user_id='default_user'
             AND (s.title LIKE ? OR s.artist LIKE ?)""",
        (like, like),
    ).fetchall()

    platform_rows = db.execute(
        "SELECT * FROM platform_songs WHERE title LIKE ? OR artist LIKE ?",
        (like, like),
    ).fetchall()
    db.close()

    return jsonify(
        {
            "my_library": [row_to_dict(r) for r in my_rows],
            "platform": [row_to_dict(r) for r in platform_rows],
        }
    )


# ---------------------------------------------------------------------------
# API – add platform song to library
# ---------------------------------------------------------------------------


@app.route("/api/library/add/<int:platform_song_id>", methods=["POST"])
def add_platform_song(platform_song_id):
    db = get_db()
    ps = db.execute(
        "SELECT * FROM platform_songs WHERE id=?", (platform_song_id,)
    ).fetchone()
    if ps is None:
        db.close()
        return jsonify({"error": "Platform song not found"}), 404

    ps = row_to_dict(ps)

    # Check if already added (match by title+artist from platform)
    existing = db.execute(
        "SELECT s.id FROM songs s "
        "JOIN user_library_items uli ON uli.song_id=s.id "
        "WHERE s.title=? AND s.artist=? AND s.source='platform' AND uli.user_id='default_user'",
        (ps["title"], ps["artist"]),
    ).fetchone()
    if existing:
        db.close()
        return jsonify({"already_added": True, "song_id": existing["id"]}), 200

    song_id = db.execute(
        """INSERT INTO songs (title, artist, duration, format, status, source)
           VALUES (?,?,?,'stream','waveform_ready','platform')""",
        (ps["title"], ps["artist"], ps["duration"]),
    ).lastrowid
    db.execute(
        "INSERT OR IGNORE INTO user_library_items (song_id, user_id) VALUES (?,'default_user')",
        (song_id,),
    )
    db.commit()
    db.close()
    return jsonify({"success": True, "song_id": song_id}), 201


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(debug=debug_mode, host="0.0.0.0", port=5000)
else:
    # When imported (e.g., for testing), still init the DB
    init_db()
