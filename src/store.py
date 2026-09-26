# -*- coding: utf-8 -*-
"""SQLite 存储：内容库、工具库、标签、指纹（增量+去重）、FTS 全文索引。"""
import json
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT UNIQUE,        -- 稳定指纹，用于增量
    kind TEXT,                      -- 灵感 / 工具
    title TEXT,
    summary TEXT,
    ocr_text TEXT,
    source_type TEXT,               -- image_old / image_v2 / text / doc / album
    source_ref TEXT,                -- 原始定位（路径或消息键）
    image_path TEXT,                -- 缓存图相对路径（无图为空）
    captured_at TEXT,               -- 内容时间(YYYY-MM 或完整)
    tool_name TEXT,
    url TEXT,
    phash TEXT,
    extra_json TEXT,
    created_at INTEGER
);
CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE
);
CREATE TABLE IF NOT EXISTS item_tags (
    item_id INTEGER, tag_id INTEGER,
    PRIMARY KEY (item_id, tag_id)
);
CREATE TABLE IF NOT EXISTS tools (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE,
    aliases_json TEXT,
    official_url TEXT,
    purpose TEXT,
    mention_count INTEGER DEFAULT 0,
    first_seen TEXT, last_seen TEXT
);
CREATE TABLE IF NOT EXISTS tool_items (
    tool_id INTEGER, item_id INTEGER,
    PRIMARY KEY (tool_id, item_id)
);
CREATE TABLE IF NOT EXISTS fingerprints (
    fingerprint TEXT PRIMARY KEY,
    status TEXT,                    -- processed / junk
    ts INTEGER
);
CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
    title, summary, ocr_text, tool_name,
    content='items', content_rowid='id', tokenize='unicode61'
);
CREATE TRIGGER IF NOT EXISTS items_ai AFTER INSERT ON items BEGIN
  INSERT INTO items_fts(rowid, title, summary, ocr_text, tool_name)
  VALUES (new.id, new.title, new.summary, new.ocr_text, new.tool_name);
END;
CREATE TRIGGER IF NOT EXISTS items_ad AFTER DELETE ON items BEGIN
  INSERT INTO items_fts(items_fts, rowid, title, summary, ocr_text, tool_name)
  VALUES ('delete', old.id, old.title, old.summary, old.ocr_text, old.tool_name);
END;
CREATE TRIGGER IF NOT EXISTS items_au AFTER UPDATE ON items BEGIN
  INSERT INTO items_fts(items_fts, rowid, title, summary, ocr_text, tool_name)
  VALUES ('delete', old.id, old.title, old.summary, old.ocr_text, old.tool_name);
  INSERT INTO items_fts(rowid, title, summary, ocr_text, tool_name)
  VALUES (new.id, new.title, new.summary, new.ocr_text, new.tool_name);
END;
"""


def connect(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=30000")
    con.executescript(SCHEMA)
    return con


def seen(con, fingerprint: str) -> bool:
    return con.execute("SELECT 1 FROM fingerprints WHERE fingerprint=?",
                       (fingerprint,)).fetchone() is not None


def mark(con, fingerprint: str, status: str):
    con.execute("INSERT OR REPLACE INTO fingerprints VALUES (?,?,?)",
                (fingerprint, status, int(time.time())))


def add_item(con, item: dict) -> int:
    cols = ["fingerprint", "kind", "title", "summary", "ocr_text", "source_type",
            "source_ref", "image_path", "captured_at", "tool_name", "url", "phash",
            "extra_json", "created_at"]
    vals = [item.get(c) for c in cols[:-1]] + [int(time.time())]
    cur = con.execute(f"INSERT OR IGNORE INTO items ({','.join(cols)}) "
                      f"VALUES ({','.join('?' * len(cols))})", vals)
    if cur.lastrowid:
        _attach_tags(con, cur.lastrowid, item.get("tags") or [])
    return cur.lastrowid


def _attach_tags(con, item_id: int, tags):
    for t in tags:
        t = (t or "").strip()
        if not t:
            continue
        con.execute("INSERT OR IGNORE INTO tags(name) VALUES (?)", (t,))
        tid = con.execute("SELECT id FROM tags WHERE name=?", (t,)).fetchone()[0]
        con.execute("INSERT OR IGNORE INTO item_tags VALUES (?,?)", (item_id, tid))


def upsert_tool(con, name: str, url: str, purpose: str, item_id: int, captured_at: str):
    name = (name or "").strip()
    if not name:
        return
    row = con.execute("SELECT id, mention_count, first_seen FROM tools WHERE name=?",
                      (name,)).fetchone()
    if row:
        con.execute("UPDATE tools SET mention_count=mention_count+1, last_seen=?,"
                    "official_url=COALESCE(NULLIF(official_url,''),?),"
                    "purpose=COALESCE(NULLIF(purpose,''),?) WHERE id=?",
                    (captured_at, url or "", purpose or "", row[0]))
        tid = row[0]
    else:
        cur = con.execute("INSERT INTO tools(name,aliases_json,official_url,purpose,"
                          "mention_count,first_seen,last_seen) VALUES (?,?,?,?,1,?,?)",
                          (name, "[]", url or "", purpose or "", captured_at, captured_at))
        tid = cur.lastrowid
    if item_id:
        con.execute("INSERT OR IGNORE INTO tool_items VALUES (?,?)", (tid, item_id))


def stats(con) -> dict:
    q = lambda s: con.execute(s).fetchone()[0]
    return {
        "items": q("SELECT COUNT(*) FROM items"),
        "inspiration": q("SELECT COUNT(*) FROM items WHERE kind='灵感'"),
        "tools": q("SELECT COUNT(*) FROM items WHERE kind='工具'"),
        "tool_cards": q("SELECT COUNT(*) FROM tools"),
        "junk": q("SELECT COUNT(*) FROM fingerprints WHERE status='junk'"),
        "processed": q("SELECT COUNT(*) FROM fingerprints"),
    }
