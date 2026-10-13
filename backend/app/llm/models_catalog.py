"""What models are actually installed, what each can be used for, and whether a selection
fits the machine.

Chat models come from Ollama's own API (installed, loaded, sizes, capabilities). Embedding
and reranking models are Hugging Face models run by sentence-transformers, so those lists
come from this project's candidate registries, with whether each is already downloaded.
Cloud models appear only when their API key is set.
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.health import OLLAMA_START_HINT
from app.embeddings.registry import CANDIDATE_MODELS, loaded_embedder_names
from app.llm.models_config import ModelConfig, get_model_config

RERANKER_CANDIDATES = (
    "cross-encoder/ms-marco-MiniLM-L-6-v2",
    "cross-encoder/ms-marco-MiniLM-L-12-v2",
    "BAAI/bge-reranker-base",
)

# Offered only when the matching API key is set. LiteLLM model ids; edit here if a provider
# renames a model.
CLOUD_MODELS: dict[str, tuple[str, ...]] = {
    "groq": ("groq/llama-3.3-70b-versatile", "groq/llama-3.1-8b-instant"),
    "gemini": ("gemini/gemini-2.0-flash", "gemini/gemini-1.5-flash"),
}

# Memory this project budgets for chat models per hardware tier, leaving room for the OS,
# the embedder, the reranker and Docling. Declared, not measured.
TIER_BUDGET_BYTES = {"8gb": 5 * 1024**3, "16gb": 11 * 1024**3}

# A model this small tends to answer the question instead of grading the answer (see
# docs/TROUBLESHOOTING.md on the critic). A rule of thumb, shown as such.
JUDGE_MIN_PARAMS_B = 3.0

_PARAM_RE = re.compile(r"([\d.]+)\s*([BM])", re.IGNORECASE)


def _params_billions(parameter_size: str | None) -> float | None:
    match = _PARAM_RE.search(parameter_size or "")
    if not match:
        return None
    value = float(match.group(1))
    return value if match.group(2).upper() == "B" else value / 1000


def _roles(name: str, capabilities: list[str], params_b: float | None) -> dict[str, Any]:
    is_guard = "guard" in name.lower()
    can_generate = "completion" in capabilities and not is_guard
    can_embed = "embedding" in capabilities
    judge_ok = can_generate and (params_b is None or params_b >= JUDGE_MIN_PARAMS_B)
    return {
        "generator": can_generate,
        "council_member": can_generate,
        "judge": judge_ok,
        "embedder": can_embed,
        "guard": is_guard,
        "notes": [
            note
            for note in (
                "Safety classifier: it labels text, it does not answer questions."
                if is_guard
                else None,
                "Embedding-only model: it cannot generate text."
                if can_embed and not can_generate
                else None,
                f"Under {JUDGE_MIN_PARAMS_B:g}B parameters: usable as a judge, but small models "
                "grade unreliably."
                if can_generate and not judge_ok
                else None,
            )
            if note
        ],
    }


async def ollama_models() -> dict[str, Any]:
    """Installed Ollama models with size, quantization, context length, family, whether each
    is loaded right now, and what it can be used for. Reports the exact failure if Ollama is
    not reachable."""
    base = get_settings().ollama_base_url
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            tags = await client.get(f"{base}/api/tags")
            tags.raise_for_status()
            ps = await client.get(f"{base}/api/ps")
            ps.raise_for_status()
            installed = tags.json().get("models", [])
            shows = await asyncio.gather(
                *(client.post(f"{base}/api/show", json={"model": m["name"]}) for m in installed),
                return_exceptions=True,
            )
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        return {
            "status": "down",
            "error": f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__,
            "fix": OLLAMA_START_HINT,
            "base_url": base,
            "models": [],
        }

    loaded = {m["name"]: m for m in ps.json().get("models", [])}
    models = []
    for entry, show in zip(installed, shows, strict=True):
        details = entry.get("details", {}) or {}
        shown: dict[str, Any] = {}
        if isinstance(show, httpx.Response) and show.status_code == 200:
            shown = show.json()
        capabilities = list(shown.get("capabilities") or [])
        context = details.get("context_length") or next(
            (v for k, v in (shown.get("model_info") or {}).items() if k.endswith("context_length")),
            None,
        )
        params_b = _params_billions(details.get("parameter_size"))
        live = loaded.get(entry["name"])
        models.append(
            {
                "id": f"ollama/{entry['name']}",
                "name": entry["name"],
                "provider": "ollama",
                "cloud": False,
                "family": details.get("family"),
                "parameter_size": details.get("parameter_size"),
                "parameters_billions": params_b,
                "quantization": details.get("quantization_level"),
                "context_length": context,
                "disk_bytes": entry.get("size"),
                "loaded": live is not None,
                "vram_bytes": live.get("size_vram") if live else None,
                "expires_at": live.get("expires_at") if live else None,
                "capabilities": capabilities,
                # When Ollama reports no capabilities (older versions), nothing is assumed.
                "capabilities_known": bool(capabilities),
                "roles": _roles(entry["name"], capabilities, params_b),
            }
        )
    return {"status": "up", "error": None, "fix": None, "base_url": base, "models": models}


def cloud_models() -> list[dict[str, Any]]:
    settings = get_settings()
    keys = {"groq": settings.groq_api_key, "gemini": settings.gemini_api_key}
    out = []
    for provider, ids in CLOUD_MODELS.items():
        if not keys[provider]:
            continue
        for model_id in ids:
            out.append(
                {
                    "id": model_id,
                    "name": model_id.split("/", 1)[1],
                    "provider": provider,
                    "cloud": True,
                    "loaded": False,
                    "disk_bytes": None,
                    "vram_bytes": None,
                    "roles": {
                        "generator": True,
                        "council_member": True,
                        "judge": True,
                        "embedder": False,
                        "guard": False,
                        "notes": [
                            "Cloud model: text leaves this machine, and calls may be billed."
                        ],
                    },
                }
            )
    return out


def _hf_cache_dir(model_name: str) -> Path:
    home = os.environ.get("HF_HOME") or str(Path.home() / ".cache" / "huggingface")
    hub = os.environ.get("HF_HUB_CACHE") or str(Path(home) / "hub")
    return Path(hub) / ("models--" + model_name.replace("/", "--"))


def _dir_bytes(path: Path) -> int | None:
    if not path.exists():
        return None
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file() and not f.is_symlink())


def huggingface_models(candidates: tuple[str, ...], loaded: list[str]) -> list[dict[str, Any]]:
    out = []
    for name in candidates:
        cache = _hf_cache_dir(name)
        out.append(
            {
                "id": name,
                "name": name,
                "provider": "huggingface",
                "downloaded": cache.exists(),
                "loaded": name in loaded,
                "disk_bytes": _dir_bytes(cache),
            }
        )
    return out


def assess_budget(config: ModelConfig, ollama: list[dict[str, Any]]) -> dict[str, Any]:
    """Whether the selected chat models fit the tier's budget. Uses real loaded memory where
    a model is loaded and its size on disk otherwise (a lower bound on what it needs)."""
    tier = get_settings().hardware_tier
    budget = TIER_BUDGET_BYTES.get(tier, TIER_BUDGET_BYTES["16gb"])
    by_id = {m["id"]: m for m in ollama}
    selected = [m for m in dict.fromkeys(config.all_llm_models()) if m in by_id]
    sizes = {m: by_id[m]["vram_bytes"] or by_id[m]["disk_bytes"] or 0 for m in selected}
    # On 8 GB the council runs one model at a time, so the peak is the largest single model
    # plus the generator; on 16 GB council members are resident together.
    if tier == "8gb":
        peak = max(sizes.values(), default=0)
        basis = "the largest selected model (models run one at a time on this tier)"
    else:
        peak = sum(sizes.values())
        basis = "all selected models resident together (the council runs concurrently)"
    return {
        "tier": tier,
        "budget_bytes": budget,
        "selected_bytes": peak,
        "basis": basis,
        "over_budget": peak > budget,
        "per_model": sizes,
        "warning": (
            f"This selection needs about {peak / 1024**3:.1f} GB for {basis}, over the "
            f"{budget / 1024**3:.0f} GB this project budgets for chat models on the {tier} tier. "
            "Expect swapping or slow, serial model loads."
            if peak > budget
            else None
        ),
    }


async def catalog() -> dict[str, Any]:
    config = get_model_config()
    ollama = await ollama_models()
    from app.retrieval.reranker import loaded_reranker_names

    return {
        "ollama": {k: v for k, v in ollama.items() if k != "models"},
        "chat_models": [*ollama["models"], *cloud_models()],
        "embedding_models": huggingface_models(CANDIDATE_MODELS, loaded_embedder_names()),
        "reranker_models": huggingface_models(RERANKER_CANDIDATES, loaded_reranker_names()),
        "selection": {
            "generator": config.generator,
            "judge": config.judge,
            "council": config.council,
            "chairman": config.chairman,
            "embedding": config.embedding,
            "reranker": config.reranker,
            "guard": config.guard,
        },
        "budget": assess_budget(config, ollama["models"]),
    }


class SelectionError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


async def validate_selection(changes: dict[str, Any]) -> None:
    """Refuses a pairing that cannot work: a model that is not installed, an embedding or
    guard model offered as a chat model, an unknown embedder or reranker."""
    chat = {m["id"]: m for m in (await catalog())["chat_models"]}

    def need(model_id: str, role: str, label: str) -> None:
        model = chat.get(model_id)
        if model is None:
            raise SelectionError(
                f"{model_id} is not installed. Pull it first (`ollama pull "
                f"{model_id.removeprefix('ollama/')}`), or choose a model from the list."
            )
        if not model["roles"].get(role):
            notes = " ".join(model["roles"].get("notes", []))
            raise SelectionError(f"{model_id} cannot be used as the {label}. {notes}".strip())

    if "generator" in changes:
        need(changes["generator"], "generator", "generator")
    if "judge" in changes:
        need(changes["judge"], "judge", "judge")
    if "chairman" in changes:
        need(changes["chairman"], "generator", "council chairman")
    if "council" in changes:
        members = changes["council"]
        if len(set(members)) != len(members):
            raise SelectionError("The council roster lists the same model twice.")
        for member in members:
            need(member, "council_member", "council member")
    if "embedding" in changes and changes["embedding"] not in CANDIDATE_MODELS:
        raise SelectionError(
            f"{changes['embedding']} is not a supported embedding model. "
            f"Choose one of: {', '.join(CANDIDATE_MODELS)}."
        )
    if "reranker" in changes and changes["reranker"] not in RERANKER_CANDIDATES:
        raise SelectionError(
            f"{changes['reranker']} is not a supported reranker. "
            f"Choose one of: {', '.join(RERANKER_CANDIDATES)}."
        )
