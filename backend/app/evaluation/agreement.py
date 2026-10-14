"""How far two judge models agree. The benchmark's judge is the same small local model that
writes the answers, so a judged score could reflect that model's own preferences. A second
judge from a different model family re-scores the correctness of the same answers against the
same known answers; close agreement means the judged scores are not one model's opinion."""

from __future__ import annotations

from dataclasses import dataclass

from app.evaluation.benchmark import BenchmarkReport
from app.evaluation.judge import says_not_covered, score_correctness
from app.evaluation.stats import pearson

# Answers at or above this are counted as correct when comparing the two judges' verdicts.
CORRECT_AT = 0.7


@dataclass
class JudgeAgreement:
    first_judge: str
    second_judge: str
    n: int
    mean_absolute_difference: float
    pearson_r: float | None
    verdict_agreement: float
    cohen_kappa: float | None

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def _kappa(a: list[bool], b: list[bool]) -> float | None:
    n = len(a)
    if n == 0:
        return None
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    pa, pb = sum(a) / n, sum(b) / n
    expected = pa * pb + (1 - pa) * (1 - pb)
    return None if expected == 1 else (observed - expected) / (1 - expected)


async def measure_agreement(
    report: BenchmarkReport, first_judge: str, second_judge: str
) -> JudgeAgreement | None:
    firsts: list[float] = []
    seconds: list[float] = []
    for result in report.config_results:
        for sample in result.samples:
            reference = sample.get("reference_answer") or ""
            if sample.get("correctness") is None or not reference or says_not_covered(reference):
                continue
            second = await score_correctness(
                sample["answer"], reference, sample.get("question", ""), model=second_judge
            )
            if second is None:
                continue
            firsts.append(float(sample["correctness"]))
            seconds.append(second)
    if not firsts:
        return None
    a = [x >= CORRECT_AT for x in firsts]
    b = [y >= CORRECT_AT for y in seconds]
    return JudgeAgreement(
        first_judge=first_judge,
        second_judge=second_judge,
        n=len(firsts),
        mean_absolute_difference=round(
            sum(abs(x - y) for x, y in zip(firsts, seconds, strict=True)) / len(firsts), 3
        ),
        pearson_r=None if (r := pearson(firsts, seconds)) is None else round(r, 3),
        verdict_agreement=round(sum(x == y for x, y in zip(a, b, strict=True)) / len(a), 3),
        cohen_kappa=None if (k := _kappa(a, b)) is None else round(k, 3),
    )
