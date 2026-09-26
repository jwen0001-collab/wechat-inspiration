# -*- coding: utf-8 -*-
"""去重：文件 SHA-256 精确去重 + 感知哈希(pHash)近似图去重。"""
import hashlib
import io


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def phash_of(image_bytes: bytes):
    try:
        import imagehash
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes))
        return str(imagehash.phash(img))
    except Exception:
        return None


def hamming(a: str, b: str) -> int:
    if not a or not b or len(a) != len(b):
        return 999
    ai, bi = int(a, 16), int(b, 16)
    return bin(ai ^ bi).count("1")


class NearDup:
    """在一次运行内累积已见 pHash，判断新图是否与已有图近似重复。"""

    def __init__(self, threshold: int = 4):
        self.threshold = threshold
        self.seen = []  # list[str]

    def is_dup(self, phash: str) -> bool:
        if not phash:
            return False
        for p in self.seen:
            if hamming(phash, p) <= self.threshold:
                return True
        return False

    def add(self, phash: str):
        if phash:
            self.seen.append(phash)
