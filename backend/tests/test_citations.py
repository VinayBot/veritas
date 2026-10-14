from __future__ import annotations

from app.agents.citations import citation_markers
from app.agents.orchestrator import _citations_from
from app.evaluation.judge import citation_validity


def test_grouped_markers_count_as_citations() -> None:
    """Small models often write "[7, 8]"; that is two citations, not none."""
    answer = "Early bots were built at Penn [7, 8]. Deep learning followed [4]. See [3,5]."
    assert citation_markers(answer) == [7, 8, 4, 3, 5]
    hits = [{"chunk_id": f"c{i}", "text": f"text {i}"} for i in range(1, 9)]
    assert [c["marker"] for c in _citations_from(answer, hits)] == [3, 4, 5, 7, 8]
    assert citation_validity("Built at Penn [7, 8].", num_context_items=8) == 1.0
    assert citation_validity("Built at Penn [7, 9].", num_context_items=8) == 0.5
