import logging
import json
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from app.config import APP_VERSION


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


# ---------------------------------------------------------------------------
# Audit logger — structured, privacy-safe event log
# ---------------------------------------------------------------------------

_audit_logger: logging.Logger | None = None


def _get_audit_logger() -> logging.Logger:
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = logging.getLogger("market_pulse.audit")
        _audit_logger.propagate = False
        if not _audit_logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(message)s"))
            _audit_logger.addHandler(handler)
            _audit_logger.setLevel(logging.INFO)
    return _audit_logger


def audit_log(
    event_type: str,
    component: str,
    session_id: str | None = None,
    report_type: str | None = None,
    generated_filename: str | None = None,
    notes: str | None = None,
    error_code: str | None = None,
    duration_ms: float | None = None,
) -> None:
    """Write a structured audit entry to stdout (captured by Render)."""
    now = datetime.now(timezone.utc)
    entry = {
        "log_type": "AUDIT",
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z",
        "app_version": APP_VERSION,
        "event_type": event_type,
        "session_id": session_id,
        "component": component,
        "report_type": report_type,
        "generated_filename": generated_filename,
        "notes": notes,
        "error_code": error_code,
        "duration_ms": duration_ms,
    }
    entry = {k: v for k, v in entry.items() if v is not None}
    _get_audit_logger().info(json.dumps(entry))
