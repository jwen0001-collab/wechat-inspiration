# -*- coding: utf-8 -*-
"""命令行入口。
  python -m src.run ingest        # 本地采集+解码+OCR+去重+入库（不需联网）
  python -m src.run classify      # DeepSeek 判定未分类条目（需 secrets.json 的 key）
  python -m src.run stats         # 查看统计
  python -m src.run serve         # 启动网页界面
"""
import sys

from . import config, pipeline, store


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"
    cfg = config.load()
    if cmd == "ingest":
        pipeline.ingest(cfg, do_ocr=cfg.get("ocr", {}).get("enabled", True))
    elif cmd == "classify":
        pipeline.classify_pending(cfg)
    elif cmd == "stats":
        con = store.connect(config.db_path(cfg))
        print(store.stats(con))
    elif cmd == "serve":
        from . import server
        server.run(cfg)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
