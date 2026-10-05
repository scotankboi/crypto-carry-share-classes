"""One HTTP client for every source: retries with exponential backoff and a polite sleep."""
import json
import time

import requests

RETRY_STATUS = {418, 429, 500, 502, 503, 504}


class HttpClient:
    def __init__(self, sleep_sec: float = 0.1, max_retries: int = 5, timeout: int = 30):
        self.sleep_sec, self.max_retries, self.timeout = sleep_sec, max_retries, timeout
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "crypto-carry-share-classes/1.0 (public-data research)"

    def _request(self, method: str, url: str, **kw) -> requests.Response:
        last = None
        for attempt in range(self.max_retries):
            try:
                resp = self.session.request(method, url, timeout=self.timeout, **kw)
            except requests.RequestException as exc:
                last = exc
            else:
                if resp.status_code not in RETRY_STATUS:
                    resp.raise_for_status()
                    time.sleep(self.sleep_sec)
                    return resp
                last = requests.HTTPError(f"HTTP {resp.status_code} for {resp.url}")
                ra = resp.headers.get("Retry-After")
                if ra and ra.isdigit():
                    time.sleep(int(ra))
                    continue
            time.sleep(min(2 ** attempt, 30))
        raise RuntimeError(f"{method} {url} failed after {self.max_retries} attempts: {last}")

    def get(self, url: str, params: dict | None = None) -> requests.Response:
        return self._request("GET", url, params=params)

    def get_json(self, url: str, params: dict | None = None):
        return self._request("GET", url, params=params).json()

    def get_text(self, url: str, params: dict | None = None, headers: dict | None = None) -> str:
        return self._request("GET", url, params=params, headers=headers).text

    def post_json(self, url: str, body: dict):
        return self._request("POST", url, data=json.dumps(body), headers={"Content-Type": "application/json"}).json()
