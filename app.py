"""
音频导入解析与平台内曲库搜索 - 桌面验证版
Flask 后端服务
"""
import os
import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path

import numpy as np
from flask import Flask, request, jsonify, send_from_directory, render_template, send_file

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024  # 200MB

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / 'uploads'
WAVEFORM_DIR = BASE_DIR / 'waveforms'
DB_PATH = BASE_DIR / 'music_library.db'

UPLOAD_DIR.mkdir(exist_ok=True)
WAVEFORM_DIR.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = {'.mp3', '.aac', '.m4a', '.flac', '.ogg', '.wav'}

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS songs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            artist TEXT DEFAULT '',
            album TEXT DEFAULT '',
            duration REAL DEFAULT 0,
            source TEXT DEFAULT 'local',
            platform_id TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS audio_assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            song_id INTEGER NOT NULL,
            file_path TEXT NOT NULL,
            file_name TEXT NOT NULL,
            file_size INTEGER DEFAULT 0,
            file_hash TEXT DEFAULT '',
            format TEXT DEFAULT '',
            sample_rate INTEGER DEFAULT 0,
            channels INTEGER DEFAULT 0,
            bitrate INTEGER DEFAULT 0,
            duration REAL DEFAULT 0,
            status TEXT DEFAULT 'uploaded',
            error_msg TEXT DEFAULT '',
            waveform_path TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (song_id) REFERENCES songs(id)
        );

        CREATE TABLE IF NOT EXISTS user_library (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            song_id INTEGER NOT NULL,
            added_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(song_id),
            FOREIGN KEY (song_id) REFERENCES songs(id)
        );

        CREATE TABLE IF NOT EXISTS platform_songs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            artist TEXT DEFAULT '',
            album TEXT DEFAULT '',
            duration REAL DEFAULT 0,
            genre TEXT DEFAULT '',
            description TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS analysis_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            song_id INTEGER NOT NULL,
            task_type TEXT DEFAULT 'waveform',
            status TEXT DEFAULT 'pending',
            result TEXT DEFAULT '',
            error_msg TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (song_id) REFERENCES songs(id)
        );
    """)
    conn.commit()
    _seed_platform_songs(conn)
    conn.close()


def _seed_platform_songs(conn):
    count = conn.execute("SELECT COUNT(*) FROM platform_songs").fetchone()[0]
    if count > 0:
        return
    sample_songs = [
        ("青花瓷", "周杰伦", "我很忙", 240.0, "国风", "古典国风风格，融合中国传统乐器"),
        ("七里香", "周杰伦", "七里香", 270.0, "流行", "经典情歌"),
        ("晴天", "周杰伦", "叶惠美", 269.0, "流行", "青春记忆"),
        ("稻香", "周杰伦", "魔杰座", 223.0, "流行", "励志田园风"),
        ("以父之名", "周杰伦", "叶惠美", 338.0, "流行/摇滚", "史诗级长歌"),
        ("告白气球", "周杰伦", "周杰伦的床边故事", 216.0, "流行", "浪漫法式风情"),
        ("夜曲", "周杰伦", "十一月的肖邦", 229.0, "流行", "钢琴曲"),
        ("说好不哭", "周杰伦/五月天阿信", "说好不哭", 227.0, "流行", "合唱情歌"),
        ("红颜如霜", "薛之谦", "初学者", 244.0, "流行", "细腻情感"),
        ("你还要我怎样", "薛之谦", "意外", 231.0, "流行", "流行情歌"),
        ("演员", "薛之谦", "意外", 220.0, "流行", "现象级热单"),
        ("认真的雪", "薛之谦", "薛之谦", 220.0, "流行", "清新雪景"),
        ("成都", "赵雷", "无法长大", 312.0, "民谣", "城市民谣代表作"),
        ("我记得", "赵雷", "赵雷", 265.0, "民谣", "质朴情感"),
        ("南方姑娘", "赵雷", "吉姆餐厅", 253.0, "民谣", "南方风情"),
        ("少年", "梦然", "少年", 283.0, "流行", "励志青春"),
        ("起风了", "买辣椒也用券", "起风了", 298.0, "流行", "网络爆款"),
        ("可能否", "里昂（梁博）", "可能否", 227.0, "流行", "治愈系"),
        ("平凡之路", "朴树", "我是歌手", 304.0, "摇滚/流行", "励志"),
        ("那些年", "胡夏", "那些年", 243.0, "流行", "青春回忆"),
    ]
    conn.executemany(
        "INSERT INTO platform_songs (title, artist, album, duration, genre, description) VALUES (?,?,?,?,?,?)",
        sample_songs
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def calc_file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def parse_audio_metadata(file_path: str):
    """Extract metadata using mutagen."""
    try:
        import mutagen
        from mutagen.mp3 import MP3
        from mutagen.mp4 import MP4
        from mutagen.flac import FLAC
        from mutagen.oggvorbis import OggVorbis

        meta = {
            'title': '',
            'artist': '',
            'album': '',
            'duration': 0.0,
            'sample_rate': 0,
            'channels': 0,
            'bitrate': 0,
            'format': '',
        }

        ext = Path(file_path).suffix.lower()
        audio = None

        if ext == '.mp3':
            audio = MP3(file_path)
            meta['format'] = 'MP3'
            meta['bitrate'] = getattr(audio.info, 'bitrate', 0)
            meta['sample_rate'] = getattr(audio.info, 'sample_rate', 0)
            meta['channels'] = getattr(audio.info, 'channels', 0)
            meta['duration'] = getattr(audio.info, 'length', 0.0)
            tags = audio.tags
            if tags:
                meta['title'] = str(tags.get('TIT2', [''])[0]) if tags.get('TIT2') else ''
                meta['artist'] = str(tags.get('TPE1', [''])[0]) if tags.get('TPE1') else ''
                meta['album'] = str(tags.get('TALB', [''])[0]) if tags.get('TALB') else ''

        elif ext in ('.m4a', '.aac', '.mp4'):
            audio = MP4(file_path)
            meta['format'] = 'M4A/AAC'
            meta['bitrate'] = getattr(audio.info, 'bitrate', 0)
            meta['sample_rate'] = getattr(audio.info, 'sample_rate', 0)
            meta['channels'] = getattr(audio.info, 'channels', 0)
            meta['duration'] = getattr(audio.info, 'length', 0.0)
            tags = audio.tags or {}
            meta['title'] = str(tags.get('\xa9nam', [''])[0]) if tags.get('\xa9nam') else ''
            meta['artist'] = str(tags.get('\xa9ART', [''])[0]) if tags.get('\xa9ART') else ''
            meta['album'] = str(tags.get('\xa9alb', [''])[0]) if tags.get('\xa9alb') else ''

        elif ext == '.flac':
            audio = FLAC(file_path)
            meta['format'] = 'FLAC'
            meta['sample_rate'] = getattr(audio.info, 'sample_rate', 0)
            meta['channels'] = getattr(audio.info, 'channels', 0)
            meta['bitrate'] = getattr(audio.info, 'bits_per_sample', 0) * meta['sample_rate'] * meta['channels']
            meta['duration'] = getattr(audio.info, 'length', 0.0)
            tags = audio.tags or {}
            meta['title'] = tags.get('title', [''])[0] if tags.get('title') else ''
            meta['artist'] = tags.get('artist', [''])[0] if tags.get('artist') else ''
            meta['album'] = tags.get('album', [''])[0] if tags.get('album') else ''

        elif ext == '.ogg':
            audio = OggVorbis(file_path)
            meta['format'] = 'OGG'
            meta['sample_rate'] = getattr(audio.info, 'sample_rate', 0)
            meta['channels'] = getattr(audio.info, 'channels', 0)
            meta['duration'] = getattr(audio.info, 'length', 0.0)
            tags = audio.tags or {}
            meta['title'] = tags.get('title', [''])[0] if tags.get('title') else ''
            meta['artist'] = tags.get('artist', [''])[0] if tags.get('artist') else ''
            meta['album'] = tags.get('album', [''])[0] if tags.get('album') else ''

        else:
            # Generic fallback
            audio = mutagen.File(file_path)
            if audio:
                meta['duration'] = getattr(audio.info, 'length', 0.0)
                meta['format'] = ext.upper().lstrip('.')

        return meta, None
    except Exception as e:
        return None, str(e)


def generate_waveform(file_path: str, waveform_path: str, num_points: int = 1000):
    """Generate waveform amplitude array from audio file."""
    try:
        import librosa
        y, sr = librosa.load(file_path, sr=None, mono=True, duration=None)
        # Downsample to num_points
        hop = max(1, len(y) // num_points)
        frames = []
        for i in range(num_points):
            start = i * hop
            end = min(start + hop, len(y))
            if start >= len(y):
                frames.append(0.0)
            else:
                chunk = y[start:end]
                frames.append(float(np.max(np.abs(chunk))))
        # Normalize
        max_val = max(frames) if max(frames) > 0 else 1.0
        frames = [round(v / max_val, 4) for v in frames]
        with open(waveform_path, 'w') as f:
            json.dump(frames, f)
        return True, None
    except Exception as e:
        return False, str(e)


def process_audio_async(asset_id: int, song_id: int, file_path: str, waveform_path: str):
    """Background thread: parse metadata + generate waveform."""
    conn = get_db()
    try:
        # Update status to parsing
        conn.execute(
            "UPDATE audio_assets SET status=? WHERE id=?",
            ('parsing', asset_id)
        )
        conn.commit()

        meta, err = parse_audio_metadata(file_path)
        if err or meta is None:
            conn.execute(
                "UPDATE audio_assets SET status=?, error_msg=? WHERE id=?",
                ('analysis_failed', err or 'parse error', asset_id)
            )
            conn.commit()
            return

        # Update asset with parsed info
        conn.execute("""
            UPDATE audio_assets SET
                status=?, format=?, sample_rate=?, channels=?, bitrate=?, duration=?
            WHERE id=?
        """, ('parsed', meta['format'], meta['sample_rate'], meta['channels'],
              meta['bitrate'], meta['duration'], asset_id))

        # Update song title/artist/album if empty
        song = conn.execute("SELECT * FROM songs WHERE id=?", (song_id,)).fetchone()
        if song:
            updates = {}
            if not song['title'] and meta['title']:
                updates['title'] = meta['title']
            if not song['artist'] and meta['artist']:
                updates['artist'] = meta['artist']
            if not song['album'] and meta['album']:
                updates['album'] = meta['album']
            if song['duration'] == 0 and meta['duration']:
                updates['duration'] = meta['duration']
            if updates:
                set_clause = ', '.join(f"{k}=?" for k in updates)
                conn.execute(
                    f"UPDATE songs SET {set_clause} WHERE id=?",
                    list(updates.values()) + [song_id]
                )
        conn.commit()

        # Generate waveform
        conn.execute(
            "UPDATE audio_assets SET status=? WHERE id=?",
            ('waveform_generating', asset_id)
        )
        conn.commit()

        ok, werr = generate_waveform(file_path, waveform_path)
        if ok:
            conn.execute(
                "UPDATE audio_assets SET status=?, waveform_path=? WHERE id=?",
                ('waveform_ready', waveform_path, asset_id)
            )
        else:
            conn.execute(
                "UPDATE audio_assets SET status=?, error_msg=? WHERE id=?",
                ('analysis_failed', werr or 'waveform error', asset_id)
            )
        conn.commit()
    except Exception as e:
        try:
            conn.execute(
                "UPDATE audio_assets SET status=?, error_msg=? WHERE id=?",
                ('analysis_failed', str(e), asset_id)
            )
            conn.commit()
        except Exception:
            pass
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/import', methods=['POST'])
def import_audio():
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': '未提供文件'}), 400

    f = request.files['file']
    if not f.filename:
        return jsonify({'success': False, 'error': '文件名为空'}), 400

    filename = f.filename
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({'success': False, 'error': f'不支持的格式: {ext}，支持 MP3/AAC/M4A/FLAC/OGG/WAV'}), 400

    # Save file temporarily to compute hash
    import tempfile
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            f.save(tmp.name)
            tmp_path = tmp.name

        file_size = os.path.getsize(tmp_path)
        file_hash = calc_file_hash(tmp_path)

        conn = get_db()
        try:
            # Deduplication check
            existing = conn.execute(
                "SELECT aa.id, aa.song_id, s.title, s.artist FROM audio_assets aa JOIN songs s ON s.id=aa.song_id WHERE aa.file_hash=? AND aa.file_size=?",
                (file_hash, file_size)
            ).fetchone()

            if existing:
                os.unlink(tmp_path)
                return jsonify({
                    'success': False,
                    'duplicate': True,
                    'error': f'文件已存在：{existing["title"] or filename}（{existing["artist"]}）',
                    'song_id': existing['song_id']
                }), 409

            # Determine title from filename (will be overwritten by metadata)
            stem = Path(filename).stem
            title = stem

            # Move file to uploads dir
            dest_filename = f"{file_hash[:16]}_{filename}"
            dest_path = str(UPLOAD_DIR / dest_filename)
            os.rename(tmp_path, dest_path)
            tmp_path = None

            # Create song record
            cur = conn.execute(
                "INSERT INTO songs (title, artist, album, source) VALUES (?,?,?,?)",
                (title, '', '', 'local')
            )
            song_id = cur.lastrowid

            # Create audio asset record
            waveform_path = str(WAVEFORM_DIR / f"waveform_{song_id}.json")
            cur2 = conn.execute("""
                INSERT INTO audio_assets
                    (song_id, file_path, file_name, file_size, file_hash, status)
                VALUES (?,?,?,?,?,?)
            """, (song_id, dest_path, filename, file_size, file_hash, 'uploaded'))
            asset_id = cur2.lastrowid

            # Add to user library
            conn.execute(
                "INSERT OR IGNORE INTO user_library (song_id) VALUES (?)",
                (song_id,)
            )
            conn.commit()

            # Start async processing
            t = threading.Thread(
                target=process_audio_async,
                args=(asset_id, song_id, dest_path, waveform_path),
                daemon=True
            )
            t.start()

            return jsonify({
                'success': True,
                'song_id': song_id,
                'asset_id': asset_id,
                'message': f'导入成功，正在后台解析音频...'
            })
        finally:
            conn.close()
    except Exception as e:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/library', methods=['GET'])
def get_library():
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT s.id, s.title, s.artist, s.album, s.duration, s.created_at,
                   aa.id as asset_id, aa.file_name, aa.file_size, aa.format,
                   aa.sample_rate, aa.channels, aa.bitrate, aa.status, aa.error_msg,
                   aa.waveform_path
            FROM user_library ul
            JOIN songs s ON s.id = ul.song_id
            LEFT JOIN audio_assets aa ON aa.song_id = s.id
            WHERE s.source = 'local'
            ORDER BY ul.added_at DESC
        """).fetchall()

        songs = []
        for r in rows:
            songs.append({
                'id': r['id'],
                'title': r['title'] or r['file_name'] or '未知歌曲',
                'artist': r['artist'] or '未知艺术家',
                'album': r['album'] or '',
                'duration': r['duration'],
                'duration_str': _fmt_duration(r['duration']),
                'created_at': r['created_at'],
                'asset_id': r['asset_id'],
                'file_name': r['file_name'],
                'file_size': r['file_size'],
                'file_size_str': _fmt_size(r['file_size']),
                'format': r['format'],
                'sample_rate': r['sample_rate'],
                'channels': r['channels'],
                'bitrate': r['bitrate'],
                'status': r['status'],
                'error_msg': r['error_msg'],
                'has_waveform': bool(r['waveform_path'] and os.path.exists(r['waveform_path'])),
            })
        return jsonify({'success': True, 'songs': songs})
    finally:
        conn.close()


