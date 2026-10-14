from __future__ import annotations

from app.graphrag.extractor import _parse_triples


def test_a_reply_cut_off_mid_item_keeps_the_complete_triples():
    raw = (
        '[\n {"subject": "Elena Petrova", "predicate": "reviews", "object": "approvals"},\n'
        ' {"subject": "Employees", "predicate": "use", "obj'
    )
    assert [(t.subject, t.object) for t in _parse_triples(raw)] == [("Elena Petrova", "approvals")]


def test_items_written_in_square_brackets_are_read():
    raw = (
        '["subject": "Laptops", "predicate": "must be", "object": "encrypted"],\n'
        '["subject": "Staff", "predicate": "use", "object": "the \\"VPN\\" client"]'
    )
    triples = _parse_triples(raw)
    assert [t.subject for t in triples] == ["Laptops", "Staff"]
    assert triples[1].object == 'the "VPN" client'


def test_valid_json_and_no_triples():
    assert len(_parse_triples('[{"subject": "X", "predicate": "is", "object": "Y"}]')) == 1
    assert _parse_triples("no relations here") == []
