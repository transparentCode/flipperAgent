from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ASGIResponse:
    status_code: int
    body: Any


async def request(
    app,
    method: str,
    path: str,
    body: Any | None = None,
) -> ASGIResponse:
    encoded_body = b"" if body is None else json.dumps(body).encode("utf-8")
    pending_messages = [
        {"type": "http.request", "body": encoded_body, "more_body": False}
    ]
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        if pending_messages:
            return pending_messages.pop(0)
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "headers": [
                (b"host", b"testserver"),
                (b"content-type", b"application/json"),
            ],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "root_path": "",
        },
        receive,
        send,
    )
    start = next(
        message for message in sent if message["type"] == "http.response.start"
    )
    body_message = next(
        message for message in sent if message["type"] == "http.response.body"
    )
    raw_body = body_message.get("body", b"")
    return ASGIResponse(
        status_code=int(start["status"]),
        body=json.loads(raw_body) if raw_body else None,
    )