@app.route('/api/song/<int:song_id>', methods=['GET'])
def get_song(song_id):
    conn = get_db()
    try:
        row = conn.execute("""
            SELECT s.id, s.title, s.artist, s.album, s.duration, s.created_at,
                   aa.id as asset_id, aa.file_name, aa.file_size, aa.format,
                   aa.sample_rate, aa.channels, aa.bitrate, aa.status, aa.error_msg,
                   aa.waveform_path, aa.file_path
            FROM songs s
            LEFT JOIN audio_assets aa ON aa.song_id = s.id
            WHERE s.id=?
        """, (song_id,)).fetchone()
        if not row:
            return jsonify({'success': False, 'error': '歌曲不存在'}), 404
        return jsonify({
            'success': True,
            'song': {
                'id': row['id'],
                'title': row['title'],
                'artist': row['artist'],
                'album': row['album'],
                'duration': row['duration'],
                'duration_str': _fmt_duration(row['duration']),
                'created_at': row['created_at'],
                'asset_id': row['asset_id'],
                'file_name': row['file_name'],
                'file_size': row['file_size'],
                'file_size_str': _fmt_size(row['file_size']),
                'format': row['format'],
                'sample_rate': row['sample_rate'],
                'channels': row['channels'],
                'bitrate': row['bitrate'],
                'status': row['status'],
                'error_msg': row['error_msg'],
                'has_waveform': bool(row['waveform_path'] and os.path.exists(row['waveform_path'])),
                'file_path': row['file_path'],
            }
        })
    finally:
        conn.close()


