"""Kleinanzeigen publish — stubbed for Phase 6a.

The mobile listing-create flow needs a mitmproxy capture session against the
KA Android app's "Anzeige aufgeben" path before it can be implemented (see
RESEARCH-ka.md in the vinted-lister repo). Until that lands, /publish for
Kleinanzeigen falls back to returning the new-listing page URL with
posted=false.
"""

from __future__ import annotations


class KleinanzeigenNotConfigured(RuntimeError):
    pass


def is_configured() -> bool:
    return False


async def publish(image_path, payload):
    raise KleinanzeigenNotConfigured(
        "Kleinanzeigen direct publishing not implemented (Phase 6c)"
    )
