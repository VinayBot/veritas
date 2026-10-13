"""How long an answer should be.

A normal question gets a quick reply of three or four lines. Asking for depth ("explain in
detail", "deep dive", "elaborate") — or choosing Deep in the UI — gets seven or eight. The
length is a property of the turn, so every path that writes an answer (direct strategies,
the agent's synthesizer and summarizer, the council) reads the same instruction from here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

DETAIL_LEVELS = ("brief", "deep")
MAX_SENTENCES = {"brief": 4, "deep": 8}

_DEEP_RE = re.compile(
    r"\b("
    r"in[- ]depth|in detail|detailed|deep(?:er|ly)?(?: dive| answer| reply| explanation)?|"
    r"elaborate|thorough(?:ly)?|comprehensive(?:ly)?|step[- ]by[- ]step|"
    r"explain (?:fully|thoroughly|everything)|full (?:explanation|answer|breakdown)|"
    r"long(?:er)? (?:answer|reply|explanation)|more detail|walk me through"
    r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class AnswerStyle:
    detail: str
    instruction: str
    max_tokens: int
    """True when the answer should come from the fast generator without escalating to a
    slower, stronger model — a quick reply should be quick."""
    prefer_fast_model: bool


_BRIEF = AnswerStyle(
    detail="brief",
    instruction=(
        "Write 3 to 4 lines: three or four full sentences, about 50 to 70 words in total. The "
        "first sentence is the direct answer; the next two or three add the conditions, "
        "numbers or exceptions the context gives for it. Plain prose, no bullet points, no "
        "preamble, no restating the question, no closing summary."
    ),
    max_tokens=170,
    prefer_fast_model=True,
)

_DEEP = AnswerStyle(
    detail="deep",
    instruction=(
        "Write 7 to 8 lines: seven or eight full sentences, about 130 to 170 words in total. "
        "Start with the direct answer, then cover every relevant detail, condition, number "
        "and exception the context gives, drawing on more than one source where they apply. "
        "Stop after the eighth sentence. Plain prose, no bullet points, no preamble, no "
        "closing summary and no list of references at the end."
    ),
    max_tokens=330,
    prefer_fast_model=False,
)


def wants_depth(query: str) -> bool:
    return bool(_DEEP_RE.search(query))


def resolve_detail(query: str, requested: str | None = None) -> str:
    """`requested` is the UI's explicit choice ("brief" | "deep"); anything else means
    decide from how the question is phrased."""
    if requested in DETAIL_LEVELS:
        return str(requested)
    return "deep" if wants_depth(query) else "brief"


def style_for(detail: str | None) -> AnswerStyle:
    return _DEEP if detail == "deep" else _BRIEF


_TRAILING_SOURCES_RE = re.compile(
    r"\n\s*(?:\*\*)?(?:references|sources|citations)(?:\*\*)?\s*:?\s*\n.*\Z",
    re.IGNORECASE | re.DOTALL,
)


# A sentence ends at . ! or ? — optionally followed by citation markers — before whitespace.
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])(?:\s*\[\d+(?:\s*,\s*\d+)*\])*(?=\s|$)")
_NUMBER_BEFORE_DOT_RE = re.compile(r"(?:\d|\b(?:e\.g|i\.e|vs|etc|Mr|Mrs|Ms|Dr|No))\.$")


def _sentences(text: str) -> list[str]:
    """Splits into sentences, keeping each one's trailing citation markers with it."""
    parts: list[str] = []
    start = 0
    for match in _SENTENCE_END_RE.finditer(text):
        end = match.end()
        candidate = text[start:end]
        # "5.5 days", "e.g." and numbered-list markers are not sentence ends.
        if _NUMBER_BEFORE_DOT_RE.search(text[start : match.start()]) and not match.group().strip():
            continue
        if candidate.strip():
            parts.append(candidate.strip())
        start = end
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def tidy_answer(answer: str, detail: str | None = None) -> str:
    """Makes the reply the length it was asked to be.

    Drops a "References:" list a model sometimes appends (inline markers like [2] are the
    citations), a last sentence that was cut off by the token limit, and — when `detail` is
    given — anything past the fourth sentence of a quick answer or the eighth of a deep one.
    Nothing is rewritten: sentences are only ever removed from the end."""
    text = _TRAILING_SOURCES_RE.sub("", answer).strip()
    if not text:
        return text
    sentences = _sentences(text)
    if len(sentences) > 1 and not re.search(r"[.!?][\s\]\[\d,]*$", sentences[-1]):
        sentences = sentences[:-1]  # cut off mid-sentence
    if detail in DETAIL_LEVELS:
        sentences = sentences[: MAX_SENTENCES[detail]]
    return " ".join(sentences) if len(sentences) < len(_sentences(text)) else text
