"""
key_logger.py
main.py から呼び出すログユーティリティ。

使い方:
    import key_logger
    key_logger.log("メッセージ")   # DEBUG レベル
    key_logger.info("メッセージ")  # INFO レベル

有効・無効の切り替え:
    ENABLE_LOG = True   → ファイル + 標準出力 に出力
    ENABLE_LOG = False  → 何もしない（ゼロオーバーヘッド）
"""

import logging
import os
import sys

# ── ここを切り替えるだけでログのON/OFFが変わる ──────────────
ENABLE_LOG = False
# ────────────────────────────────────────────────────────────

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "key_remapper.log")

_logger = logging.getLogger("key_remapper")

if ENABLE_LOG:
    _logger.setLevel(logging.DEBUG)
    _fmt = logging.Formatter(
        "%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    _fh = logging.FileHandler(LOG_FILE, encoding="utf-8", mode="w")
    _fh.setFormatter(_fmt)
    _sh = logging.StreamHandler(sys.stdout)
    _sh.setFormatter(_fmt)
    _logger.addHandler(_fh)
    _logger.addHandler(_sh)
    _logger.info(f"ログ開始 → {LOG_FILE}")
else:
    _logger.addHandler(logging.NullHandler())


def debug(msg: str):
    if ENABLE_LOG:
        _logger.debug(msg)

def info(msg: str):
    if ENABLE_LOG:
        _logger.info(msg)

def warning(msg: str):
    if ENABLE_LOG:
        _logger.warning(msg)