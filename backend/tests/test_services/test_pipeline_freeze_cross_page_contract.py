"""Original entrypoint contracts for freeze projection and cross-page mutation."""

import asyncio
import builtins
from types import SimpleNamespace as NS

import pytest

from app.features import cross_page_linking as linking
from app.features import pipeline_orchestrator as pipeline
from app.features.pipeline_stages import structure_freeze_stage as freeze


@pytest.fixture
def logs(monkeypatch):
    calls = []
    logger = NS(
        **{
            level: lambda *args, _level=level: calls.append((_level, args))
            for level in ("debug", "info", "warning")
        }
    )
    monkeypatch.setattr(pipeline, "logger", logger)
    return calls


def test_apply_replaces_options_in_lexical_block_order(logs):
    questions = [
        {"raw_question_text": "stem first second", "option_lines": {"Z": "old"}}
    ]
    registry = {"1:2": {"A": "later", "B": "b"}, "1:10": {"A": "first", "C": "c"}}
    blocks = [
        {"page": 1, "block_index": 2, "text": "second"},
        {"page": 1, "block_index": 10, "normalized_text": "first"},
    ]
    pipeline._apply_frozen_options(questions, registry, normalized_blocks=blocks)
    assert list(questions[0]["option_lines"].items()) == [
        ("A", "first"),
        ("C", "c"),
        ("B", "b"),
    ]
    assert questions[0]["has_options"] is questions[0]["is_frozen"] is True
    assert [level for level, _ in logs] == ["debug", "info"]


def test_apply_original_key_membership_precedes_string_conversion(logs):
    question = {"raw_question_text": "stem"}
    pipeline._apply_frozen_options(
        [question],
        {"1:0": {"1": "first", 1: "second"}},
        normalized_blocks=[{"page": 1, "text": "stem"}],
    )
    assert question["option_lines"] == {"1": "second"}


@pytest.mark.parametrize("checksum", ["different", "raises"])
def test_checksum_is_best_effort_and_logger_is_live(monkeypatch, logs, checksum):
    replacement = []

    def verify(data):
        assert data == {"1:0": {"A": "a"}}
        monkeypatch.setattr(
            pipeline,
            "logger",
            NS(
                warning=lambda *args: replacement.append(args),
                debug=lambda *args: None,
                info=lambda *args: None,
            ),
        )
        if checksum == "raises":
            raise ValueError("checksum")
        return "actual"

    monkeypatch.setattr(freeze, "_compute_freeze_checksum", verify)
    question = {"raw_question_text": "stem"}
    pipeline._apply_frozen_options(
        [question], {"1:0": {"A": "a"}}, "expected", [{"page": 1, "text": "stem"}]
    )
    assert question["is_frozen"] is True
    assert len(replacement) == 1
    assert not logs


def test_empty_registry_returns_before_checksum_import(monkeypatch):
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        assert name != "app.features.pipeline_stages.structure_freeze_stage"
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    pipeline._apply_frozen_options([{}], {})


def test_apply_no_block_match_preserves_question_and_reports_zero(logs):
    question = {"raw_question_text": "other", "option_lines": {"Z": "old"}}
    pipeline._apply_frozen_options(
        [question], {"1:0": {"A": "a"}}, normalized_blocks=[{"page": 1, "text": "stem"}]
    )
    assert question == {"raw_question_text": "other", "option_lines": {"Z": "old"}}
    assert logs[0][0] == "info"
    assert "zero questions" in logs[0][1][0]


def test_compare_truncation_and_difference_order():
    legacy = {"1:0": {str(i): str(i) for i in range(60)}}
    result = pipeline._compare_freeze_results(
        object(),
        object(),
        legacy,
        {"r": [NS(option_key="x", original_text="x ", binding_status="binding_lost")]},
    )
    assert result["differences_count"] == 61
    assert result["differences_truncated"] == 11
    assert len(result["differences"]) == 50
    assert result["binding_lost_count"] == 1
    assert list(result["differences"][0]) == [
        "type",
        "option_key",
        "legacy_text",
        "ir_text",
    ]


def test_compare_text_mismatch_follows_missing_options():
    result = pipeline._compare_freeze_results(
        {},
        {},
        {"q": {"A": "a"}},
        {"r": [NS(option_key="A", original_text="b", binding_status="bound")]},
    )
    assert [d["type"] for d in result["differences"]] == [
        "only_in_legacy",
        "only_in_ir",
        "text_mismatch",
    ]
    assert result["option_text_match"] is False


def test_remap_preserves_content_and_shallow_identities():
    entry = NS(binding_status="binding_lost")
    other = object()
    registry = {"q": {"A": "alpha", "B": "lost"}, "ir": [entry], "other": other}
    result = pipeline._remap_frozen_registry_vl_rebuild(
        registry, [{"normalized_text": "A. alpha"}, {"text": "B. lost"}]
    )
    assert result["registry"]["q"] == registry["q"]
    assert result["registry"]["q"] is not registry["q"]
    assert result["registry"]["ir"] is not registry["ir"]
    assert result["registry"]["ir"][0] is entry
    assert result["registry"]["other"] is other
    assert set(result["binding_lost_questions"]) == {"q", "ir"}
    assert result["binding_lost_option_keys"] == [("q", "B")]


def document():
    return NS(
        pages=[
            NS(page_id="s", page_index=0, regions=[]),
            NS(page_id="t", page_index=1, regions=[]),
        ],
        cross_page_links=[],
    )


