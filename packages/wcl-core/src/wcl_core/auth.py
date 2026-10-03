import base64
import time

import requests
from pydantic import SecretStr

from . import http
from .common.errors import AuthenticationError
from .config import as_secret


class TokenManager:
    TOKEN_URL = "https://www.warcraftlogs.com/oauth/token"  # noqa: S105 - a URL, not a secret

    def __init__(self, client_id: str, client_secret: str | SecretStr) -> None:
        self.client_id = client_id
        self.client_secret = as_secret(client_secret)
        self.access_token: SecretStr | None = None
        self.token_expiry = 0.0

    def _is_token_valid(self) -> bool:
        return bool(self.access_token) and time.time() < self.token_expiry

    def _get_new_token(self) -> None:
        auth_string = f"{self.client_id}:{self.client_secret.get_secret_value()}"
        b64_auth = base64.b64encode(auth_string.encode()).decode()

        headers = {"Authorization": f"Basic {b64_auth}", "Content-Type": "application/x-www-form-urlencoded"}

        data = {"grant_type": "client_credentials"}

        try:
            response = http.post(self.TOKEN_URL, headers=headers, data=data, timeout=30)
            response.raise_for_status()
            token_data = response.json()
        except requests.ConnectionError as e:
            raise AuthenticationError("Cannot reach WarcraftLogs — check your internet connection") from e
        except requests.Timeout as e:
            raise AuthenticationError("WarcraftLogs authentication timed out — try again later") from e
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else "error"
            raise AuthenticationError(f"Authentication failed (HTTP {status})", details=str(e)) from e
        except (ValueError, KeyError) as e:
            raise AuthenticationError("Received invalid response from WarcraftLogs", details=str(e)) from e

        self.access_token = SecretStr(token_data["access_token"])
        self.token_expiry = time.time() + token_data.get("expires_in", 3600) - 60

    def get_token(self) -> str:
        """Return the raw bearer token; callers must put it only in the Authorization header."""
        if not self._is_token_valid():
            self._get_new_token()
        if self.access_token is None:
            raise AuthenticationError("No access token available")
        return self.access_token.get_secret_value()
