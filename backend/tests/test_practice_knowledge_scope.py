from types import SimpleNamespace

from app.services.practice.chapter_scope import bucket_targets, knowledge_bucket


def _state(*, attempts=1, confidence=1.0, mastery=50.0):
    return SimpleNamespace(
        attempt_count=attempts,
        confidence=confidence,
        mastery_score=mastery,
    )


def test_chapter_bucket_prefers_weak_and_unobserved():
    assert knowledge_bucket(None) == "unobserved"
    assert knowledge_bucket(_state(attempts=0, confidence=1.0, mastery=90)) == "unobserved"
    assert knowledge_bucket(_state(attempts=3, confidence=0.2, mastery=20)) == "unobserved"
    assert knowledge_bucket(_state(attempts=3, confidence=0.8, mastery=39.9)) == "weak"
    assert knowledge_bucket(_state(attempts=3, confidence=0.8, mastery=60)) == "developing"
    assert knowledge_bucket(_state(attempts=3, confidence=0.8, mastery=84.9)) == "developing"
    assert knowledge_bucket(_state(attempts=3, confidence=0.8, mastery=85)) == "stable"


def test_chapter_bucket_targets_sum_to_requested_count():
    for count in range(0, 51):
        targets = bucket_targets(count)
        assert set(targets) == {"weak", "unobserved", "developing", "stable"}
        assert sum(targets.values()) == count
        assert all(value >= 0 for value in targets.values())


def test_ten_question_chapter_mix_matches_product_target():
    assert bucket_targets(10) == {
        "weak": 4,
        "unobserved": 3,
        "developing": 2,
        "stable": 1,
    }
