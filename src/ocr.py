# -*- coding: utf-8 -*-
"""本地中文 OCR，RapidOCR 封装。首次调用惰性加载模型。"""
import io

_engine = None


def _get():
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _engine = RapidOCR()
    return _engine


MAX_SIDE = 1600  # OCR 前把长边缩到此值，大幅提速，文字仍清晰


def image_text(image_bytes: bytes) -> str:
    """返回图中识别到的文字（拼接）。大图先缩放提速。失败返回空串。"""
    try:
        import numpy as np
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        w, h = img.size
        if max(w, h) > MAX_SIDE:
            s = MAX_SIDE / max(w, h)
            img = img.resize((max(1, int(w * s)), max(1, int(h * s))), Image.LANCZOS)
        arr = np.array(img)
        result, _ = _get()(arr)
        if not result:
            return ""
        return "\n".join(line[1] for line in result if len(line) >= 2).strip()
    except Exception:
        return ""
