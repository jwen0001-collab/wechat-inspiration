# -*- coding: utf-8 -*-
"""配置与密钥加载。config.json 优先，缺失回退 config.example.json。"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resolve(p: str) -> str:
    """相对路径按项目根解析，绝对路径原样。"""
    if not p:
        return p
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(ROOT, p))


def load() -> dict:
    path = os.path.join(ROOT, "config.json")
    if not os.path.exists(path):
        path = os.path.join(ROOT, "config.example.json")
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    cfg["_root"] = ROOT
    # 归一化项目内路径
    cfg["sources"]["album_inbox"] = _resolve(cfg["sources"].get("album_inbox", "inbox/album"))
    return cfg


def deepseek_key(cfg: dict) -> str | None:
    """读取 DeepSeek key，顺序：环境变量 → 本项目 secrets.json → 配置的 secrets_file。
    不打印、不写日志。"""
    ai = cfg.get("ai", {})
    env_name = ai.get("api_key_env", "DEEPSEEK_API_KEY")
    if os.environ.get(env_name):
        return os.environ[env_name]
    candidates = [os.path.join(ROOT, "secrets.json")]
    if ai.get("secrets_file"):
        candidates.append(ai["secrets_file"])
    for sf in candidates:
        if sf and os.path.exists(sf):
            try:
                with open(sf, "r", encoding="utf-8") as f:
                    k = json.load(f).get(env_name)
                if k and str(k).startswith("sk-"):
                    return k
            except Exception:
                continue
    return None


def db_path(cfg: dict) -> str:
    return _resolve("data/inspiration.db")


def cache_dir(cfg: dict) -> str:
    d = _resolve("cache/images")
    os.makedirs(d, exist_ok=True)
    return d
