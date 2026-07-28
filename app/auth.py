import time

import msal

from app.config import settings

GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]

_cached_token = None
_cached_token_exp = 0


def get_access_token() -> str:
    global _cached_token, _cached_token_exp

    now = int(time.time())
    if _cached_token and _cached_token_exp > now + 300:
        return _cached_token

    client = msal.ConfidentialClientApplication(
        client_id=settings.client_id,
        client_credential=settings.client_secret,
        authority=f"https://login.microsoftonline.com/{settings.tenant_id}",
    )

    result = client.acquire_token_for_client(scopes=GRAPH_SCOPE)
    if "access_token" not in result:
        raise RuntimeError(f"Failed to acquire token: {result.get('error_description', result)}")

    _cached_token = result["access_token"]
    _cached_token_exp = now + int(result.get("expires_in", 3600))
    return _cached_token
