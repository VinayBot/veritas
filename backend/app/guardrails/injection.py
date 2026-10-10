"""Prompt-injection detection: fast regex heuristics first (catch the obvious cases without a
model), then the DeBERTa classifier for subtler attempts. Used by both the input layer (on the
user's message) and the retrieval layer (on retrieved/scraped content, which Section 10 treats
as untrusted — "indirect injection via document").
"""

from __future__ import annotations

import re
from functools import lru_cache

MODEL_NAME = "protectai/deberta-v3-base-prompt-injection-v2"

_INJECTION_PATTERNS = [
    re.compile(r"ignore (all )?(previous|prior|above) instructions", re.I),
    re.compile(r"disregard (all )?(previous|prior|above)", re.I),
    re.compile(r"new instructions?\s*:", re.I),
    re.compile(r"reveal (your|the) (system )?prompt", re.I),
    re.compile(r"print (your|the) (system )?(instructions|prompt)", re.I),
    re.compile(r"act as (if )?(you are )?(an? )?(unrestricted|jailbroken)\b", re.I),
    re.compile(r"</?(system|assistant|user)>", re.I),
    re.compile(r"\bDAN\b"),
    re.compile(r"you are now (in )?(developer|dan|unfiltered) mode", re.I),
]


class InjectionVerdict:
    def __init__(self, is_injection: bool, score: float, matched: str | None = None):
        self.is_injection = is_injection
        self.score = score
        self.matched = matched


def regex_scan(text: str) -> InjectionVerdict:
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            return InjectionVerdict(is_injection=True, score=0.95, matched=pattern.pattern)
    return InjectionVerdict(is_injection=False, score=0.0)


@lru_cache(maxsize=1)
def _get_classifier():
    from transformers import pipeline

    return pipeline("text-classification", model=MODEL_NAME)


def classifier_scan(text: str) -> InjectionVerdict:
    try:
        classifier = _get_classifier()
        result = classifier(text[:2000])[0]
    except Exception:
        return InjectionVerdict(is_injection=False, score=0.0)

    label = str(result["label"]).upper()
    score = float(result["score"])
    is_injection = label in ("INJECTION", "LABEL_1", "1", "UNSAFE", "MALICIOUS")
    return InjectionVerdict(is_injection=is_injection, score=score if is_injection else 1.0 - score)


def scan(text: str) -> InjectionVerdict:
    regex_result = regex_scan(text)
    if regex_result.is_injection:
        return regex_result
    return classifier_scan(text)
