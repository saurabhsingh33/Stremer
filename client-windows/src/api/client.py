import requests
from typing import List, Dict, Optional


class APIClient:
    def __init__(self, base_url: str, token: Optional[str] = None):
        self.base_url = base_url.rstrip('/')
        self.token = token

    def set_token(self, token: str):
        self.token = token

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def list_files(self, path: str = "/") -> List[Dict]:
        url = f"{self.base_url}/files"
        resp = requests.get(url, params={"path": path}, headers=self._headers(), timeout=15)
        resp.raise_for_status()
        return resp.json().get("items", [])

    def stream_url(self, path: str) -> str:
        return f"{self.base_url}/stream?path={requests.utils.quote(path, safe='')}&token={self.token or ''}"

    def thumb_url(self, path: str, w: int = 256, h: int = 256) -> str:
        return f"{self.base_url}/thumb?path={requests.utils.quote(path, safe='')}&w={w}&h={h}"

    def meta_url(self, path: str) -> str:
        return f"{self.base_url}/meta?path={requests.utils.quote(path, safe='')}"

    def get_meta(self, path: str) -> Dict:
        url = f"{self.base_url}/meta"
        resp = requests.get(url, params={"path": path}, headers=self._headers(), timeout=15)
        resp.raise_for_status()
        return resp.json()

    def delete_file(self, path: str) -> bool:
        url = f"{self.base_url}/file"
        resp = requests.delete(url, params={"path": path}, headers=self._headers(), timeout=15)
        return resp.status_code == 200

    def copy_file(self, src: str, dst: str) -> bool:
        url = f"{self.base_url}/copy"
        resp = requests.post(url, json={"src": src, "dst": dst}, headers=self._headers(), timeout=30)
        return resp.status_code == 200

    def rename_file(self, path: str, new_name: str) -> bool:
        url = f"{self.base_url}/rename"
        resp = requests.post(url, json={"path": path, "newName": new_name}, headers=self._headers(), timeout=15)
        return resp.status_code == 200
