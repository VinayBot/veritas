from __future__ import annotations

from app.evaluation import grounding

ANSWER = (
    "Chatbots date back to the early 2000s [1]. They use machine learning [2]. "
    "Dialogflow launched in 2010 [3]."
)


async def test_a_blanket_flag_is_rechecked_one_sentence_at_a_time(monkeypatch):
    calls: list[str] = []

    async def fake_complete(prompt, **_):
        calls.append(prompt)
        if "List any sentences" in prompt:
            return (
                '["Chatbots date back to the early 2000s.", "They use machine learning.", '
                '"Dialogflow launched in 2010."]'
            )
        return "no" if "2010" in prompt.split("Statement:")[1] else "Yes."

    monkeypatch.setattr(grounding, "complete", fake_complete)
    claims = await grounding.unsupported_claims(ANSWER, "context about chatbots")
    assert claims == ["Dialogflow launched in 2010."]
    assert len(calls) == 4  # one bulk check, then one per flagged sentence


async def test_a_single_flag_is_not_rechecked(monkeypatch):
    calls: list[str] = []

    async def fake_complete(prompt, **_):
        calls.append(prompt)
        return '["Dialogflow launched in 2010."]'

    monkeypatch.setattr(grounding, "complete", fake_complete)
    claims = await grounding.unsupported_claims(ANSWER, "context about chatbots")
    assert claims == ["Dialogflow launched in 2010."]
    assert len(calls) == 1
