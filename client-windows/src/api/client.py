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

    def list_files(self, path: str = "/", offset: int | None = None, limit: int | None = None) -> List[Dict]:
        url = f"{self.base_url}/files"
        params: Dict[str, object] = {"path": path}
        if offset is not None:
            params["offset"] = max(0, int(offset))
        if limit is not None:
            params["limit"] = max(1, int(limit))
        resp = requests.get(url, params=params, headers=self._headers(), timeout=30)
        resp.raise_for_status()
        return resp.json().get("items", [])

    def list_files_page(self, path: str = "/", offset: int = 0, limit: int = 100) -> tuple[list[Dict], int, int, int, Optional[str]]:
        """Return (items, total, offset, limit, error) for paginated folder listing."""
        url = f"{self.base_url}/files"
        params = {"path": path, "offset": max(0, int(offset)), "limit": max(1, int(limit))}
        resp = requests.get(url, params=params, headers=self._headers(), timeout=30)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("items", [])
        total = int(data.get("total", len(items)))
        error = data.get("error")
        return items, total, int(data.get("offset", offset)), int(data.get("limit", limit)), error

    def stream_files(self, path: str = "/", on_item_callback=None, max_items: int = None, offset: int = 0):
        """Stream files one by one from /files endpoint (NDJSON format).
        Calls on_item_callback(item) for each item as it arrives.
        Returns (error_message, has_more) tuple."""
        url = f"{self.base_url}/files"
        params = {"path": path}
        if max_items:
            params["limit"] = max_items
        if offset > 0:
            params["offset"] = offset
        error = None
        has_more = False
        items_count = 0

        try:
            # Use stream=True to read the response line-by-line without loading it all into memory
            resp = requests.get(url, params=params, headers=self._headers(), timeout=300, stream=True)
            resp.raise_for_status()

            # Read NDJSON (newline-delimited JSON) and emit items immediately
            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                try:
                    import json
                    item = json.loads(line)
                    if "error" in item:
                        error = item["error"]
                    elif on_item_callback:
                        # Call callback immediately as item arrives from server
                        # Callback can return False to stop streaming
                        items_count += 1
                        result = on_item_callback(item)
                        if result is False:
                            # Callback signaled to stop
                            has_more = True
                            break

                        # Check if we've reached the limit
                        if max_items and items_count >= max_items:
                            has_more = True
                            break
                except json.JSONDecodeError:
                    pass
        except Exception as e:
            error = str(e)

        return error, has_more

    def search(self, path: str = "/", q: str | None = None, type_: str | None = None, size_min: int | None = None, size_max: int | None = None, modified_after: int | None = None, modified_before: int | None = None, limit: int = 200) -> List[Dict]:
        url = f"{self.base_url}/search"
        params = {"path": path, "limit": limit}
        if q:
            params["q"] = q
        if type_:
            params["type"] = type_
        if size_min is not None:
            params["sizeMin"] = size_min
        if size_max is not None:
            params["sizeMax"] = size_max
        if modified_after is not None:
            params["modifiedAfter"] = modified_after
        if modified_before is not None:
            params["modifiedBefore"] = modified_before
        resp = requests.get(url, params=params, headers=self._headers(), timeout=30)
        resp.raise_for_status()
        return resp.json().get("items", [])

    def stream_url(self, path: str) -> str:
        # Only include token parameter if we have a valid token
        if self.token:
            return f"{self.base_url}/stream?path={requests.utils.quote(path, safe='')}&token={self.token}"
        else:
            return f"{self.base_url}/stream?path={requests.utils.quote(path, safe='')}"

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

    def create_folder(self, parent_path: str, name: str) -> bool:
        url = f"{self.base_url}/mkdir"
        resp = requests.post(url, json={"path": parent_path, "name": name}, headers=self._headers(), timeout=15)
        return resp.status_code == 200

    def create_file(self, parent_path: str, name: str, mime: Optional[str] = None) -> bool:
        url = f"{self.base_url}/createFile"
        payload = {"path": parent_path, "name": name}
        if mime:
            payload["mime"] = mime
        resp = requests.post(url, json=payload, headers=self._headers(), timeout=15)
        return resp.status_code == 200
