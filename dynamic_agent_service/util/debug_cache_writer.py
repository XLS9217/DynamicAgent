import os
import json
from pathlib import Path

def get_cache_folder():
    cache_dir = os.getenv("CHCHE_DIR")
    if not cache_dir:
        raise ValueError("CHCHE_DIR not found in environment variables")

    cache_path = Path(cache_dir)
    cache_path.mkdir(parents=True, exist_ok=True)
    return cache_path

def debug_cache_json(file_name, debug_json):
    """
    Write debug JSON to cache folder with file_name as the filename.
    """
    cache_folder = get_cache_folder()
    file_path = cache_folder / f"{file_name}.json"

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(debug_json, f, ensure_ascii=False, indent=2)

def debug_cache_md(file_name, text):
    """Write debug text to cache folder as a .md file."""
    cache_folder = get_cache_folder()
    file_path = cache_folder / f"{file_name}.md"

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(text)