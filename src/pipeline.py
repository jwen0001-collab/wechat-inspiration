# -*- coding: utf-8 -*-
"""处理流程编排：本地采集/解码/去重/OCR/入库（ingest），AI 判定（classify_pending）。

两段分离：ingest 不需要联网，先把所有内容变成可搜索的库；
classify_pending 在有 DeepSeek key 时把"未分类"升级为 灵感/工具/垃圾 + 标签摘要。
"""
import os
import time

from . import classify, collect, config, dedup, ocr, store


def _fingerprint(item, image_bytes):
    import hashlib
    if image_bytes is not None:
        return "img:" + hashlib.sha256(image_bytes).hexdigest()
    return "txt:" + hashlib.sha256(item["source_ref"].encode()).hexdigest()


def ingest(cfg, do_ocr=True, log=print) -> dict:
    con = store.connect(config.db_path(cfg))
    cache = config.cache_dir(cfg)
    nd = dedup.NearDup(cfg.get("dedup", {}).get("phash_distance", 4))
    for (p,) in con.execute("SELECT phash FROM items WHERE phash IS NOT NULL"):
        nd.add(p)

    counts = {"new": 0, "dup_exact": 0, "dup_near": 0, "skipped": 0, "wxgf": 0, "ocr": 0}
    t0 = time.time()
    items = list(collect.collect_all(cfg))
    log(f"采集到 {len(items)} 条原子输入，开始处理…")

    for idx, item in enumerate(items):
        st = item["source_type"]
        image_bytes = item["load"]() if item.get("load") else None
        if item.get("load") and image_bytes is None:
            counts["skipped"] += 1
            continue

        fp = _fingerprint(item, image_bytes)
        if store.seen(con, fp):
            counts["dup_exact"] += 1
            continue

        phash = dedup.phash_of(image_bytes) if image_bytes else None
        if phash and nd.is_dup(phash):
            store.mark(con, fp, "processed")
            counts["dup_near"] += 1
            continue
        if phash:
            nd.add(phash)

        image_path = ""
        ocr_text = item.get("text") or ""
        if image_bytes is not None:
            ext = "png"
            try:
                from PIL import Image
                import io
                ext = (Image.open(io.BytesIO(image_bytes)).format or "PNG").lower()
                if ext == "jpeg":
                    ext = "jpg"
            except Exception:
                pass
            name = fp.split(":")[1][:32] + "." + ext
            with open(os.path.join(cache, name), "wb") as f:
                f.write(image_bytes)
            image_path = "cache/images/" + name
            if do_ocr:
                ocr_text = ocr.image_text(image_bytes)
                counts["ocr"] += 1

        rec = {
            "fingerprint": fp, "kind": "未分类", "title": "", "summary": "",
            "ocr_text": ocr_text, "source_type": st, "source_ref": item["source_ref"],
            "image_path": image_path, "captured_at": item.get("captured_at", ""),
            "tool_name": "", "url": item.get("url") or "", "phash": phash,
            "extra_json": "{}", "tags": [],
        }
        store.add_item(con, rec)
        store.mark(con, fp, "processed")
        counts["new"] += 1
        if (idx + 1) % 50 == 0:
            con.commit()
            log(f"  进度 {idx + 1}/{len(items)} | 新增 {counts['new']} | "
                f"精确重复 {counts['dup_exact']} | 近似重复 {counts['dup_near']} | "
                f"用时 {time.time() - t0:.0f}s")
    con.commit()
    log(f"ingest 完成：{counts} | 用时 {time.time() - t0:.0f}s")
    con.close()
    return counts


def classify_pending(cfg, batch_size=12, log=print) -> dict:
    key = config.deepseek_key(cfg)
    if not key:
        log("⚠ 未找到 DeepSeek key（secrets.json / 环境变量），跳过 AI 判定。")
        return {"error": "no_key"}
    con = store.connect(config.db_path(cfg))
    rows = con.execute(
        "SELECT id, ocr_text, url, source_type FROM items WHERE kind='未分类' "
        "AND (ocr_text != '' OR url != '')").fetchall()
    cap = cfg["ai"].get("max_items_per_run", 0)
    if cap and len(rows) > cap:
        log(f"待判定 {len(rows)} 条，按上限只处理前 {cap} 条。")
        rows = rows[:cap]
    log(f"AI 判定 {len(rows)} 条，批大小 {batch_size}…")

    total_in = total_out = 0
    done = 0
    junk = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        texts = [(r["ocr_text"] or "")[:1200] + (
            f"\n[链接]{r['url']}" if r["url"] else "") or "(空)" for r in batch]
        try:
            res, usage = classify.classify_batch(cfg, key, texts)
        except Exception as e:
            log(f"  批 {i} 失败：{str(e)[:80]}，重试一次…")
            time.sleep(3)
            try:
                res, usage = classify.classify_batch(cfg, key, texts)
            except Exception as e2:
                log(f"  批 {i} 再次失败，跳过：{str(e2)[:80]}")
                continue
        total_in += usage.get("prompt_tokens", 0)
        total_out += usage.get("completion_tokens", 0)
        for r, c in zip(batch, res):
            kind = c.get("kind", "垃圾")
            if kind == "垃圾":
                # 保留条目为"垃圾"供复核召回；指纹标记 junk，重跑不再送 AI
                con.execute("UPDATE items SET kind='垃圾', title=?, summary=? WHERE id=?",
                            (c.get("title", ""), c.get("summary", ""), r["id"]))
                fp_row = con.execute("SELECT fingerprint FROM items WHERE id=?",
                                     (r["id"],)).fetchone()
                if fp_row and fp_row[0]:
                    store.mark(con, fp_row[0], "junk")
                junk += 1
                continue
            con.execute(
                "UPDATE items SET kind=?, title=?, summary=?, tool_name=?, url=COALESCE(NULLIF(?,''),url) "
                "WHERE id=?",
                (kind, c.get("title", ""), c.get("summary", ""),
                 c.get("tool_name", ""), c.get("url", ""), r["id"]))
            store._attach_tags(con, r["id"], c.get("tags") or [])
            if kind == "工具" and c.get("tool_name"):
                cap_at = con.execute("SELECT captured_at FROM items WHERE id=?",
                                     (r["id"],)).fetchone()[0]
                store.upsert_tool(con, c["tool_name"], c.get("url", ""),
                                  c.get("summary", ""), r["id"], cap_at)
            done += 1
        con.commit()
        log(f"  已判定 {min(i + batch_size, len(rows))}/{len(rows)} | "
            f"入库 {done} | 垃圾 {junk} | tokens in/out {total_in}/{total_out}")

    # 粗略成本（deepseek-chat 非高峰约 ¥1.1/¥2.2 每百万 in/out，人民币近似）
    cost = total_in / 1e6 * 1.1 + total_out / 1e6 * 2.2
    log(f"AI 判定完成：入库 {done}，垃圾 {junk}，tokens {total_in}+{total_out}，"
        f"约 ¥{cost:.2f}")
    con.close()
    return {"classified": done, "junk": junk, "tokens_in": total_in,
            "tokens_out": total_out, "cost_rmb": round(cost, 2)}
