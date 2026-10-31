"""Internal OCR worker artifact upload: the daemon's streamed hex-JSON contract."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register relationships before create_all
from app.api.internal import ocr_worker
from app.core.config import settings
from app.core.database import Base, get_db
from app.ocr_worker import daemon
from app.services import ocr_job_service as jobs

WORKER = "gpu-1"
URL = "/api/internal/ocr-worker/artifacts/upload"
AUTH = {"Worker-API-Key": f"{WORKER}/secret"}


@pytest_asyncio.fixture
async def env(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ocr.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(settings, "OCR_WORKER_ARTIFACT_DIR", str(tmp_path / "store"))
    monkeypatch.setattr(settings, "OCR_WORKER_ARTIFACT_MAX_BYTES", 1024)

    async def fake_verify(_db, worker_id, token):
        return object() if (worker_id, token) == (WORKER, "secret") else None

    monkeypatch.setattr(ocr_worker, "verify_credential", fake_verify)
    app = FastAPI()
    app.include_router(ocr_worker.router)

    async def override_db():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        yield SimpleNamespace(client=client, factory=factory, root=tmp_path / "store")
    await engine.dispose()


def _key(job_id):
    return f"ocr-results/{job_id}/document.ir.json"


def _body(job_id, data, *, key=None, sha=None, hex_data=None, trailer='"}'):
    sha = sha or hashlib.sha256(data).hexdigest()
    head = (
        f'{{"job_id":{json.dumps(job_id)},"key":{json.dumps(key or _key(job_id))},'
        f'"sha256":{json.dumps(sha)},"data":"'
    )
    hexed = data.hex() if hex_data is None else hex_data
    return head.encode() + hexed.encode() + trailer.encode()


async def _chunks(body, size=7):
    for offset in range(0, len(body), size):
        yield body[offset : offset + size]


async def _job(env, *, status="running", owner=WORKER, sha=None, lease_expires_at=None):
    job_id = uuid.uuid4().hex
    async with env.factory() as db:
        db.add(
            jobs.OCRJob(
                id=job_id,
                request_id=f"req-{job_id}",
                document_id="doc",
                document_sha256="a" * 64,
                status=status,
                input_artifact_key="uploads/x.pdf",
                input_mime_type="application/pdf",
                input_size_bytes=10,
                pipeline_fingerprint="pipe",
                lease_owner=owner,
                output_sha256=sha,
                lease_expires_at=lease_expires_at,
            )
        )
        await db.commit()
    return job_id


async def _post(env, body, *, headers=None, stream=True):
    content = _chunks(body) if stream else body
    return await env.client.post(
        URL, content=content, headers=AUTH if headers is None else headers
    )


def _files(env):
    return [p for p in env.root.rglob("*") if p.is_file()] if env.root.exists() else []


def _stored(env, job_id):
    return (env.root / "ocr-results" / job_id / "document.ir.json").read_bytes()


@pytest.mark.asyncio
async def test_daemon_upload_is_stored_with_matching_hash(env, monkeypatch):
    job_id = await _job(env)
    data = json.dumps({"pages": [{"page_index": 0}]}).encode()
    seen = {}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, url, content, headers):
            seen.update(url=url, body=b"".join(content), headers=headers)
            return SimpleNamespace(raise_for_status=lambda: None)

    monkeypatch.setattr(daemon.httpx, "Client", FakeClient)
    daemon._upload_artifact("http://srv", WORKER, "secret", job_id, _key(job_id), data)
    assert seen["url"] == "http://srv" + URL

    response = await _post(env, seen["body"], headers=seen["headers"])
    assert response.status_code == 200
    assert _stored(env, job_id) == data
    payload = response.json()["data"]
    assert payload["sha256"] == hashlib.sha256(data).hexdigest()
    assert payload["size"] == len(data)


@pytest.mark.asyncio
async def test_upload_then_complete_uses_the_stored_artifact(env):
    async with env.factory() as db:
        job = await jobs.create_job(
            db,
            request_id="flow",
            document_id="doc",
            document_sha256="a" * 64,
            input_artifact_key="uploads/x.pdf",
            input_mime_type="application/pdf",
            input_size_bytes=10,
            pipeline_fingerprint="pipe",
        )
        claimed, token = await jobs.claim_job(db, worker_id=WORKER)
        await jobs.start_job(db, claimed.id, token)
        await db.commit()
        job_id = job.id
    data = b'{"pages":[]}'
    response = await _post(env, _body(job_id, data))
    assert response.status_code == 200
    done = await env.client.post(
        f"/api/internal/ocr-worker/jobs/{job_id}/complete",
        json={
            "lease_token": token,
            "output_artifact_key": _key(job_id),
            "output_sha256": hashlib.sha256(data).hexdigest(),
        },
        headers=AUTH,
    )
    assert done.status_code == 200
    assert _stored(env, job_id) == data


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers",
    [{}, {"Worker-API-Key": "gpu-1/wrong"}, {"Worker-API-Key": "other/secret"}],
)
async def test_upload_requires_worker_credentials(env, headers):
    job_id = await _job(env)
    response = await _post(env, _body(job_id, b"x"), headers=headers)
    assert response.status_code == 401
    assert _files(env) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "owner", "code"),
    [
        ("pending", None, 409),
        ("leased", WORKER, 409),
        ("failed", WORKER, 409),
        ("running", "other", 403),
        ("uploading", None, 403),
    ],
)
async def test_upload_rejects_jobs_the_worker_cannot_write(env, status, owner, code):
    job_id = await _job(env, status=status, owner=owner)
    response = await _post(env, _body(job_id, b"x"))
    assert response.status_code == code
    assert _files(env) == []


@pytest.mark.asyncio
async def test_upload_for_unknown_job_is_404(env):
    job_id = uuid.uuid4().hex
    response = await _post(env, _body(job_id, b"x"))
    assert response.status_code == 404
    assert _files(env) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("job_id", ["../etc", "A" * 32, "a" * 31, "a/b", ""])
async def test_upload_rejects_malformed_job_ids(env, job_id):
    response = await _post(env, _body(job_id, b"x", key=f"ocr-results/{job_id}/x"))
    assert response.status_code == 400
    assert not env.root.exists() or _files(env) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "key",
    ["ocr-results/other/document.ir.json", "../x", "ocr-results/{id}/../x", "x"],
)
async def test_upload_rejects_keys_other_than_the_jobs_own(env, key):
    job_id = await _job(env)
    key = key.replace("{id}", job_id)
    response = await _post(env, _body(job_id, b"x", key=key))
    assert response.status_code == 400
    assert _files(env) == []


@pytest.mark.asyncio
async def test_sha_mismatch_is_422_and_leaves_nothing(env):
    job_id = await _job(env)
    response = await _post(env, _body(job_id, b"data", sha="0" * 64))
    assert response.status_code == 422
    assert _files(env) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda b: b.replace(b'"data":"', b'"data":"zz', 1), "not valid hex"),
        (lambda b: b.replace(b'"data":"', b'"data":"a', 1), "Truncated or malformed"),
        (lambda b: b[:-2], "Truncated or malformed"),
        (lambda b: b + b"g" * 64, "after artifact"),
        (lambda b: b + b"garbage", "Truncated or malformed"),
        (lambda b: b.replace(b'"data":"', b'"dat":"', 1), "Missing artifact header"),
        (lambda b: b"not json", "Missing artifact header"),
    ],
)
async def test_malformed_bodies_are_400_and_leave_nothing(env, mutate, reason):
    job_id = await _job(env)
    response = await _post(env, mutate(_body(job_id, b"payload")))
    assert response.status_code == 400
    assert reason in response.json()["detail"]
    assert _files(env) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(("size", "code"), [(1024, 200), (1025, 413)])
async def test_streamed_size_limit_is_enforced(env, size, code):
    job_id = await _job(env)
    response = await _post(env, _body(job_id, b"x" * size))
    assert response.status_code == code
    assert len(_files(env)) == (1 if code == 200 else 0)


@pytest.mark.asyncio
async def test_declared_oversize_is_rejected_before_reading(env, monkeypatch):
    from app.services import ocr_artifact_service as artifacts

    async def must_not_run(*_args, **_kwargs):
        raise AssertionError("body must not be read")

    monkeypatch.setattr(artifacts, "receive_artifact", must_not_run)
    job_id = await _job(env)
    response = await _post(env, _body(job_id, b"x" * 5000), stream=False)
    assert response.status_code == 413


@pytest.mark.asyncio
async def test_expired_lease_is_409(env):
    from datetime import UTC, datetime, timedelta

    job_id = await _job(env, lease_expires_at=datetime.now(UTC) - timedelta(minutes=1))
    response = await _post(env, _body(job_id, b"x"))
    assert response.status_code == 409
    assert _files(env) == []


@pytest.mark.asyncio
async def test_job_cancelled_mid_stream_is_not_published(env):
    job_id = await _job(env)
    body = _body(job_id, b"x" * 200)

    async def stream():
        yield body[: len(body) // 2]
        async with env.factory() as db:
            job = await db.get(jobs.OCRJob, job_id)
            job.status = "cancelled"
            await db.commit()
        yield body[len(body) // 2 :]

    response = await env.client.post(URL, content=stream(), headers=AUTH)
    assert response.status_code == 409
    assert _files(env) == []


@pytest.mark.asyncio
async def test_publish_failure_is_503_and_cleans_up(env, monkeypatch):
    from app.services import ocr_artifact_service as artifacts

    def boom(*_args):
        raise OSError("disk full")

    monkeypatch.setattr(artifacts.os, "replace", boom)
    job_id = await _job(env)
    response = await _post(env, _body(job_id, b"payload"))
    assert response.status_code == 503
    assert _files(env) == []


@pytest.mark.asyncio
async def test_repeat_upload_before_completion_replaces_the_file(env):
    job_id = await _job(env)
    assert (await _post(env, _body(job_id, b"first"))).status_code == 200
    assert (await _post(env, _body(job_id, b"second"))).status_code == 200
    assert _stored(env, job_id) == b"second"
    assert len(_files(env)) == 1


@pytest.mark.asyncio
async def test_completed_job_accepts_only_its_recorded_output(env):
    data = b"final"
    sha = hashlib.sha256(data).hexdigest()
    job_id = await _job(env, status="completed", owner=None, sha=sha)
    assert (await _post(env, _body(job_id, data))).status_code == 200
    assert _stored(env, job_id) == data
    other = await _post(env, _body(job_id, b"different"))
    assert other.status_code == 409
    assert _stored(env, job_id) == data
    assert len(_files(env)) == 1


@pytest.mark.asyncio
async def test_concurrent_uploads_leave_one_complete_file(env):
    job_id = await _job(env)
    first, second = b"a" * 300, b"b" * 300
    results = await asyncio.gather(
        _post(env, _body(job_id, first)), _post(env, _body(job_id, second))
    )
    assert [r.status_code for r in results] == [200, 200]
    assert _stored(env, job_id) in (first, second)
    assert len(_files(env)) == 1


@pytest.mark.asyncio
async def test_interrupted_stream_leaves_no_partial_artifact(env):
    from app.services import ocr_artifact_service as artifacts

    job_id = await _job(env)
    body = _body(job_id, b"x" * 200)

    async def broken():
        yield body[: len(body) // 2]
        raise ConnectionError("client went away")

    async def allow(_header):
        return None

    with pytest.raises(ConnectionError):
        await artifacts.receive_artifact(broken(), validate=allow)
    assert _files(env) == []


@pytest.mark.asyncio
async def test_unavailable_storage_is_503(env, tmp_path, monkeypatch):
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    monkeypatch.setattr(settings, "OCR_WORKER_ARTIFACT_DIR", str(blocker / "store"))
    job_id = await _job(env)
    response = await _post(env, _body(job_id, b"x"))
    assert response.status_code == 503


async def _started_job(env):
    async with env.factory() as db:
        job = await jobs.create_job(
            db,
            request_id=f"bind-{uuid.uuid4().hex}",
            document_id="doc",
            document_sha256="a" * 64,
            input_artifact_key="uploads/x.pdf",
            input_mime_type="application/pdf",
            input_size_bytes=10,
            pipeline_fingerprint="pipe",
        )
        claimed, token = await jobs.claim_job(db, worker_id=WORKER)
        await jobs.start_job(db, claimed.id, token)
        await db.commit()
        return job.id, token


async def _complete(env, job_id, token, *, key, sha):
    return await env.client.post(
        f"/api/internal/ocr-worker/jobs/{job_id}/complete",
        json={"lease_token": token, "output_artifact_key": key, "output_sha256": sha},
        headers=AUTH,
    )


async def _status(env, job_id):
    async with env.factory() as db:
        return (await jobs._get_job_or_raise(db, job_id)).status


@pytest.mark.asyncio
async def test_complete_rejects_non_canonical_artifact_key(env):
    job_id, token = await _started_job(env)
    data = b'{"pages":[]}'
    assert (await _post(env, _body(job_id, data))).status_code == 200
    response = await _complete(
        env, job_id, token, key="ocr-results/other/document.ir.json",
        sha=hashlib.sha256(data).hexdigest(),
    )
    assert response.status_code == 409
    assert await _status(env, job_id) != "completed"


@pytest.mark.asyncio
async def test_complete_rejects_missing_artifact(env):
    job_id, token = await _started_job(env)
    response = await _complete(env, job_id, token, key=_key(job_id), sha="b" * 64)
    assert response.status_code == 409
    assert await _status(env, job_id) != "completed"


@pytest.mark.asyncio
async def test_complete_rejects_hash_that_does_not_match_stored_artifact(env):
    job_id, token = await _started_job(env)
    assert (await _post(env, _body(job_id, b'{"pages":[]}'))).status_code == 200
    response = await _complete(env, job_id, token, key=_key(job_id), sha="c" * 64)
    assert response.status_code == 409
    assert await _status(env, job_id) != "completed"


@pytest.mark.asyncio
async def test_complete_rejects_artifact_that_is_not_a_json_object(env):
    job_id, token = await _started_job(env)
    data = b"not json"
    assert (await _post(env, _body(job_id, data))).status_code == 200
    response = await _complete(
        env, job_id, token, key=_key(job_id), sha=hashlib.sha256(data).hexdigest()
    )
    assert response.status_code == 409
    assert await _status(env, job_id) != "completed"


@pytest.mark.asyncio
async def test_upload_rejected_when_aggregate_quota_is_full(env, monkeypatch):
    monkeypatch.setattr(settings, "OCR_WORKER_ARTIFACT_TOTAL_MAX_BYTES", 1500)
    first = await _job(env)
    assert (await _post(env, _body(first, b"x" * 1000))).status_code == 200

    second = await _job(env)
    response = await _post(env, _body(second, b"y" * 1000))
    assert response.status_code == 507
    assert not list((env.root / "ocr-results" / second).glob("*"))

    # Replacing a job's own artifact does not count its previous copy twice.
    assert (await _post(env, _body(first, b"z" * 1000))).status_code == 200


def test_cleanup_removes_expired_artifacts_and_keeps_fresh_ones(env, monkeypatch):
    import os
    import time

    from app.services import ocr_artifact_service as artifacts

    monkeypatch.setattr(settings, "STAGING_RETENTION_SEC", 3600)
    old_dir = env.root / "ocr-results" / "old"
    fresh_dir = env.root / "ocr-results" / "fresh"
    old_dir.mkdir(parents=True)
    fresh_dir.mkdir(parents=True)
    old_file = old_dir / "document.ir.json"
    old_tmp = fresh_dir / ".document.ir.json.abc.tmp"
    fresh_file = fresh_dir / "document.ir.json"
    for path in (old_file, old_tmp, fresh_file):
        path.write_text("{}")
    stale = time.time() - 7200
    os.utime(old_file, (stale, stale))
    os.utime(old_tmp, (stale, stale))

    assert artifacts.cleanup_expired_artifacts() == 2
    assert not old_dir.exists()
    assert not old_tmp.exists()
    assert fresh_file.exists()


def test_cleanup_without_artifact_dir_is_a_noop(env):
    from app.services import ocr_artifact_service as artifacts

    assert artifacts.cleanup_expired_artifacts() == 0
