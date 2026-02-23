import logging
import sys

# Default Logger Name
LOGGER_NAME = "omniclaw"


def configure_logging(level: int | str = logging.INFO, json_format: bool = False) -> logging.Logger:
    """
    Configure the OmniClaw logger.

    Args:
        level: Logging level (e.g., logging.INFO, "DEBUG")
        json_format: Whether to emit JSON logs (good for Datadog/Splunk)

    Returns:
        The configured logger instance.
    """
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)

    # Remove existing handlers to avoid duplicates if re-configured
    if logger.handlers:
        logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    if json_format:
        # Simple JSON formatter mock (users can replace with python-json-logger if needed)
        formatter = logging.Formatter(
            '{"timestamp": "%(asctime)s", "level": "%(levelname)s", "name": "%(name)s", "message": "%(message)s"}'
        )
    else:
        # Human readable format
        formatter = logging.Formatter(
            "[%(asctime)s] %(levelname)s [%(name)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )

    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # Don't propagate to root logger to avoid double printing if user has their own setup
    logger.propagate = False

    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Get a child logger of omniclaw."""
    if name:
        return logging.getLogger(f"{LOGGER_NAME}.{name}")
    return logging.getLogger(LOGGER_NAME)
