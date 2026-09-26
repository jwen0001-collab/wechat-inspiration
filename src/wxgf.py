# -*- coding: utf-8 -*-
"""微信 .wxgf 图片转码：wxgf 是私有头 + HEVC(H.265) Annex-B 裸流。
跳过私有头，从 VPS 起始码切出裸流，用 ffmpeg 解成 PNG（取第一帧）。"""
import subprocess

_ff = None


def _ffmpeg():
    global _ff
    if _ff is None:
        import imageio_ffmpeg
        _ff = imageio_ffmpeg.get_ffmpeg_exe()
    return _ff


def _find_vps(d: bytes) -> int:
    """找到 NAL type==32(VPS) 的 Annex-B 起始码偏移。"""
    i = 0
    while True:
        j = d.find(b"\x00\x00\x00\x01", i)
        if j < 0 or j + 4 >= len(d):
            return -1
        if ((d[j + 4] >> 1) & 0x3F) == 32:
            return j
        i = j + 4


def to_png(data: bytes):
    """wxgf 字节 → PNG 字节；失败返回 None。"""
    if data[:4] != b"wxgf":
        return None
    s = _find_vps(data)
    if s < 0:
        return None
    try:
        p = subprocess.run(
            [_ffmpeg(), "-y", "-loglevel", "error", "-f", "hevc", "-i", "pipe:0",
             "-frames:v", "1", "-f", "image2", "-vcodec", "png", "pipe:1"],
            input=data[s:], capture_output=True, timeout=60)
        return p.stdout if len(p.stdout) > 100 else None
    except Exception:
        return None
