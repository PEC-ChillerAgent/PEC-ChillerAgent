"""Small, explicit trace envelope; never serialize credentials or private reasoning."""

from copy import deepcopy

PRIVATE = {"reasoning_content", "reasoning", "thinking", "analysis"}
SECRET = {"api_key", "apikey", "authorization", "password", "access_token", "refresh_token", "secret"}


def clean_trace(value, secret: str = ""):
    if isinstance(value, dict):
        return {key: ("[REDACTED]" if key.lower() in SECRET else clean_trace(item, secret))
                for key, item in value.items() if key.lower() not in PRIVATE}
    if isinstance(value, list):
        return [clean_trace(item, secret) for item in value]
    if isinstance(value, str) and secret:
        return value.replace(secret, "[REDACTED]")
    return deepcopy(value)


class CompletionMessage(dict):
    """Wire-compatible message with audit data outside the provider message keys."""

    def __init__(self, message: dict, audit: dict):
        super().__init__(message)
        self.audit = audit
