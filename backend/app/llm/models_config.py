"""The models every role is currently using.

One accessor, so no call site reads `settings.default_llm_model` directly: which model
generates, judges, sits on the council, embeds and reranks is a runtime choice (see
app/core/runtime_settings.py), with `.env` supplying the zero-config defaults.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core import runtime_settings
from app.core.config import get_settings


@dataclass(frozen=True)
class ModelConfig:
    provider: str
    generator: str
    judge: str
    council: list[str]
    chairman: str
    guard: str
    embedding: str
    reranker: str

    def all_llm_models(self) -> list[str]:
        ordered = [self.generator, self.judge, self.chairman, self.guard, *self.council]
        return list(dict.fromkeys(m for m in ordered if m))

    def stronger_model(self) -> str | None:
        """The designated "use this for harder judgment calls" model: the first council member
        that is not the generator. None when there is no second model to escalate to, or when
        escalation is switched off (the default — see ESCALATE_TO_STRONGER_MODEL) so that only
        one answer model is ever held in memory."""
        if not get_settings().escalate_to_stronger_model:
            return None
        return next((m for m in self.council if m != self.generator), None)


def get_model_config() -> ModelConfig:
    settings = get_settings()
    overrides = runtime_settings.current()
    generator = overrides.get("generator_model") or settings.default_llm_model
    council = overrides.get("council_models")
    return ModelConfig(
        provider=settings.llm_provider,
        generator=generator,
        judge=overrides.get("judge_model") or settings.judge_model or generator,
        council=list(council) if council is not None else settings.council_model_list,
        chairman=overrides.get("chairman_model") or settings.chairman_model,
        guard=settings.guard_model,
        embedding=overrides.get("embedding_model") or settings.embedding_model,
        reranker=overrides.get("reranker_model") or settings.reranker_model,
    )
