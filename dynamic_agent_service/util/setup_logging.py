import logging
import sys
from colorama import Fore, Style

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

def my_logger_setup():
    logger = logging.getLogger("src")
    logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(ColorFormatter())
    logger.addHandler(handler)
    logger.propagate = False

def get_my_logger():
    return logging.getLogger("src")
