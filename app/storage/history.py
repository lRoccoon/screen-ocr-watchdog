"""被推送消息的全量历史，追加写 ndjson。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class HistoryStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, fingerprint: str, text: str, ts: datetime | None = None) -> None:
        ts = ts or datetime.now(timezone.utc)
        record = {"ts": ts.isoformat(), "fingerprint": fingerprint, "text": text}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def tail(self, n: int = 100) -> list[dict]:
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8") as f:
            lines = f.readlines()
        result = []
        for line in lines[-n:]:
            line = line.strip()
            if line:
                result.append(json.loads(line))
        return result
