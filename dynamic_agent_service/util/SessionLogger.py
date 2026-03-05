import json
import os
from pathlib import Path
from dotenv import load_dotenv
import aiofiles

load_dotenv()


class SessionLogger:

    def __init__(self, session_id: str):
        """
        use .env to find cache folder, everything says in CACHE_FOLDER_PATH/session_log/session_id/file.log
        """
        self.session_id = session_id
        cache_folder = os.getenv("CACHE_FOLDER_PATH", "./cache")
        self.log_dir = Path(cache_folder) / "session_log" / session_id
        self.log_dir.mkdir(parents=True, exist_ok=True)

    async def log(self, file: str, line: dict):
        """
        append the json line as a single line to the session log file
        """
        log_file = self.log_dir / f"{file}.log"
        async with aiofiles.open(log_file, mode="a", encoding="utf-8") as f:
            await f.write(json.dumps(line, ensure_ascii=False) + "\n")