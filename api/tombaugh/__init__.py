"""Tombaugh API package. Interface: docs/CONTRACT_FIELDS.md (v1.0)."""

from astropy.utils import iers

iers.conf.auto_download = False  # never reach out for Earth-orientation tables at import or run time

__version__ = "0.3.0"  # 0.3.0: older-survey (legacy) planes in every built field; visit dates in warnings
CONTRACT_VERSION = "1.0"
