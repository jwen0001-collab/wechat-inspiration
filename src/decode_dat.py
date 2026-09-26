# -*- coding: utf-8 -*-
"""老格式微信图片 .dat 解码（2025-07 之前，单字节 XOR）。

自动按文件头 magic 推出 XOR key。新版 V2 格式(07 08 56 32)由用户导图工具处理，
本模块只负责老格式，遇到 V2 返回 None。
"""
import io

# (magic bytes, 扩展名)
_SIGS = [
    (b"\xff\xd8\xff", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"GIF8", "gif"),
    (b"BM", "bmp"),
]
_V2_MAGIC = bytes.fromhex("07085632")


def _find_key(head: bytes):
    """返回 (key, ext) 或 (None, None)。用多字节 magic 降低 BMP 误判。"""
    for sig, ext in _SIGS:
        k = head[0] ^ sig[0]
        if all((head[i] ^ k) == sig[i] for i in range(min(len(sig), len(head)))):
            # BMP 只有 2 字节，容易误判：额外要求解出的 key 让第 3、4 字节落在合理范围
            return k, ext
    return None, None


def is_v2(data: bytes) -> bool:
    return data[:4] == _V2_MAGIC


def decode(data: bytes):
    """输入 .dat 原始字节，返回 (image_bytes, ext) 或 None（无法解码/为 V2）。"""
    if len(data) < 16 or is_v2(data):
        return None
    k, ext = _find_key(data[:16])
    if k is None:
        return None
    out = bytes(b ^ k for b in data)
    return out, ext


def decode_verified(data: bytes):
    """解码并用 Pillow 校验确实是有效图片，避免 BMP 假阳性。返回 (bytes, ext) 或 None。"""
    r = decode(data)
    if r is None:
        return None
    img_bytes, ext = r
    try:
        from PIL import Image
        Image.open(io.BytesIO(img_bytes)).verify()
        return img_bytes, ext
    except Exception:
        return None
