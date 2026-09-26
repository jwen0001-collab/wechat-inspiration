# -*- coding: utf-8 -*-
"""DeepSeek 判定：灵感/工具/垃圾 + 标题/摘要/标签/工具名/链接。批量调用省钱。"""
import json
import re

import requests

SYSTEM = """你是内容整理助手。用户把"灵感"和"工具类信息"发到微信文件传输助手，
现在给你一批条目（截图OCR文字或文字消息），请逐条判断并结构化。

分类规则：
- 工具：介绍/推荐某个软件、网站、App、AI工具、插件、模型、服务，含可复用的产品信息。
- 灵感：值得留存的想法、选题、金句、方法论、案例、设计参考、文案、知识点。
- 垃圾：付款/订单/物流通知、验证码、纯闲聊、个人待办杂事、系统消息、无信息量内容。

每条输出字段：
- kind: "工具" | "灵感" | "垃圾"
- title: 简短标题(<=20字)，垃圾可空
- summary: 一句话摘要，垃圾可空
- tags: 标签数组(2-4个，如"AI工具""设计""文案""效率""选题")，垃圾用[]
- tool_name: 若为工具，填规范产品名，否则""
- url: 条目中的官网/相关链接，没有填""

只返回 JSON 数组，每个元素对应输入同序号条目，不要多余文字。"""


def _client(cfg, key):
    ai = cfg["ai"]
    return {"url": ai["endpoint"], "model": ai["model"],
            "temp": ai.get("temperature", 0.2), "timeout": ai.get("timeout_sec", 60),
            "headers": {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}}


def _parse_json_array(s: str):
    s = s.strip()
    s = re.sub(r"^```(json)?|```$", "", s, flags=re.M).strip()
    i, j = s.find("["), s.rfind("]")
    if i >= 0 and j > i:
        s = s[i:j + 1]
    return json.loads(s)


def classify_batch(cfg, key, texts: list[str]) -> tuple[list[dict], dict]:
    """输入若干条目文本，返回 (结果列表, 用量)。失败抛异常由上层重试。"""
    c = _client(cfg, key)
    numbered = "\n\n".join(f"[{i}] {t[:1200]}" for i, t in enumerate(texts))
    body = {
        "model": c["model"],
        "temperature": c["temp"],
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"共 {len(texts)} 条：\n\n{numbered}"},
        ],
        "response_format": {"type": "json_object"} if False else None,
    }
    body = {k: v for k, v in body.items() if v is not None}
    r = requests.post(c["url"], headers=c["headers"], json=body, timeout=c["timeout"])
    r.raise_for_status()
    data = r.json()
    content = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})
    arr = _parse_json_array(content)
    # 对齐长度
    out = []
    for i in range(len(texts)):
        out.append(arr[i] if i < len(arr) and isinstance(arr[i], dict) else
                   {"kind": "垃圾", "title": "", "summary": "", "tags": [],
                    "tool_name": "", "url": ""})
    return out, usage
