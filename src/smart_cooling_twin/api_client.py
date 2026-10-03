"""Dashboard HTTP boundary; credentials stay in the Streamlit server process."""

import httpx


class APIError(RuntimeError):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


class TwinAPIClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def request(self, method: str, path: str, *, token: str = "", data: dict | None = None) -> dict:
        headers = {"Authorization": "Bearer " + token} if token else {}
        try:
            response = httpx.request(
                method,
                self.base_url + path,
                headers=headers,
                json=data,
                timeout=5,
                follow_redirects=False,
            )
            if response.status_code >= 400:
                try:
                    detail = response.json().get("detail", "Request failed")
                except ValueError:
                    detail = "Request failed"
                raise APIError(str(detail), response.status_code)
            return response.json() if response.content else {}
        except httpx.HTTPError as exc:
            raise APIError(
                "Backend is unavailable. It will reconnect automatically when the service returns."
            ) from exc
