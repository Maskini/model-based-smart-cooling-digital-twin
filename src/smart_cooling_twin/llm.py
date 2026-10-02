"""Optional diagnostic provider boundary. Provider output cannot request actuation."""

from typing import Protocol
from pydantic import Field
from .models import AgentObservation, Record


class Diagnostic(Record):
    summary: str = Field(max_length=2000)
    possible_causes: list[str] = Field(default_factory=list, max_length=8)


class DiagnosticProvider(Protocol):
    def diagnose(self, observation: dict) -> dict: ...


class LLMReasoner:
    def __init__(self, provider: DiagnosticProvider | None = None, enabled: bool = False):
        self.provider, self.enabled = provider, enabled

    def explain(self, observation: AgentObservation) -> Diagnostic | None:
        if not self.enabled or self.provider is None:
            return None
        try:
            return Diagnostic.model_validate(
                self.provider.diagnose(observation.model_dump(mode="json"))
            )
        except (ValueError, TypeError, RuntimeError):
            return None


class HTTPDiagnosticProvider:
    """Optional provider-neutral diagnostic endpoint returning Diagnostic JSON."""

    def __init__(self, url: str, api_key: str, model: str = ""):
        self.url, self.api_key, self.model = url, api_key, model

    def diagnose(self, observation: dict) -> dict:
        import httpx

        try:
            response = httpx.post(
                self.url,
                json={"model": self.model, "observation": observation},
                headers={"Authorization": "Bearer " + self.api_key},
                timeout=5,
                follow_redirects=False,
            )
            response.raise_for_status()
            if len(response.content) > 16384:
                raise ValueError("Diagnostic response too large")
            return response.json()
        except httpx.HTTPError as exc:
            raise RuntimeError("Diagnostic provider unavailable") from exc
