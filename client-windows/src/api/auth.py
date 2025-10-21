import requests
from typing import Optional


class AuthClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')

    def login(self, username: str, password: str) -> Optional[str]:
        url = f"{self.base_url}/auth/login"
        # Send form-encoded data instead of JSON to match Android server
        resp = requests.post(
            url,
            data={"username": username, "password": password},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("token")
        return None