def link(**overrides):
    values = dict(
        source_page_id="s",
        target_page_id="t",
        is_ambiguous=False,
        source_region_ids=["r"],
        confidence=0.8,
        reason_codes=["reason"],
    )
    values.update(overrides)
    return NS(**values, to_dict=lambda: {"source": "s", "target": "t"})


@pytest.mark.parametrize("mode", ["disabled", "single"])
def test_merge_early_return_preserves_list_identity(monkeypatch, mode):
    monkeypatch.setenv("DISABLE_CROSS_PAGE_MERGING", "1" if mode == "disabled" else "")
    monkeypatch.setattr(
        pipeline, "_get_blocks_document_ir", lambda blocks: pytest.fail("resolved")
    )
    blocks = [{}, {}] if mode == "disabled" else [{}]
    result = pipeline._merge_cross_page_blocks(blocks)
    assert result[0] is blocks
    assert result[1:] == ([], [], [])


def test_document_resolution_failure_is_outside_catch(monkeypatch):
    monkeypatch.delenv("DISABLE_CROSS_PAGE_MERGING", raising=False)
    error = ValueError("resolve")

    def fail(blocks):
        raise error

    monkeypatch.setattr(pipeline, "_get_blocks_document_ir", fail)
    with pytest.raises(ValueError) as caught:
        pipeline._merge_cross_page_blocks([{}, {}])
    assert caught.value is error


@pytest.mark.parametrize("error", [ValueError("merge"), asyncio.CancelledError()])
def test_merge_partial_state_and_exception_boundary(monkeypatch, logs, error):
    monkeypatch.delenv("DISABLE_CROSS_PAGE_MERGING", raising=False)
    doc = document()
    blocks = [{"page": 1}, {"page": 2}]
    monkeypatch.setattr(linking, "detect_cross_page_links", lambda pages: [link()])

    def fail(*args):
        blocks[0]["partial"] = True
        raise error

    monkeypatch.setattr(pipeline, "_apply_cross_page_block_merge", fail)
    if isinstance(error, asyncio.CancelledError):
        with pytest.raises(asyncio.CancelledError):
            pipeline._merge_cross_page_blocks(blocks, doc)
        assert not logs
    else:
        result = pipeline._merge_cross_page_blocks(blocks, doc)
        assert result[0] is blocks
        assert result[1] == doc.cross_page_links == [{"source": "s", "target": "t"}]
        assert result[2] == ["cross_page_error: merge"]
        assert result[3] == []
    assert blocks[0]["partial"] is True


@pytest.mark.parametrize(
    "revision,text,expected_revision,count",
    [(0, "stem", 1, 1), (0, "stem target", 1, 0), (4, "stem", 4, 0)],
)
def test_merge_only_first_source_block_and_revision(
    monkeypatch, logs, revision, text, expected_revision, count
):
    monkeypatch.setattr(linking, "_get_page_text", lambda page: "target")
    blocks = [
        {"page": 1, "normalized_text": text, "_cross_page_revision": revision},
        {"page": 1, "normalized_text": "second"},
    ]
    merged, results = pipeline._apply_cross_page_block_merge(
        blocks, [link()], document()
    )
    assert merged is not blocks and merged[0] is blocks[0]
    assert merged[0]["_cross_page_revision"] == expected_revision
    assert merged[1]["normalized_text"] == "second"
    assert len(results) == count
    if count:
        assert results[0]["source_region_ids"] == ["r"]
        assert merged[0]["normalized_text"] == "stem\ntarget"


def test_merge_keeps_partial_mutation_when_page_index_is_not_list_index(
    monkeypatch, logs
):
    doc = document()
    doc.pages[0].page_index = 5
    blocks = [{"page": 6, "normalized_text": "stem"}]
    monkeypatch.setattr(linking, "_get_page_text", lambda page: "target")
    with pytest.raises(IndexError):
        pipeline._apply_cross_page_block_merge(blocks, [link()], doc)
    assert blocks[0]["normalized_text"] == "stem\ntarget"
    assert blocks[0]["_cross_page_revision"] == 1


def test_document_lookup_can_replace_live_merge_helper_and_logger(monkeypatch):
    monkeypatch.delenv("DISABLE_CROSS_PAGE_MERGING", raising=False)
    calls = []
    blocks = [{"page": 1}, {"page": 2}]
    doc = document()

    def resolve(actual):
        assert actual is blocks
        monkeypatch.setattr(
            pipeline,
            "_apply_cross_page_block_merge",
            lambda *args: (calls.append("merge") or blocks, []),
        )
        monkeypatch.setattr(
            pipeline, "logger", NS(info=lambda *args: calls.append("log"))
        )
        return doc

    monkeypatch.setattr(pipeline, "_get_blocks_document_ir", resolve)
    monkeypatch.setattr(linking, "detect_cross_page_links", lambda pages: [link()])
    assert pipeline._merge_cross_page_blocks(blocks)[0] is blocks
    assert calls == ["merge", "log"]


def test_page_text_import_is_captured_once_per_merge_call(monkeypatch, logs):
    calls = []

    def page_text(page):
        calls.append(page.page_id)
        monkeypatch.setattr(
            linking, "_get_page_text", lambda page: pytest.fail("recaptured")
        )
        return "target"

    monkeypatch.setattr(linking, "_get_page_text", page_text)
    pipeline._apply_cross_page_block_merge(
        [{"page": 1, "normalized_text": "stem"}], [link(), link()], document()
    )
    assert calls == ["t", "t"]
