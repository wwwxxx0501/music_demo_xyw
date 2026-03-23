import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "music.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()

    c.executescript("""
        CREATE TABLE IF NOT EXISTS songs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT NOT NULL,
            artist      TEXT DEFAULT '',
            duration    REAL DEFAULT 0,
            file_size   INTEGER DEFAULT 0,
            format      TEXT DEFAULT '',
            sample_rate INTEGER DEFAULT 0,
            channels    INTEGER DEFAULT 0,
            bitrate     INTEGER DEFAULT 0,
            file_hash   TEXT DEFAULT '',
            status      TEXT DEFAULT 'uploaded',
            error_message TEXT DEFAULT '',
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
            source      TEXT DEFAULT 'local'
        );

        CREATE TABLE IF NOT EXISTS audio_assets (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            song_id           INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
            file_path         TEXT NOT NULL,
            file_name         TEXT NOT NULL,
            original_file_name TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS user_library_items (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            song_id    INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
            user_id    TEXT DEFAULT 'default_user',
            added_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(song_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS analysis_tasks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            song_id     INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
            task_type   TEXT NOT NULL,
            status      TEXT DEFAULT 'pending',
            result_json TEXT DEFAULT '',
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS platform_songs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT NOT NULL,
            artist      TEXT DEFAULT '',
            duration    REAL DEFAULT 0,
            genre       TEXT DEFAULT '',
            description TEXT DEFAULT ''
        );
    """)
    conn.commit()
    _seed_platform_songs(c, conn)
    conn.close()


PLATFORM_SONGS = [
    ("青花瓷",   "周杰伦", 235.0, "国语流行", "周杰伦2007年专辑《我很忙》中的歌曲"),
    ("晴天",     "周杰伦", 269.0, "国语流行", "周杰伦2003年专辑《叶惠美》中的歌曲"),
    ("七里香",   "周杰伦", 217.0, "国语流行", "周杰伦2004年专辑《七里香》中的歌曲"),
    ("稻香",     "周杰伦", 223.0, "国语流行", "周杰伦2008年专辑《魔杰座》中的歌曲"),
    ("江南",     "林俊杰", 240.0, "国语流行", "林俊杰2004年专辑《第二天堂》中的歌曲"),
    ("曹操",     "林俊杰", 244.0, "国语流行", "林俊杰2006年专辑《曹操》中的歌曲"),
    ("富士山下", "陈奕迅", 296.0, "国语流行", "陈奕迅2005年专辑《U87》中的歌曲"),
    ("十年",     "陈奕迅", 220.0, "粤语流行", "陈奕迅2003年粤语专辑中的歌曲"),
    ("爱情转移", "陈奕迅", 278.0, "国语流行", "陈奕迅2007年专辑中的歌曲"),
    ("成都",     "赵雷",   312.0, "民谣",     "赵雷2016年专辑《无法长大》中的歌曲"),
    ("南山南",   "马頔",   258.0, "民谣",     "马頔2014年代表作"),
    ("董小姐",   "宋冬野", 298.0, "民谣",     "宋冬野2013年代表作"),
    ("Shake It Off",  "Taylor Swift", 219.0, "Pop",     "Taylor Swift 2014 album 1989"),
    ("Love Story",    "Taylor Swift", 235.0, "Country Pop", "Taylor Swift 2008 album Fearless"),
    ("Blank Space",   "Taylor Swift", 231.0, "Pop",     "Taylor Swift 2014 album 1989"),
    ("Shape of You",  "Ed Sheeran",   234.0, "Pop",     "Ed Sheeran 2017 album ÷"),
    ("Perfect",       "Ed Sheeran",   263.0, "Pop",     "Ed Sheeran 2017 album ÷"),
    ("Thinking Out Loud", "Ed Sheeran", 281.0, "Soul Pop", "Ed Sheeran 2014 album X"),
    ("Rolling in the Deep", "Adele",  228.0, "Soul",    "Adele 2010 album 21"),
    ("Someone Like You",    "Adele",  285.0, "Soul",    "Adele 2011 album 21"),
]


def _seed_platform_songs(cursor, conn):
    count = cursor.execute("SELECT COUNT(*) FROM platform_songs").fetchone()[0]
    if count == 0:
        cursor.executemany(
            "INSERT INTO platform_songs (title, artist, duration, genre, description) VALUES (?,?,?,?,?)",
            PLATFORM_SONGS,
        )
        conn.commit()


def row_to_dict(row):
    if row is None:
        return None
    return dict(row)
