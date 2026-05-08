"""Platform-publish integrations.

Phase 6a: Vinted only. Kleinanzeigen is a stub that always reports
"not configured" until Phase 6c lands the mobile listing flow.
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
