#!/usr/bin/env python3
"""`make doctor` (Phase 6 backlog item 4's "warm start... add make doctor to check models and
API keys"). Read-only diagnostic, deliberately distinct from `make models` (which actively
downloads/warms everything): this just reports current status — Ollama reachability and which
of the 4 required local models are actually present, whether the optional cloud-provider keys
(GROQ_API_KEY, GEMINI_API_KEY) and the required PII_VAULT_KEY are set (presence only, never
printing a value), and whether the data directory exists and is writable. Safe to run before
`make setup` has even finished, and safe to run repeatedly — it changes nothing.
"""

from __future__ import annotations

import os
import sys

import httpx

sys.path.insert(0, ".")

from app.core.config import get_settings  # noqa: E402


def _required_ollama_models() -> list[str]:
    """Whatever this installation is configured to use, not a fixed list."""
    from app.llm.models_config import get_model_config

    names = [m.removeprefix("ollama/") for m in get_model_config().all_llm_models()]
    return list(dict.fromkeys(n for n in names if "/" not in n))


REQUIRED_OLLAMA_MODELS = _required_ollama_models()


def _check(label: str, ok: bool, detail: str) -> bool:
    print(f"[{'OK  ' if ok else 'WARN'}] {label:<24} {detail}")
    return ok


def main() -> int:
    settings = get_settings()
    all_ok = True

    print("Veritas doctor — read-only status check (nothing is downloaded or modified)\n")

    # --- Ollama + required local models ---
    try:
        resp = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=3.0)
        resp.raise_for_status()
        present = {m["name"] for m in resp.json().get("models", [])}
        all_ok &= _check("Ollama reachable", True, settings.ollama_base_url)
        for model in REQUIRED_OLLAMA_MODELS:
            found = any(model == name or name.startswith(f"{model}-") for name in present)
            all_ok &= _check(
                f"  model {model}",
                found,
                "present" if found else "missing — run: ollama pull " + model,
            )
    except httpx.HTTPError as exc:
        all_ok &= _check(
            "Ollama reachable", False, f"{settings.ollama_base_url} unreachable ({exc})"
        )
        print("         (every required-model check below is skipped — Ollama must answer first)")

    # --- Cloud provider keys (presence only — never print the value) ---
    for env_var, required in [
        ("GROQ_API_KEY", False),
        ("GEMINI_API_KEY", False),
        ("PII_VAULT_KEY", True),
    ]:
        value = os.environ.get(env_var, "") or getattr(settings, env_var.lower(), "")
        key_present = bool(value)
        if required:
            all_ok &= _check(
                env_var,
                key_present,
                "set" if key_present else "NOT SET — required for PII masking in prod",
            )
        else:
            _check(
                env_var,
                True,
                "set (cloud fallback available)"
                if key_present
                else "not set (optional — Ollama-only is fine)",
            )

    # --- Data directory ---
    data_dir = settings.data_dir
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        probe = data_dir / ".doctor-write-probe"
        probe.write_text("ok")
        probe.unlink()
        all_ok &= _check("Data directory writable", True, str(data_dir))
    except OSError as exc:
        all_ok &= _check("Data directory writable", False, f"{data_dir}: {exc}")

    # --- Backend itself, if already running ---
    try:
        resp = httpx.get(f"http://localhost:{settings.api_port}/api/v1/health", timeout=2.0)
        _check("Backend running", resp.status_code == 200, f"localhost:{settings.api_port}")
    except httpx.HTTPError:
        _check(
            "Backend running", True, "not running right now (fine — this check doesn't require it)"
        )

    print()
    print(
        "PASS — ready for `make dev`."
        if all_ok
        else "Some checks above need attention before `make dev` will work smoothly."
    )
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