@app.route('/api/song/<int:song_id>/waveform', methods=['GET'])
def get_waveform(song_id):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT waveform_path FROM audio_assets WHERE song_id=?", (song_id,)
        ).fetchone()
        if not row or not row['waveform_path'] or not os.path.exists(row['waveform_path']):
            return jsonify({'success': False, 'error': '波形数据尚未就绪'}), 404
        with open(row['waveform_path']) as f:
            data = json.load(f)
        return jsonify({'success': True, 'waveform': data})
    finally:
        conn.close()


@app.route('/api/song/<int:song_id>/stream')
def stream_audio(song_id):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT file_path FROM audio_assets WHERE song_id=?", (song_id,)
        ).fetchone()
        if not row or not os.path.exists(row['file_path']):
            return jsonify({'error': '文件不存在'}), 404
        return send_file(row['file_path'], conditional=True)
    finally:
        conn.close()


@app.route('/api/search', methods=['GET'])
def search():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify({'success': True, 'my_library': [], 'platform': []})

    conn = get_db()
    try:
        like = f'%{q}%'

        # Search user library
        my_rows = conn.execute("""
            SELECT s.id, s.title, s.artist, s.album, s.duration,
                   aa.format, aa.status, aa.file_size
            FROM user_library ul
            JOIN songs s ON s.id = ul.song_id
            LEFT JOIN audio_assets aa ON aa.song_id = s.id
            WHERE s.title LIKE ? OR s.artist LIKE ? OR s.album LIKE ?
            ORDER BY s.title
        """, (like, like, like)).fetchall()

        my_songs = [{
            'id': r['id'],
            'title': r['title'],
            'artist': r['artist'] or '未知艺术家',
            'album': r['album'] or '',
            'duration': r['duration'],
            'duration_str': _fmt_duration(r['duration']),
            'format': r['format'],
            'status': r['status'],
            'file_size_str': _fmt_size(r['file_size']),
            'in_library': True,
        } for r in my_rows]

        # Search platform library
        plat_rows = conn.execute("""
            SELECT p.id, p.title, p.artist, p.album, p.duration, p.genre, p.description,
                   ul.song_id IS NOT NULL as in_library
            FROM platform_songs p
            LEFT JOIN songs s ON s.platform_id = CAST(p.id AS TEXT) AND s.source='platform'
            LEFT JOIN user_library ul ON ul.song_id = s.id
            WHERE p.title LIKE ? OR p.artist LIKE ? OR p.album LIKE ?
            ORDER BY p.title
        """, (like, like, like)).fetchall()

        plat_songs = [{
            'id': r['id'],
            'title': r['title'],
            'artist': r['artist'],
            'album': r['album'] or '',
            'duration': r['duration'],
            'duration_str': _fmt_duration(r['duration']),
            'genre': r['genre'],
            'description': r['description'],
            'in_library': bool(r['in_library']),
            'source': 'platform',
        } for r in plat_rows]

        return jsonify({
            'success': True,
            'my_library': my_songs,
            'platform': plat_songs,
        })
    finally:
        conn.close()


