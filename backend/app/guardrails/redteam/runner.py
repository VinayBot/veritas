"""Runs the red-team corpus (app/guardrails/redteam/attacks.py) through the real input
guardrail and reports the block rate (attacks correctly blocked) and false-positive rate
(benign messages incorrectly blocked) — the two numbers Section 10 and the Definition of Done
gate on. Every verdict comes from actually calling `check_input`, never a lookup table.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.guardrails.input import check_input
from app.guardrails.redteam.attacks import ATTACKS, BENIGN, Attack


@dataclass
class AttackResult:
    category: str
    text: str
    blocked: bool
    rule: str


@dataclass
class CategoryStats:
    total: int
    blocked: int
    block_rate: float


@dataclass
class RedTeamReport:
    attack_results: list[AttackResult] = field(default_factory=list)
    benign_results: list[AttackResult] = field(default_factory=list)

    @property
    def total_attacks(self) -> int:
        return len(self.attack_results)

    @property
    def blocked_attacks(self) -> int:
        return sum(1 for r in self.attack_results if r.blocked)

    @property
    def block_rate(self) -> float:
        return self.blocked_attacks / self.total_attacks if self.total_attacks else 0.0

    @property
    def total_benign(self) -> int:
        return len(self.benign_results)

    @property
    def false_positives(self) -> int:
        return sum(1 for r in self.benign_results if r.blocked)

    @property
    def false_positive_rate(self) -> float:
        return self.false_positives / self.total_benign if self.total_benign else 0.0

    def by_category(self) -> dict[str, CategoryStats]:
        categories: dict[str, list[AttackResult]] = {}
        for r in self.attack_results:
            categories.setdefault(r.category, []).append(r)
        return {
            cat: CategoryStats(
                total=len(results),
                blocked=sum(1 for r in results if r.blocked),
                block_rate=sum(1 for r in results if r.blocked) / len(results),
            )
            for cat, results in categories.items()
        }


async def _run_one(item: Attack) -> AttackResult:
    session_id = f"redteam-{uuid.uuid4()}"
    trace_id = str(uuid.uuid4())
    result = await check_input(item.text, session_id, trace_id)
    return AttackResult(
        category=item.category, text=item.text, blocked=result.decision == "block", rule=result.rule
    )


async def run_redteam_suite() -> RedTeamReport:
    report = RedTeamReport()
    for attack in ATTACKS:
        report.attack_results.append(await _run_one(attack))
    for text in BENIGN:
        report.benign_results.append(await _run_one(Attack("benign", text)))
    return report
