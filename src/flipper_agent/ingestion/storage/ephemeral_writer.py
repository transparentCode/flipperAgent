import json
import gzip
import os
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any

class EphemeralJSONLWriter:
    def __init__(self, base_dir: str = "data/raw_sockets"):
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)

    def _get_filepath(self, stream: str) -> str:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return os.path.join(self.base_dir, f"{date_str}_{stream}.jsonl.gz")

    def _sync_append(self, filepath: str, data: str) -> None:
        with gzip.open(filepath, "at", encoding="utf-8") as f:
            f.write(data)

    async def write(self, stream: str, data: Dict[str, Any]) -> None:
        filepath = self._get_filepath(stream)
        line = json.dumps(data) + "\n"
        await asyncio.to_thread(self._sync_append, filepath, line)
