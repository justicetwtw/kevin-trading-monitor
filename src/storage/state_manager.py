"""JSON 狀態讀寫共用工具"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any
from loguru import logger

DATA_STORE_DIR = Path(__file__).parent.parent.parent / "data_store"
DATA_STORE_DIR.mkdir(exist_ok=True)

def read_json(filename: str, default: Any = None) -> Any:
    """讀取 JSON 檔案,不存在則返回 default"""
    filepath = DATA_STORE_DIR / filename
    if not filepath.exists():
        return default if default is not None else {}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error in {filename}: {e}")
        return default if default is not None else {}

def write_json(filename: str, data: Any, indent: int = 2) -> bool:
    """Atomically write a JSON file.

    The payload is fully materialised in a temp file, fsynced, then
    ``os.replace``d over the target, so a concurrent reader (or a run that is
    SIGKILLed mid-write) never observes a truncated/partial file that would be
    read back as the caller's empty default.
    """
    filepath = DATA_STORE_DIR / filename
    tmp_name = None
    try:
        fd, tmp_name = tempfile.mkstemp(
            dir=str(filepath.parent), prefix=f".{filepath.name}.", suffix=".tmp"
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, filepath)
        return True
    except Exception as e:
        logger.error(f"Failed to write {filename}: {e}")
        if tmp_name is not None:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
        return False

def update_json(filename: str, updates: dict) -> bool:
    """更新 JSON 檔案的部分欄位"""
    data = read_json(filename, default={})
    if not isinstance(data, dict):
        logger.error(f"Cannot update non-dict JSON: {filename}")
        return False
    data.update(updates)
    return write_json(filename, data)

def append_to_list_json(filename: str, item: Any, max_items: int = None) -> bool:
    """將 item 添加到 JSON 列表中"""
    data = read_json(filename, default=[])
    if not isinstance(data, list):
        logger.error(f"Cannot append to non-list JSON: {filename}")
        return False
    data.append(item)
    if max_items and len(data) > max_items:
        data = data[-max_items:]  # 保留最後 N 個
    return write_json(filename, data)
