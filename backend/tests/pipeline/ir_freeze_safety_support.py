"""Helpers for real split execution; external services stay behind fixture guards."""

from tests.pipeline.ir_freeze_binding_support import source_blocks


def freeze_sources(runtime, monkeypatch, blocks=None, *, mode="ir"):
    if blocks is None:
        blocks = source_blocks(1)
    document = runtime.build(blocks, source_bytes=b"ir-binding-safety")
    blocks[0]["_document_ir"] = document
    monkeypatch.setattr(runtime.settings, "STRUCTURE_FREEZE_MODE", mode)
    pipeline = runtime.pipeline_module.ImportPipeline(options={})
    return pipeline, blocks, pipeline._run_structure_freeze(blocks), document


def split_frozen(pipeline, blocks, frozen, **arguments):
    values = {"import_mode": "exam", "source_type": "pdf", **frozen, **arguments}
    return pipeline._run_split(blocks, **values)


def assert_unbound(result, *, reason):
    assert result["raw_questions"]
    assert all(not question.get("is_frozen") for question in result["raw_questions"])
    diagnostics = result["freeze_binding_diagnostics"]
    assert diagnostics["accepted_questions"] == 0
    assert reason in diagnostics["reasons"]


def assert_bound(result, expected):
    questions = result["raw_questions"]
    assert len(questions) == len(expected)
    assert [question["option_lines"] for question in questions] == expected
    assert all(question["is_frozen"] for question in questions)
    assert all(question["_original_raw_text"] for question in questions)
    assert result["freeze_binding_diagnostics"]["accepted_questions"] == len(expected)


def reseal(plan):
    from app.features.freeze_source_binding import binding_checksum

    plan["checksum"] = binding_checksum(plan)
