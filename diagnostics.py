"""Local bounded diagnostics, without message contents or full process paths."""
import logging
from logging.handlers import RotatingFileHandler


def configure_logging(directory):
    logger = logging.getLogger("ValorantToxicTamer")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = RotatingFileHandler(directory / "diagnostics.log", maxBytes=262144,
                                  backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(handler)
    logger.info("application starting")
    return handler
