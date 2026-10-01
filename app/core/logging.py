"""Minimal logging setup. Messages use key=value pairs so they are grep-able.

Never log passwords, password hashes, JWTs or webhook secrets.
"""

import logging


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
