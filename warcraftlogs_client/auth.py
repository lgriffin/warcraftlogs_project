import base64
import requests
import time

class TokenManager:
    TOKEN_URL = "https://www.warcraftlogs.com/oauth/token"

    def __init__(self, client_id, client_secret):
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = None
        self.token_expiry = 0

    def _is_token_valid(self):
        return self.access_token and time.time() < self.token_expiry

    def _get_new_token(self):
        auth_string = f"{self.client_id}:{self.client_secret}"
        b64_auth = base64.b64encode(auth_string.encode()).decode()

        headers = {
            "Authorization": f"Basic {b64_auth}",
            "Content-Type": "application/x-www-form-urlencoded"
        }

        data = {
            "grant_type": "client_credentials"
        }

        response = requests.post(self.TOKEN_URL, headers=headers, data=data)
        response.raise_for_status()
        token_data = response.json()

        self.access_token = token_data["access_token"]
        self.token_expiry = time.time() + token_data.get("expires_in", 3600) - 60

    def get_token(self):
        if not self._is_token_valid():
            self._get_new_token()
        return self.access_token
