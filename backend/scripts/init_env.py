#!/usr/bin/env python3
"""`make setup`: create .env from .env.example on first run and give this install its own
secrets. The PII vault key and the HMAC secret are deliberately absent from the template — a
shared, committed key would let anyone with the repository decrypt another install's vault —
so without this step every upload on a fresh machine failed at the PII stage. Existing values
are never overwritten."""

from __future__ import annotations

import re
import secrets
import shutil
from pathlib import Path

from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[2]
ENV, TEMPLATE = ROOT / ".env", ROOT / ".env.example"
GENERATED = {
    "PII_VAULT_KEY": lambda: Fernet.generate_key().decode(),
    "PII_HMAC_SECRET": lambda: secrets.token_hex(32),
}
PLACEHOLDER = "dev-only-change-me"


def main() -> None:
    fresh = not ENV.exists()
    if fresh:
        shutil.copyfile(TEMPLATE, ENV)
        print("Created .env from .env.example")
    text = ENV.read_text(encoding="utf-8")
    for name, make in GENERATED.items():
        match = re.search(rf"^{name}=(.*)$", text, re.M)
        if match is None:
            text = text.rstrip("\n") + f"\n{name}={make()}\n"
        # An empty value is filled on any run (uploads cannot work without it). The template's
        # placeholder is replaced only in a .env created just now: on an existing install,
        # changing the HMAC secret would give new documents different tokens for the same names.
        elif match.group(1).strip() == "" or (fresh and match.group(1).strip() == PLACEHOLDER):
            text = text[: match.start()] + f"{name}={make()}" + text[match.end() :]
        else:
            continue
        print(f"Generated {name} for this install")
    ENV.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