@app.route('/api/platform/add', methods=['POST'])
def add_platform_song():
    """Add a platform song to user's personal library."""
    data = request.get_json()
    platform_id = data.get('platform_id')
    if not platform_id:
        return jsonify({'success': False, 'error': '缺少 platform_id'}), 400

    conn = get_db()
    try:
        prow = conn.execute(
            "SELECT * FROM platform_songs WHERE id=?", (platform_id,)
        ).fetchone()
        if not prow:
            return jsonify({'success': False, 'error': '平台歌曲不存在'}), 404

        # Check if already in library
        existing = conn.execute(
            "SELECT s.id FROM songs s JOIN user_library ul ON ul.song_id=s.id WHERE s.platform_id=? AND s.source='platform'",
            (str(platform_id),)
        ).fetchone()
        if existing:
            return jsonify({'success': False, 'duplicate': True, 'error': '已在个人曲库中', 'song_id': existing['id']}), 409

        cur = conn.execute(
            "INSERT INTO songs (title, artist, album, duration, source, platform_id) VALUES (?,?,?,?,?,?)",
            (prow['title'], prow['artist'], prow['album'], prow['duration'], 'platform', str(platform_id))
        )
        song_id = cur.lastrowid
        conn.execute("INSERT INTO user_library (song_id) VALUES (?)", (song_id,))
        conn.commit()

        return jsonify({'success': True, 'song_id': song_id, 'message': f'《{prow["title"]}》已加入个人曲库'})
    finally:
        conn.close()


@app.route('/api/song/<int:song_id>/delete', methods=['DELETE'])
def delete_song(song_id):
    conn = get_db()
    try:
        conn.execute("DELETE FROM user_library WHERE song_id=?", (song_id,))
        conn.execute("DELETE FROM audio_assets WHERE song_id=?", (song_id,))
        conn.execute("DELETE FROM songs WHERE id=?", (song_id,))
        conn.commit()
        return jsonify({'success': True})
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _fmt_duration(seconds):
    if not seconds:
        return '--:--'
    s = int(seconds)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _fmt_size(size_bytes):
    if not size_bytes:
        return '-'
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 ** 2:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / 1024 ** 2:.1f} MB"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    init_db()
    print("=" * 60)
    print("音频导入解析与平台内曲库搜索 - 桌面验证版")
    print("访问地址：http://localhost:5000")
    print("=" * 60)
    app.run(debug=False, host='0.0.0.0', port=5000, threaded=True)
