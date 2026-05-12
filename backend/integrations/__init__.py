"""Platform-publish integrations.

Vinted and Kleinanzeigen are both fully implemented (auth, publish, update,
delete) against their reverse-engineered mobile APIs. ``is_configured(platform)``
reports whether a usable session is on disk for that platform.
"""

from __future__ import annotations

from . import kleinanzeigen, vinted


def is_configured(platform: str) -> bool:
    if platform == "vinted":
        return vinted.is_configured()
    if platform == "kleinanzeigen":
        return kleinanzeigen.is_configured()
    return False


__all__ = ["is_configured", "vinted", "kleinanzeigen"]
