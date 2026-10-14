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


# PII masking (app/privacy/tokenizer.py's make_token) runs before chunking, which runs before
# graph extraction — so by the time any of this sees the text, a real name is already
# "<PERSON_6cc6eb>". spaCy's NER has never seen that shape of token and doesn't tag it as
# anything, which silently drops every relationship a masked person was ever part of: see
# docs/TROUBLESHOOTING.md. Matching the token's own format recovers it as a same-shaped entity
# (label "PERSON"/"EMAIL_ADDRESS"/etc., text the token itself) without ever touching the real
# value — the opaque token is all this ever sees or stores.
_PII_TOKEN_RE = re.compile(r"<([A-Z_]+)_[0-9a-f]{6}>")


def extract_entities(text: str) -> list[Entity]:
    nlp = _get_nlp()
    doc = nlp(text)
    entities = [
        Entity(text=ent.text, label=ent.label_, start=ent.start_char, end=ent.end_char)
        for ent in doc.ents
    ]
    for match in _PII_TOKEN_RE.finditer(text):
        entities.append(
            Entity(
                text=match.group(0),
                label=match.group(1),
                start=match.start(),
                end=match.end(),
            )
        )
    return entities


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


# One triple, written as an object or, by a small model, as a bracketed list of the same
# key-value pairs: {"subject": …, "predicate": …, "object": …} or ["subject": …, …].
_TRIPLE_ITEM_RE = re.compile(
    r'[{\[]\s*("subject"\s*:.*?"object"\s*:\s*"(?:[^"\\]|\\.)*")\s*[}\]]', re.DOTALL
)


def _parse_triples(raw: str) -> list[Triple]:
    """Every complete triple in the reply. The whole reply is not required to be valid JSON:
    llama3.2:3b's list was often cut off by the token limit partway through its last item, or
    used [ ] for an item, and rejecting the whole reply for that left the sample policy with
    16 entities and no relations at all."""
    candidate = raw.strip()
    match = _JSON_ARRAY_RE.search(candidate)
    try:
        parsed = json.loads(match.group(0) if match else candidate)
    except json.JSONDecodeError:
        parsed = None
    if not isinstance(parsed, list):
        parsed = []
        for item in _TRIPLE_ITEM_RE.finditer(candidate):
            try:
                parsed.append(json.loads("{" + item.group(1) + "}"))
            except json.JSONDecodeError:
                continue
        if not parsed:
            logger.info("Triple extraction: no complete triple in the LLM output")

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
    text: str, model: str | None = None, max_triples: int = 8
) -> list[Triple]:
    # Eight relations from a 2,500-character window: a few seconds per chunk on a small local
    # model, instead of the 15-25 s an 800-token reply took.
    prompt = _TRIPLE_PROMPT.format(text=text[:2500], max_triples=max_triples)
    try:
        raw = await complete(prompt, model=model, max_tokens=320, temperature=0.0)
    except LlmUnavailableError:
        logger.info("Triple extraction: LLM unavailable, returning no triples for this chunk")
        return []
    return _parse_triples(raw)
