"""Package logger without import-time duplicate handlers."""

import logging

logger = logging.getLogger("tdxhub")
logger.addHandler(logging.NullHandler())
