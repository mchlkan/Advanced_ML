"""OAuth-related primitives shared by Vinted + KA integrations.

Both platforms decode JWT access-token payloads to read user_id / expiry.
This module owns that one helper so a fix (e.g. base64 padding bug) lands
in one place instead of being duplicated.
"""

from __future__ import annotations

import base64
import json


def decode_jwt_payload(token: str) -> dict:
    """Return the JWT's middle (payload) segment as a dict, or {} if the
    token doesn't look like a JWT. Pads with '=' to satisfy base64."""
    parts = token.split(".")
    if len(parts) != 3:
        return {}
    return json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (4 - len(parts[1]) % 4)))
