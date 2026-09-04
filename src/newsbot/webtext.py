from __future__ import annotations

from typing import Any


def decoded_response_text(response: Any) -> str:
    encoding = (getattr(response, "encoding", "") or "").lower()
    if not encoding or encoding in {"iso-8859-1", "latin-1"}:
        apparent_encoding = getattr(response, "apparent_encoding", "") or ""
        if apparent_encoding:
            response.encoding = apparent_encoding
    return response.text
