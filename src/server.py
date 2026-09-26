# -*- coding: utf-8 -*-
"""FastAPI 后端 + 本地网页界面。"""
import json
import os

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, store

app = FastAPI(title="灵感工具箱")
_CFG = None


def _con():
    return store.connect(config.db_path(_CFG))


def _fts_query(q: str) -> str:
    # 转成 FTS5 安全查询：按空白拆词，每词加 * 前缀匹配
    terms = [t for t in q.replace('"', " ").split() if t]
    return " ".join(f'"{t}"*' for t in terms) if terms else ""


@app.get("/api/stats")
def api_stats():
    con = _con()
    s = store.stats(con)
    con.close()
    return s


@app.get("/api/items")
def api_items(q: str = "", kind: str = "", tag: str = "",
              limit: int = 60, offset: int = 0):
    con = _con()
    where, args = ["kind != '垃圾'"], []
    if kind:
        where = ["kind = ?"]
        args = [kind]
    if tag:
        where.append("id IN (SELECT item_id FROM item_tags it "
                     "JOIN tags t ON t.id=it.tag_id WHERE t.name=?)")
        args.append(tag)
    base = " AND ".join(where)
    if q.strip():
        # 中文子串搜索：unicode61 分词对中文按整块切，无法词中匹配；
        # 数据量小(~千条)，直接 LIKE 子串，对中文最可靠。多词 AND。
        terms = [t for t in q.split() if t]
        for t in terms:
            base += " AND (title LIKE ? OR summary LIKE ? OR ocr_text LIKE ? OR tool_name LIKE ?)"
            args += [f"%{t}%"] * 4
        sql = (f"SELECT * FROM items WHERE {base} "
               f"ORDER BY captured_at DESC, id DESC LIMIT ? OFFSET ?")
        rows = con.execute(sql, args + [limit, offset]).fetchall()
    else:
        sql = (f"SELECT * FROM items WHERE {base} "
               f"ORDER BY captured_at DESC, id DESC LIMIT ? OFFSET ?")
        rows = con.execute(sql, args + [limit, offset]).fetchall()
    out = [_item_dict(con, r) for r in rows]
    con.close()
    return out


def _item_dict(con, r):
    tags = [x[0] for x in con.execute(
        "SELECT t.name FROM tags t JOIN item_tags it ON it.tag_id=t.id "
        "WHERE it.item_id=?", (r["id"],)).fetchall()]
    d = dict(r)
    d["tags"] = tags
    return d


@app.get("/api/tags")
def api_tags():
    con = _con()
    rows = con.execute(
        "SELECT t.name, COUNT(*) c FROM tags t JOIN item_tags it ON it.tag_id=t.id "
        "JOIN items i ON i.id=it.item_id WHERE i.kind!='垃圾' "
        "GROUP BY t.name ORDER BY c DESC").fetchall()
    con.close()
    return [{"name": r[0], "count": r[1]} for r in rows]


@app.get("/api/tools")
def api_tools():
    con = _con()
    rows = con.execute(
        "SELECT * FROM tools ORDER BY mention_count DESC, last_seen DESC").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        srcs = con.execute(
            "SELECT i.image_path, i.captured_at FROM items i "
            "JOIN tool_items ti ON ti.item_id=i.id WHERE ti.tool_id=? "
            "AND i.image_path!='' LIMIT 6", (r["id"],)).fetchall()
        d["sources"] = [dict(s) for s in srcs]
        out.append(d)
    con.close()
    return out


@app.get("/api/junk")
def api_junk(limit: int = 100, offset: int = 0):
    con = _con()
    rows = con.execute("SELECT * FROM items WHERE kind='垃圾' "
                       "ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
    out = [_item_dict(con, r) for r in rows]
    con.close()
    return out


@app.post("/api/recall/{item_id}")
def api_recall(item_id: int, kind: str = Query("灵感")):
    con = _con()
    con.execute("UPDATE items SET kind=? WHERE id=?", (kind, item_id))
    con.commit()
    con.close()
    return {"ok": True}


@app.post("/api/topics")
def api_topics(payload: dict):
    """灵感→选题：把选中的灵感（或某标签）交给 DeepSeek 归纳为内容选题。"""
    from . import classify
    key = config.deepseek_key(_CFG)
    if not key:
        return JSONResponse({"error": "未配置 DeepSeek key，无法生成选题"}, status_code=400)
    con = _con()
    ids = payload.get("ids") or []
    tag = payload.get("tag")
    if tag:
        rows = con.execute(
            "SELECT i.title, i.summary, i.ocr_text FROM items i "
            "JOIN item_tags it ON it.item_id=i.id JOIN tags t ON t.id=it.tag_id "
            "WHERE t.name=? AND i.kind='灵感' LIMIT 40", (tag,)).fetchall()
    elif ids:
        qmarks = ",".join("?" * len(ids))
        rows = con.execute(
            f"SELECT title, summary, ocr_text FROM items WHERE id IN ({qmarks})",
            ids).fetchall()
    else:
        con.close()
        return JSONResponse({"error": "请先选择灵感或标签"}, status_code=400)
    con.close()
    material = "\n".join(
        f"- {r['title'] or ''} {r['summary'] or ''} {(r['ocr_text'] or '')[:120]}"
        for r in rows)
    import requests
    ai = _CFG["ai"]
    prompt = ("以下是我收集的灵感素材，请帮我归纳成 5-8 个可创作的内容选题，"
              "每个选题给：标题、切入角度、适合平台(小红书/视频)、可用的素材点。\n\n" + material)
    body = {"model": ai["model"], "temperature": 0.6,
            "messages": [{"role": "user", "content": prompt}]}
    r = requests.post(ai["endpoint"], json=body, timeout=ai.get("timeout_sec", 60),
                      headers={"Authorization": f"Bearer {key}"})
    r.raise_for_status()
    return {"topics": r.json()["choices"][0]["message"]["content"]}


@app.get("/", response_class=HTMLResponse)
def index():
    p = os.path.join(config.ROOT, "src", "web", "index.html")
    return FileResponse(p)


def run(cfg):
    global _CFG
    _CFG = cfg
    import uvicorn
    cache = os.path.join(config.ROOT, "cache")
    if os.path.isdir(cache):
        app.mount("/cache", StaticFiles(directory=cache), name="cache")
    host, port = cfg["server"]["host"], cfg["server"]["port"]
    print(f"灵感工具箱已启动 → http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
