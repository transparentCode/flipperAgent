from __future__ import annotations

import html
from typing import Any

import aiohttp

from apps.alert_app.contracts import AlertIncidentRecord


class TelegramAlertTransport:
    async def send(
        self,
        *,
        incident: AlertIncidentRecord,
        route_name: str,
        route_config: dict[str, Any],
    ) -> None:
        bot_token = str(route_config.get("bot_token", "")).strip()
        chat_id = str(route_config.get("chat_id", "")).strip()
        parse_mode = self._normalize_parse_mode(route_config.get("parse_mode"))
        thread_id = route_config.get("thread_id")
        if not bot_token or not chat_id:
            raise ValueError(
                f"Telegram route {route_name} requires bot_token and chat_id",
            )

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        text = self._format_message(incident, parse_mode=parse_mode)
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        if thread_id not in (None, ""):
            payload["message_thread_id"] = thread_id

        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload) as response:
                if response.status >= 400:
                    body = await response.text()
                    raise RuntimeError(
                        f"Telegram transport failed for {route_name}: "
                        f"status={response.status} body={body[:200]}"
                    )

    @staticmethod
    def _format_message(
        incident: AlertIncidentRecord,
        *,
        parse_mode: str = "HTML",
    ) -> str:
        if parse_mode.upper() == "HTML":
            return TelegramAlertTransport._format_html_message(incident)
        return TelegramAlertTransport._format_plain_text_message(incident)

    @staticmethod
    def _format_html_message(incident: AlertIncidentRecord) -> str:
        lines = [
            (
                f"<b>{html.escape(incident.severity.value.upper())}</b> "
                f"<code>{html.escape(incident.source_app.value)}</code>"
            ),
            html.escape(incident.title),
            html.escape(incident.summary),
        ]
        if incident.asset:
            lines.append(
                f"<code>asset</code> {html.escape(incident.asset)}",
            )
        if incident.timeframe:
            lines.append(
                f"<code>timeframe</code> {html.escape(incident.timeframe)}",
            )
        return "\n".join(lines)

    @staticmethod
    def _format_plain_text_message(incident: AlertIncidentRecord) -> str:
        lines = [
            f"{incident.severity.value.upper()} {incident.source_app.value}",
            incident.title,
            incident.summary,
        ]
        if incident.asset:
            lines.append(f"asset {incident.asset}")
        if incident.timeframe:
            lines.append(f"timeframe {incident.timeframe}")
        return "\n".join(lines)

    @staticmethod
    def _normalize_parse_mode(value: object) -> str:
        normalized = str(value or "").strip().upper()
        if normalized == "HTML":
            return "HTML"
        if normalized in {"", "MARKDOWN", "MARKDOWNV2"}:
            return "HTML"
        return str(value or "HTML").strip() or "HTML"
