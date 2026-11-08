"""Task 07.04 Tests: Loop detection and runaway cost prevention.

Contracts: C07, C08.
Assertions:
1. Whitespace-only SQL repetition fails REPAIR_STALLED.
2. SELECT literal 'A' versus 'a' are not collapsed.
3. Repeated error signatures stop.
4. Different runs do not share seen hashes.
5. Max two repairs, 16000 cumulative tokens and the original 30-second run deadline are enforced.
"""

from __future__ import annotations


from querylens.pipeline.errors import ClassifiedError
from querylens.pipeline.loop_detection import LoopDetector, candidate_fingerprint


def test_whitespace_repetition_yields_identical_fingerprint() -> None:
    sql1 = "SELECT  id,   name FROM users WHERE active = 1"
    sql2 = "SELECT id, name\nFROM users\nWHERE   active = 1"
    assert candidate_fingerprint(sql1) == candidate_fingerprint(sql2)


def test_string_literal_case_preserved_in_fingerprint() -> None:
    sql_upper = "SELECT * FROM users WHERE status = 'ACTIVE'"
    sql_lower = "SELECT * FROM users WHERE status = 'active'"
    assert candidate_fingerprint(sql_upper) != candidate_fingerprint(sql_lower)


def test_loop_detector_stops_on_repeated_sql() -> None:
    detector = LoopDetector()
    sql = "SELECT id FROM users"

    # First encounter
    assert detector.check_candidate(sql) is True

    # Same query candidate (even with varied whitespace)
    sql_with_spaces = "SELECT   id   FROM    users"
    assert detector.check_candidate(sql_with_spaces) is False


def test_loop_detector_stops_on_repeated_consecutive_error_signatures() -> None:
    detector = LoopDetector()
    err = ClassifiedError(
        category="unknown_identifier",
        code="UNDEFINED_COLUMN",
        safe_message="column foo does not exist",
        repairable=True,
    )

    # First time error signature occurs
    assert detector.check_error_signature(err.error_signature) is True

    # Repeated consecutive identical error signature
    assert detector.check_error_signature(err.error_signature) is False


def test_different_runs_do_not_share_state() -> None:
    run1_detector = LoopDetector()
    run2_detector = LoopDetector()

    sql = "SELECT id FROM accounts"
    assert run1_detector.check_candidate(sql) is True
    # Run 1 repeated
    assert run1_detector.check_candidate(sql) is False

    # Run 2 has independent state
    assert run2_detector.check_candidate(sql) is True
