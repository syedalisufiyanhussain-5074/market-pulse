import logging
import json
import time
from contextlib import contextmanager
from typing import Any


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "layer": getattr(record, "layer", "unknown"),
            "message": record.getMessage(),
            "file_hash": getattr(record, "file_hash", None),
            "duration_ms": getattr(record, "duration_ms", None),
            "row_count": getattr(record, "row_count", None),
        }
        log_data = {k: v for k, v in log_data.items() if v is not None}
        return json.dumps(log_data)


def get_logger(layer: str) -> logging.Logger:
    logger = logging.getLogger(f"market_pulse.{layer}")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


@contextmanager
def log_stage(logger: logging.Logger, stage: str, **extra: Any):
    start = time.perf_counter()
    logger.info(f"Starting {stage}", extra=extra)
    try:
        yield
    except Exception as e:
        duration = (time.perf_counter() - start) * 1000
        logger.error(
            f"Failed {stage}: {e}",
            extra={**extra, "duration_ms": round(duration, 1)},
        )
        raise
    else:
        duration = (time.perf_counter() - start) * 1000
        logger.info(
            f"Completed {stage}",
            extra={**extra, "duration_ms": round(duration, 1)},
        )
