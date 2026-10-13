"""Whether a strategy can run right now, for a given document, and if not, exactly why and
what would fix it. Checked live: nothing here is cached or assumed."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.core.config import get_settings
from app.core.health import OLLAMA_START_HINT, ollama_inventory
from app.ingestion.models import Document
from app.llm.models_config import get_model_config
from app.rag_engines.base import StrategySpec
from app.rag_engines.registry import INDEX_VARIANTS
from app.rag_engines.variants import has_variant

TIER_ORDER = {"8gb": 0, "16gb": 1}


@dataclass
class Availability:
    available: bool
    reason: str | None = None
    """What the UI can offer to do about it: "build_index" | "build_graph" | None."""
    action: str | None = None
    variant: str | None = None
    """Runnable, but with a caveat worth showing (for example a slower tier)."""
    warning: str | None = None

    def to_dict(self) -> dict:
        return {
            "available": self.available,
            "reason": self.reason,
            "action": self.action,
            "variant": self.variant,
            "warning": self.warning,
        }


@dataclass
class LlmState:
    ok: bool
    reason: str | None
    installed: list[str] | None


async def llm_state() -> LlmState:
    """Can the generator model answer at all? Every strategy needs it."""
    config = get_model_config()
    if not config.generator.startswith("ollama/"):
        return LlmState(True, None, None)  # a cloud model: reachability is checked on use
    try:
        installed = (await ollama_inventory())["installed"]
    except (httpx.HTTPError, KeyError, ValueError):
        return LlmState(False, f"Ollama is not running. {OLLAMA_START_HINT}", None)
    name = config.generator.removeprefix("ollama/")
    if name not in installed:
        return LlmState(
            False, f"The generator model is not installed. Run `ollama pull {name}`.", installed
        )
    return LlmState(True, None, installed)


async def check(spec: StrategySpec, document: Document | None, llm: LlmState) -> Availability:
    if not llm.ok:
        return Availability(False, reason=llm.reason)

    warning: str | None = None
    tier = get_settings().hardware_tier
    if TIER_ORDER.get(tier, 1) < TIER_ORDER[spec.min_hardware_tier]:
        warning = (
            f"Designed for the {spec.min_hardware_tier} tier. On {tier} its models run one "
            "after another, so expect it to take several times longer."
        )

    if spec.council:
        config = get_model_config()
        if len(config.council) < 2:
            return Availability(
                False,
                reason="A council needs at least two models; add them to the roster in Settings.",
            )
        if llm.installed is not None:
            missing = [
                m.removeprefix("ollama/")
                for m in [*config.council, config.chairman]
                if m.startswith("ollama/") and m.removeprefix("ollama/") not in llm.installed
            ]
            if missing:
                return Availability(
                    False,
                    reason=f"Council model not installed: {', '.join(missing)}. "
                    f"Run `ollama pull {missing[0]}`.",
                )

    if document is None:
        return Availability(True, warning=warning)

    if document.status != "ready":
        return Availability(False, reason=f"The document is still {document.status}.")

    plan = spec.plan
    if plan is not None and plan.variant != "default":
        if not await has_variant(document.id, plan.variant):
            description = INDEX_VARIANTS[plan.variant].description.lower()
            return Availability(
                False,
                reason=f"Needs an index this document does not have yet: {description}.",
                action="build_index",
                variant=plan.variant,
                warning=warning,
            )

    if plan is not None and plan.graph and not (document.graph_entity_count or 0):
        if document.enrichment_status == "running":
            return Availability(False, reason="The knowledge graph is still being built.")
        return Availability(
            False,
            reason="No knowledge graph has been built for this document "
            "(no entities were extracted).",
            action="build_graph",
            warning=warning,
        )

    return Availability(True, warning=warning)
