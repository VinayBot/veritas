"""Entity + relation extraction: spaCy NER for entities (fast, deterministic), an LLM with a
strict JSON schema prompt for relation triples (NER alone can't tell you *how* two entities
relate). Both degrade gracefully — spaCy NER basically never fails; the LLM path falls back to
an empty triple list (not a crash) if the model is unavailable or returns malformed JSON, same
pattern as app/retrieval/hyde.py.
"""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache

from pydantic import BaseModel

from app.llm.client import LlmUnavailableError, complete

logger = logging.getLogger(__name__)


class Entity(BaseModel):
    text: str
    label: str
    start: int
    end: int


class Triple(BaseModel):
    subject: str
    predicate: str
    object: str


@lru_cache(maxsize=1)
def _get_nlp():
    import spacy

    return spacy.load("en_core_web_sm")


def extract_entities(text: str) -> list[Entity]:
    nlp = _get_nlp()
    doc = nlp(text)
    return [
        Entity(text=ent.text, label=ent.label_, start=ent.start_char, end=ent.end_char)
        for ent in doc.ents
    ]


_TRIPLE_PROMPT = """Extract factual relationship triples from the text below. Return ONLY a \
JSON array, no other text, no markdown fences. Each element must be an object with exactly \
these keys: "subject", "predicate", "object" — all short strings copied or paraphrased from \
the text. Extract at most {max_triples} of the clearest triples. If there are none, return [].

Text:
\"\"\"
{text}
\"\"\"

JSON array:"""

_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)


def _parse_triples(raw: str) -> list[Triple]:
    candidate = raw.strip()
    match = _JSON_ARRAY_RE.search(candidate)
    if match:
        candidate = match.group(0)
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        logger.info("Triple extraction: could not parse LLM output as JSON")
        return []
    if not isinstance(parsed, list):
        return []

    triples = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        if {"subject", "predicate", "object"} <= item.keys():
            try:
                triples.append(
                    Triple(**{k: str(item[k]) for k in ("subject", "predicate", "object")})
                )
            except (TypeError, ValueError):
                continue
    return triples


async def extract_triples_llm(
    text: str, model: str | None = None, max_triples: int = 15
) -> list[Triple]:
    prompt = _TRIPLE_PROMPT.format(text=text[:4000], max_triples=max_triples)
    try:
        raw = await complete(prompt, model=model, max_tokens=800, temperature=0.0)
    except LlmUnavailableError:
        logger.info("Triple extraction: LLM unavailable, returning no triples for this chunk")
        return []
    return _parse_triples(raw)
