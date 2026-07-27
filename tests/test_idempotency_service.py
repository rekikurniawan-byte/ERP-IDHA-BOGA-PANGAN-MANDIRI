import pytest

from app.services.idempotency_service import (
    IdempotencyConflictError,
    assert_replay_matches,
    build_request_hash,
)


def test_request_hash_is_order_independent():
    left = build_request_hash({"amount": "1000", "invoice_id": 5})
    right = build_request_hash({"invoice_id": 5, "amount": "1000"})

    assert left == right
    assert len(left) == 64


def test_replay_hash_conflict_is_rejected():
    original = build_request_hash({"amount": "1000"})
    changed = build_request_hash({"amount": "1001"})

    with pytest.raises(IdempotencyConflictError):
        assert_replay_matches(original, changed)


def test_replay_hash_match_is_allowed():
    request_hash = build_request_hash({"payment_number": "PAY-1"})

    assert_replay_matches(request_hash, request_hash)
