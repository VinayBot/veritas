#!/usr/bin/env python3
"""`make planner-eval`: routing accuracy of the agent's planner, JSON prompt vs native tool
calling, on tests/fixtures/planner_routing.json. Needs Ollama."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, ".")

from app.agents.planner import plan  # noqa: E402

CASES = json.loads(
    (
        Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "planner_routing.json"
    ).read_text()
)["cases"]


async def main() -> None:
    for mode in ("json", "tool_call"):
        right, via_tool = 0, 0
        for case in CASES:
            result = await plan(case["question"], mode=mode)
            right += result["category"] == case["category"]
            via_tool += result["via"] == "tool_call"
            if result["category"] != case["category"]:
                print(
                    f"  [{mode}] {case['question']!r}: {result['category']} "
                    f"(expected {case['category']})"
                )
        note = f", {via_tool} answered by a native tool call" if mode == "tool_call" else ""
        print(f"{mode}: {right}/{len(CASES)} routed correctly ({right / len(CASES):.0%}){note}")


asyncio.run(main())
