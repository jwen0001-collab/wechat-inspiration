# -*- coding: utf-8 -*-
"""汇集各来源为统一的"原子输入"。

原子输入 dict:
  source_type: image_old / image_v2 / text / album / doc
  source_ref:  原始定位（路径 / 消息键）
  captured_at: 'YYYY-MM' 或完整时间
  text:        文本内容（文本类）
  url:         提取到的链接（文本类，可选）
  load():      返回图片字节（图片类），文本类为 None
"""
import glob
import os
import re

from . import decode_dat, wxgf

_TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s{2}(.+?): (.*)$")
_URL = re.compile(r"https?://[^\s]+")
_SECRET = re.compile(r"\b(sk|xai|ghp|gsk|AKIA)[-_][A-Za-z0-9]{16,}\b")


def _redact(text: str) -> str:
    """抹掉疑似 API key / token，避免密钥进库或在界面泄露。"""
    return _SECRET.sub("[已隐去密钥]", text)
_PLACEHOLDER = re.compile(r"^\[(图片|语音|视频|表情|位置|通话|名片)\]$")
_IMG_EXT = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp")


def _img_loader(path):
    def load():
        return open(path, "rb").read()
    return load


def _dat_loader(path):
    def load():
        r = decode_dat.decode_verified(open(path, "rb").read())
        return r[0] if r else None
    return load


def _wxgf_loader(path):
    def load():
        return wxgf.to_png(open(path, "rb").read())
    return load


def collect_images_v2(images_dir: str, contact: str):
    """用户已导出的 V2 图片（jpg/png/wxgf），文件名形如 2025-08_<hash>.ext。"""
    folder = os.path.join(images_dir, contact)
    if not os.path.isdir(folder):
        return
    for p in sorted(glob.glob(os.path.join(folder, "**", "*"), recursive=True)):
        if not os.path.isfile(p):
            continue
        ext = os.path.splitext(p)[1].lower()
        m = re.match(r"(\d{4}-\d{2})", os.path.basename(p))
        cap = m.group(1) if m else ""
        if ext == ".wxgf":
            # 微信 HEVC，转码成 PNG 后走普通图片流程
            yield {"source_type": "image_v2", "source_ref": p, "captured_at": cap,
                   "text": None, "url": None, "load": _wxgf_loader(p)}
        elif ext in _IMG_EXT:
            yield {"source_type": "image_v2", "source_ref": p, "captured_at": cap,
                   "text": None, "url": None, "load": _img_loader(p)}


def collect_images_old(attach_dir: str):
    """老格式 .dat（2025-07 之前），本项目自行 XOR 解码。跳过缩略图 _t 和 V2。"""
    for p in sorted(glob.glob(os.path.join(attach_dir, "**", "*.dat"), recursive=True)):
        if p.endswith("_t.dat"):
            continue
        try:
            head = open(p, "rb").read(16)
        except Exception:
            continue
        if decode_dat.is_v2(head):
            continue  # V2 交给 collect_images_v2（已导出）
        m = re.search(r"(20\d\d-\d\d)", p)
        cap = m.group(1) if m else ""
        yield {"source_type": "image_old", "source_ref": p, "captured_at": cap,
               "text": None, "url": None, "load": _dat_loader(p)}


def collect_text(text_dir: str, contact: str):
    """解析联系人 txt，产出文本消息（跳过占位符与过短噪声）。"""
    path = os.path.join(text_dir, f"{contact}.txt")
    if not os.path.exists(path):
        return
    cur = None  # (ts, who, [lines])
    def flush(rec):
        if not rec:
            return None
        ts, who, lines = rec
        content = "\n".join(lines).strip()
        if not content or _PLACEHOLDER.match(content):
            return None
        content = _redact(content)
        url = _URL.search(content)
        # 噪声过滤：过短且无链接的丢弃
        if not url and len(content) < 6:
            return None
        if re.fullmatch(r"[\d\s\W]+", content) and not url:
            return None
        return {"source_type": "text", "source_ref": f"{contact}@{ts}",
                "captured_at": ts, "text": content,
                "url": url.group(0) if url else None, "load": None}

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            m = _TS.match(line)
            if m:
                out = flush(cur)
                if out:
                    yield out
                cur = (m.group(1), m.group(2), [m.group(3)])
            elif cur:
                cur[2].append(line)
    out = flush(cur)
    if out:
        yield out


def collect_album(album_dir: str):
    for p in sorted(glob.glob(os.path.join(album_dir, "**", "*"), recursive=True)):
        if os.path.isfile(p) and os.path.splitext(p)[1].lower() in _IMG_EXT:
            yield {"source_type": "album", "source_ref": p, "captured_at": "",
                   "text": None, "url": None, "load": _img_loader(p)}


def collect_all(cfg: dict):
    s = cfg["sources"]
    for contact in s["contacts"]:
        yield from collect_text(s["text_dir"], contact)
        yield from collect_images_v2(s["images_dir"], contact)
    # 老图只有文件传输助手那个 attach 目录
    if s.get("wechat_attach_dir"):
        yield from collect_images_old(s["wechat_attach_dir"])
    yield from collect_album(s["album_inbox"])
