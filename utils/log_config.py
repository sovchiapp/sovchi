import logging
from datetime import datetime, UTC
from json import dumps
from pathlib import Path
from sys import stderr
from traceback import format_exception

from loguru import logger

LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)


def _patch_record(record):
    record["extra"]["utc_time"] = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    record["extra"].setdefault("name", record["name"])
    record["extra"].setdefault("function", record["function"])
    record["extra"].setdefault("line", record["line"])


def json_formatter(record):
    log_record = {
        "timestamp": record["extra"].get("utc_time"),
        "level": record["level"].name,
        "message": record["message"],
        "module": record["extra"].get("name"),
        "function": record["extra"].get("function"),
        "line": record["extra"].get("line"),
    }
    if record["exception"]:
        exc = record["exception"]
        log_record["exception"] = {
            "type": exc.type.__name__ if exc.type else None,
            "value": str(exc.value) if exc.value else None,
            "traceback": "".join(
                format_exception(exc.type, exc.value, exc.traceback)) if exc.traceback else None,
        }
    record["extra"]["json_log"] = dumps(log_record, ensure_ascii=False)
    return "{extra[json_log]}\n"


class InterceptHandler(logging.Handler):
    def emit(self, record):
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        logger.bind(
            name=record.name,
            function=record.funcName,
            line=record.lineno,
        ).opt(exception=record.exc_info).log(level, record.getMessage())


def _intercept_stdlib(root_level="INFO"):
    logging.root.handlers = [InterceptHandler()]
    logging.root.setLevel(root_level)

    for name in list(logging.root.manager.loggerDict.keys()):
        std_logger = logging.getLogger(name)
        std_logger.handlers = []
        std_logger.propagate = True

    for name in ("django.db.backends", "daphne.access", "urllib3", "asyncio"):
        logging.getLogger(name).setLevel("WARNING")


def setup_logger():
    from utils.core import core

    log_level = "DEBUG" if core.DEBUG else "INFO"

    logger.remove()
    logger.configure(patcher=_patch_record)

    logger.add(stderr, level=log_level, format=json_formatter, colorize=False, enqueue=True)

    file_kwargs = {}
    if core.DEBUG:
        file_kwargs = {"rotation": "00:00", "retention": "14 days", "compression": "zip"}

    logger.add(
        LOGS_DIR / "app.log",
        level=log_level,
        format=json_formatter,
        encoding="utf-8",
        enqueue=True,
        **file_kwargs,
    )

    _intercept_stdlib(log_level)
    return logger
