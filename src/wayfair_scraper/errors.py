"""Errors raised by the scraper."""

from __future__ import annotations


class WayfairError(Exception):
    """Base class for scraper errors."""


class ParseError(WayfairError):
    """The page came back without the data Wayfair normally puts in it."""


class NotFoundError(WayfairError, LookupError):
    """Wayfair has no such page or product (HTTP 404, or a SKU search with no match)."""
