"""`.eml` via the standard library — no external converter needed."""

from __future__ import annotations

from email import message_from_bytes
from email.message import Message
from pathlib import Path

from app.ingestion.parsers.base import ParsedDocument


def _decode_payload(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if not isinstance(payload, bytes):
        return ""
    return payload.decode(part.get_content_charset() or "utf-8", errors="replace")


def _extract_text(msg: Message) -> str:
    if msg.is_multipart():
        parts = [
            _decode_payload(part)
            for part in msg.walk()
            if part.get_content_type() == "text/plain" and not part.get_filename()
        ]
        return "\n\n".join(p for p in parts if p)
    return _decode_payload(msg)


class EmlParser:
    def parse(self, path: Path) -> ParsedDocument:
        msg = message_from_bytes(path.read_bytes())
        header_lines = [
            f"From: {msg.get('From', '')}",
            f"To: {msg.get('To', '')}",
            f"Subject: {msg.get('Subject', '')}",
            f"Date: {msg.get('Date', '')}",
        ]
        body = _extract_text(msg)
        text = "\n".join(header_lines) + "\n\n" + body
        return ParsedDocument(
            text=text,
            metadata={
                "parser": "eml",
                "from": msg.get("From", ""),
                "subject": msg.get("Subject", ""),
            },
        )
