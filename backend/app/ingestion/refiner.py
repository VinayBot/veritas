"""Messy-document cleanup: normalize, de-hyphenate, strip repeated headers/footers/boilerplate,
merge broken paragraphs, drop near-duplicate paragraphs, detect language, score quality.

The quality score is a deterministic heuristic over the text itself (control-character ratio,
very-short-line ratio, exact-duplicate-line ratio, run-on whitespace) — computed the same way
before and after refinement, so the delta is a real measurement of what the fixes did, not an
invented number.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

from datasketch import MinHash, MinHashLSH

_PAGE_NUMBER_RE = re.compile(r"^\s*(page\s+)?\d{1,4}(\s*/\s*\d{1,4})?(\s+of\s+\d+)?\s*$", re.I)
_BOILERPLATE_KEYWORDS = (
    "all rights reserved",
    "cookie policy",
    "accept cookies",
    "privacy policy",
    "terms of service",
    "unsubscribe",
    "click here",
)
_HYPHEN_BREAK_RE = re.compile(r"(\w)-\n(\w)")
_SENTENCE_END_RE = re.compile(r"[.!?:;’\"')\]]\s*$")


@dataclass
class FixLogEntry:
    type: str
    count: int
    examples: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"type": self.type, "count": self.count, "examples": self.examples[:3]}


@dataclass
class RefinementResult:
    text: str
    quality_before: float
    quality_after: float
    fix_log: list[dict]
    language: str | None
    duplication_ratio: float


def _quality_score(text: str, line_count_baseline: int | None = None) -> float:
    """`line_count_baseline`, when given, is the *original* (pre-refinement) non-empty line
    count. Both the before and after scores must divide by the same baseline — otherwise a
    cleanup pass that strips most junk lines can *concentrate* whatever duplication remains
    against a shrunken denominator and score the cleaned text lower than the messy original,
    which would make the before/after comparison meaningless."""
    lines = text.split("\n")
    non_empty = [ln for ln in lines if ln.strip()]
    if not non_empty:
        return 0.0
    denom = max(line_count_baseline or len(non_empty), 1)

    control_chars = sum(1 for ch in text if ord(ch) < 32 and ch not in "\n\t")
    control_ratio = control_chars / max(len(text), 1)

    very_short = sum(1 for ln in non_empty if len(ln.strip()) <= 2)
    short_ratio = very_short / denom

    counts = Counter(ln.strip() for ln in non_empty if len(ln.strip()) > 20)
    dup_lines = sum(c - 1 for c in counts.values() if c > 1)
    dup_ratio = dup_lines / denom

    long_whitespace_runs = len(re.findall(r" {3,}", text))
    ws_penalty = min(long_whitespace_runs / denom, 1.0)

    score = 100.0
    score -= control_ratio * 200
    score -= short_ratio * 40
    score -= dup_ratio * 40
    score -= ws_penalty * 10
    return round(max(0.0, min(100.0, score)), 1)


def _detect_language(text: str) -> str | None:
    sample = text.strip()
    if len(sample) < 20:
        return None
    try:
        from langdetect import LangDetectException, detect

        return detect(sample)
    except LangDetectException:
        return None
    except ImportError:
        return None


def _dehyphenate(text: str, fixes: list[FixLogEntry]) -> str:
    count = 0

    def _join(m: re.Match) -> str:
        nonlocal count
        count += 1
        return m.group(1) + m.group(2)

    result = _HYPHEN_BREAK_RE.sub(_join, text)
    if count:
        fixes.append(FixLogEntry("dehyphenation", count))
    return result


def _strip_repeated_lines_and_boilerplate(text: str, fixes: list[FixLogEntry]) -> str:
    lines = text.split("\n")
    stripped_counts = Counter(ln.strip() for ln in lines if ln.strip())
    repeated = {ln for ln, c in stripped_counts.items() if c >= 3 and len(ln) < 80}

    kept = []
    removed_examples: list[str] = []
    page_number_hits = 0
    boilerplate_hits = 0
    repeated_hits = 0

    for ln in lines:
        stripped = ln.strip()
        if stripped and _PAGE_NUMBER_RE.match(stripped):
            page_number_hits += 1
            continue
        if stripped and any(kw in stripped.lower() for kw in _BOILERPLATE_KEYWORDS):
            boilerplate_hits += 1
            removed_examples.append(stripped[:60])
            continue
        if stripped in repeated:
            repeated_hits += 1
            removed_examples.append(stripped[:60])
            continue
        kept.append(ln)

    if page_number_hits:
        fixes.append(FixLogEntry("page_numbers_removed", page_number_hits))
    if boilerplate_hits:
        fixes.append(FixLogEntry("boilerplate_removed", boilerplate_hits, removed_examples))
    if repeated_hits:
        fixes.append(FixLogEntry("repeated_header_footer_removed", repeated_hits, removed_examples))

    return "\n".join(kept)


def _merge_broken_paragraphs(text: str, fixes: list[FixLogEntry]) -> str:
    paragraphs = text.split("\n\n")
    merged_count = 0
    out_paragraphs = []
    for para in paragraphs:
        raw_lines = [ln for ln in para.split("\n")]
        buffer: list[str] = []
        for ln in raw_lines:
            stripped = ln.strip()
            if not stripped:
                buffer.append(ln)
                continue
            if (
                buffer
                and buffer[-1].strip()
                and not _SENTENCE_END_RE.search(buffer[-1].strip())
                and not stripped[0].isupper()
                and not stripped.startswith(("#", "-", "*", "|"))
            ):
                buffer[-1] = buffer[-1].rstrip() + " " + stripped
                merged_count += 1
            else:
                buffer.append(ln)
        out_paragraphs.append("\n".join(buffer))
    if merged_count:
        fixes.append(FixLogEntry("broken_paragraph_merged", merged_count))
    return "\n\n".join(out_paragraphs)


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
# A sentence this long that recurs this often is template wording ("This section exists to
# provide additional context..."), not content.
_TEMPLATE_SENTENCE_MIN_CHARS = 60
_TEMPLATE_SENTENCE_MIN_REPEATS = 3


def _sentence_key(sentence: str) -> str:
    return " ".join(sentence.split()).lower()


def _dedupe_paragraphs(text: str, fixes: list[FixLogEntry]) -> tuple[str, float]:
    """Removes repetition without removing content.

    A near-duplicate paragraph (MinHash similarity >= 0.8) is dropped only when every one of
    its sentences already appeared earlier. Before, it was dropped outright: a policy that
    wraps each fact in the same template wording lost the fact with the template; a 61-page
    handbook kept 14,717 of its 261,352 characters. Then template sentences, long sentences
    repeated three or more times, are kept only where they first occur."""
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    if len(paragraphs) < 2:
        return text, 0.0

    lsh = MinHashLSH(threshold=0.8, num_perm=64)
    kept: list[str] = []
    seen: set[str] = set()
    removed = 0
    examples: list[str] = []

    for i, para in enumerate(paragraphs):
        sentences = [_sentence_key(x) for x in _SENTENCE_SPLIT_RE.split(para) if x.strip()]
        shingles = {para[j : j + 8] for j in range(max(len(para) - 8, 1))} or {para}
        mh = MinHash(num_perm=64)
        for shingle in shingles:
            mh.update(shingle.encode("utf-8"))
        if len(para) > 40 and lsh.query(mh) and all(x in seen for x in sentences):
            removed += 1
            examples.append(para[:60])
            continue
        if len(para) > 40:
            lsh.insert(f"p{i}", mh)
        seen.update(sentences)
        kept.append(para)

    counts = Counter(
        _sentence_key(x) for para in kept for x in _SENTENCE_SPLIT_RE.split(para) if x.strip()
    )
    template = {
        key
        for key, n in counts.items()
        if n >= _TEMPLATE_SENTENCE_MIN_REPEATS and len(key) >= _TEMPLATE_SENTENCE_MIN_CHARS
    }
    trimmed = 0
    if template:
        emitted: set[str] = set()
        out: list[str] = []
        for para in kept:
            # Sentences with the whitespace that follows each, so a paragraph that loses
            # nothing is unchanged and one that does keeps its own line breaks.
            pieces = re.split(r"(?<=[.!?])(\s+)", para)
            pairs = [
                (pieces[i], pieces[i + 1] if i + 1 < len(pieces) else "")
                for i in range(0, len(pieces), 2)
            ]
            parts = []
            for sentence, gap in pairs:
                key = _sentence_key(sentence)
                if key in template and key in emitted:
                    trimmed += 1
                    continue
                emitted.add(key)
                parts.append(sentence + gap)
            rebuilt = "".join(parts).strip()
            if rebuilt:
                out.append(rebuilt if len(parts) < len(pairs) else para)
        kept = out

    if removed:
        fixes.append(FixLogEntry("near_duplicate_paragraph_removed", removed, examples))
    if trimmed:
        fixes.append(FixLogEntry("repeated_template_sentence_removed", trimmed))
    return "\n\n".join(kept), removed / len(paragraphs)


def refine(raw_text: str, ocr_confidence: float | None = None) -> RefinementResult:
    baseline_lines = len([ln for ln in raw_text.split("\n") if ln.strip()])
    quality_before = _quality_score(raw_text, line_count_baseline=baseline_lines)
    fixes: list[FixLogEntry] = []

    text = unicodedata.normalize("NFKC", raw_text)
    text = _dehyphenate(text, fixes)
    text = _strip_repeated_lines_and_boilerplate(text, fixes)
    text = _merge_broken_paragraphs(text, fixes)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    before_collapse = len(text)
    text = text.strip()
    if before_collapse and len(text) != before_collapse:
        fixes.append(FixLogEntry("whitespace_collapsed", 1))

    text, duplication_ratio = _dedupe_paragraphs(text, fixes)

    language = _detect_language(text)
    quality_after = _quality_score(text, line_count_baseline=baseline_lines)

    return RefinementResult(
        text=text,
        quality_before=quality_before,
        quality_after=quality_after,
        fix_log=[f.to_dict() for f in fixes],
        language=language,
        duplication_ratio=round(duplication_ratio, 3),
    )
