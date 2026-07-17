import logging
import sys
import os
from pathlib import Path
from colorama import Fore, Style
from dotenv import load_dotenv

load_dotenv()

class ColorFormatter(logging.Formatter):
    LEVEL_COLORS = {
        logging.DEBUG: Fore.BLUE,
        logging.INFO: Fore.GREEN,
        logging.WARNING: Fore.YELLOW,
        logging.ERROR: Fore.RED,
        logging.CRITICAL: Fore.MAGENTA,
    }

    def format(self, record):
        color = self.LEVEL_COLORS.get(record.levelno, "")
        loc = f"{Fore.CYAN}{record.filename}:{record.lineno}{Style.RESET_ALL}"
        return f"[{color}{record.levelname}{Style.RESET_ALL}] - [{loc}] - {record.getMessage()}"


class SystemLogFilter(logging.Filter):
    """Allow only explicit system-category records into system.log."""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.name == "src.system"

def my_logger_setup():
    logger = logging.getLogger("src")
    logger.setLevel(logging.DEBUG)

    # Console handler with colors
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(ColorFormatter())
    logger.addHandler(console_handler)

    # File handler (plain, no colors)
    cache_dir = os.getenv("CACHE_DIR")
    if cache_dir:
        log_dir = Path(cache_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_dir / "system.log", encoding="utf-8")
        file_handler.addFilter(SystemLogFilter())
        file_handler.setFormatter(logging.Formatter("[%(levelname)s] - [%(filename)s:%(lineno)d] - %(message)s"))
        logger.addHandler(file_handler)

    logger.propagate = False

def get_my_logger(category: str = "system"):
    return logging.getLogger(f"src.{category}")
