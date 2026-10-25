"""Host-only rig policy regressions: no network, SSH, hardware or real sleeps."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

SPEC = importlib.util.spec_from_file_location(
    "rig_retry", Path(__file__).parents[1] / "tools/run_input_isolation.py"
)
rig = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rig)


class Clock:
    def __init__(self):
        self.now = 0
        self.sleeps = []

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(rig.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(rig.time, "sleep", clock.sleep)
    return clock


def reply(code=200, body=None):
    response = requests.Response()
    response.status_code = code
    response._content = (
        b"<html>edge failure</html>" if code >= 500 else json.dumps(body or {}).encode()
    )
    return response


@pytest.mark.parametrize("code", range(500, 600))
@pytest.mark.parametrize("endpoint", ["health", "status", "result", "results", "logs"])
def test_every_5xx_endpoint_retries_same_request(monkeypatch, clock, code, endpoint):
    calls = []

    def send(url, **kwargs):
        calls.append((url, kwargs))
        return reply(code) if len(calls) == 1 else reply(body={"ok": True})

    monkeypatch.setattr(requests, "get", send)
    monkeypatch.setattr(requests, "post", send)
    fields = None if endpoint in {"health", "logs"} else {"test_id": "one"}
    assert rig.request_json("http://rig", endpoint, fields=fields) == {"ok": True}
    assert calls[0] == calls[1]
    assert clock.sleeps == [30]


def test_mixed_5xx_exhaust_only_after_ten_continuous_minutes(monkeypatch, clock):
    codes = iter([500, 502, 503, 504, 520, 521, 522, 523, 524, 599] * 3)
    calls = []

    def get(*args, **kwargs):
        calls.append(clock.now)
        return reply(next(codes))

    monkeypatch.setattr(requests, "get", get)
    with pytest.raises(requests.HTTPError):
        rig.request_json("http://rig", "health")
    assert calls == list(range(0, 601, 30))
    assert clock.sleeps == [30] * 20


def test_success_at_boundary_and_each_new_request_resets_budget(monkeypatch, clock):
    responses = iter([reply(503)] * 20 + [reply()] + [reply(524)] * 20 + [reply()])
    monkeypatch.setattr(requests, "get", lambda *a, **k: next(responses))
    rig.request_json("http://rig", "health")
    rig.request_json("http://rig", "health")
    assert clock.now == 1200


@pytest.mark.parametrize("code", [400, 401, 403, 404, 409, 429])
def test_4xx_is_not_retried(monkeypatch, clock, code):
    monkeypatch.setattr(requests, "get", lambda *a, **k: reply(code))
    with pytest.raises(requests.HTTPError):
        rig.request_json("http://rig", "health")
    assert not clock.sleeps


@pytest.mark.parametrize("code", range(500, 600))
@pytest.mark.parametrize("accepted", [True, False])
def test_start_reconciles_before_any_replay(monkeypatch, clock, accepted, code):
    events = []
    bodies = []

    def post(url, **kwargs):
        events.append("post")
        bodies.append(kwargs)
        return reply(code) if len(bodies) == 1 else reply(body={"test_id": "new"})

    def recover():
        events.append("journal")
        assert clock.now == 30
        return {"test_id": "accepted"} if accepted else None

    monkeypatch.setattr(requests, "post", post)
    result = rig.request_json(
        "http://rig", "start", fields={"python": "pass"}, recover_start=recover
    )
    assert events == (["post", "journal"] if accepted else ["post", "journal", "post"])
    assert result["test_id"] == ("accepted" if accepted else "new")
    assert all(body == bodies[0] for body in bodies)


def test_unreadable_journal_holds_start_without_duplicate(monkeypatch, clock):
    calls = []

    def post(*args, **kwargs):
        calls.append(1)
        return reply(500)

    def recover():
        raise OSError("SSH unavailable")

    monkeypatch.setattr(requests, "post", post)
    with pytest.raises(OSError):
        rig.request_json("http://rig", "start", fields={}, recover_start=recover)
    assert len(calls) == 1
    assert clock.now == 600


@pytest.mark.parametrize(
    "queued",
    [
        {"status": "queued"},
        {"status": "pending"},
        {"status": "running", "message": "Test is queued"},
        {"status": "running", "queue_position": 2},
    ],
)
def test_queue_and_separate_5xx_periods_do_not_spend_execution_budget(
    monkeypatch, clock, tmp_path, queued
):
    statuses = iter(
        [reply(body=queued)] * 1201
        + [reply(503)] * 19
        + [reply(body={"status": "running"})]
        + [reply(524)] * 19
        + [reply(body={"status": "success"})]
    )
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("/results"):
            return reply(body={"results": {"completed": True}})
        return next(statuses)

    monkeypatch.setattr(requests, "post", post)
    active = []
    assert rig.wait_for_result(
        "http://rig",
        "key",
        "job",
        tmp_path,
        2,
        on_active=lambda job: active.append((job, clock.now)),
    ) == {"results": {"completed": True}}
    assert clock.now > 2300
    assert active == [("job", 1771)]  # Never provision queued/terminal jobs.
    assert all(call[1]["json"]["test_id"] == "job" for call in calls)
    assert (tmp_path / "results.json").exists()


def test_running_job_still_has_execution_timeout(monkeypatch, clock, tmp_path):
    monkeypatch.setattr(
        requests, "post", lambda *a, **k: reply(body={"status": "running"})
    )
    with pytest.raises(RuntimeError, match="execution deadline"):
        rig.wait_for_result("http://rig", "key", "job", tmp_path, 3)
    assert clock.now == 3


def test_shared_queue_is_healthy(monkeypatch):
    health = {
        "status": "healthy",
        "checks": {
            "coordinator_mode": "normal",
            "queue_depth": 100,
            "worker_thread_alive": True,
            "docker_reachable": True,
            "hub_reachable": True,
        },
    }
    monkeypatch.setattr(requests, "get", lambda *a, **k: reply(body=health))
    assert rig.service_preflight("http://rig") == health


def test_recovered_job_is_persisted_and_resume_never_submits(
    monkeypatch, clock, tmp_path
):
    calls = []
    job = "cafe0000-1111-2222-3333-444444444444"

    def post(url, **kwargs):
        calls.append(url.rsplit("/", 1)[1])
        assert (tmp_path / "submission.json").exists()
        if url.endswith("/start"):
            return reply(503)
        if url.endswith("/status"):
            return reply(body={"status": "success"})
        return reply(body={"results": {"completed": True}})

    monkeypatch.setattr(rig, "service_preflight", lambda _: {})
    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(rig, "recover_submission", lambda *a: {"test_id": job})
    for _ in range(2):
        rig.submit_program("http://rig", "secret", b"hex", "pass", tmp_path, 5)
    assert calls == ["start", "status", "results", "status", "results"]
    assert json.loads((tmp_path / "start.json").read_text())["test_id"] == job
    assert "secret" not in (tmp_path / "submission.json").read_text()
    with pytest.raises(ValueError, match="does not match"):
        rig.submit_program("http://rig", "secret", b"different", "pass", tmp_path, 5)


def test_journal_matches_only_this_submission(monkeypatch, tmp_path):
    job = "cafe0000-1111-2222-3333-444444444444"
    messages = [
        f"Starting new test {job} for board teensy (agent unique-token)",
        "Starting new test dead0000-1111-2222-3333-444444444444 for board teensy (agent someone-else)",
    ]
    monkeypatch.setattr(
        rig.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            stdout="\n".join(json.dumps({"MESSAGE": line}) for line in messages),
            stderr="",
            returncode=0,
        ),
    )
    found = rig.recover_submission(
        "http://rig", {"agent_name": "unique-token", "created_at": 123}, tmp_path
    )
    assert found["test_id"] == job
    assert json.loads((tmp_path / "start.json").read_text()) == found


def test_start_outage_budget_is_not_reset_by_successful_journal_reads(
    monkeypatch, clock
):
    posts = []
    monkeypatch.setattr(
        requests, "post", lambda *a, **k: posts.append(clock.now) or reply(503)
    )
    with pytest.raises(requests.HTTPError):
        rig.request_json("http://rig", "start", fields={}, recover_start=lambda: None)
    assert posts == list(range(0, 601, 30))


def test_final_5xx_still_reconciles_acceptance(monkeypatch, clock):
    posts = []
    monkeypatch.setattr(
        requests, "post", lambda *a, **k: posts.append(clock.now) or reply(500)
    )

    def recover():
        return {"test_id": "last-attempt"} if len(posts) == 21 else None

    assert rig.request_json(
        "http://rig", "start", fields={}, recover_start=recover
    ) == {"test_id": "last-attempt"}
    assert clock.now == 600


def test_resume_uses_frozen_inputs_and_existing_job(monkeypatch, clock, tmp_path):
    (tmp_path / "firmware.ino.hex").write_bytes(b"frozen")
    (tmp_path / "rig-program.py").write_text("pass")
    (tmp_path / "provenance.json").write_text(json.dumps({"service": "http://rig"}))
    (tmp_path / "start.json").write_text(json.dumps({"test_id": "saved"}))
    calls = []

    def post(url, **kwargs):
        calls.append(url.rsplit("/", 1)[1])
        assert kwargs["json"]["test_id"] == "saved"
        if url.endswith("/status"):
            return reply(body={"status": "success"})
        return reply(body={"results": {"completed": True}})

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(rig, "classify_result", lambda *a, **k: {"outcome": "PASS"})
    assert rig.resume_saved_program("http://rig", "secret", tmp_path) == 0
    assert calls == ["status", "results"]
    assert json.loads((tmp_path / "summary.json").read_text())["outcome"] == "PASS"


def test_unknown_start_cannot_bypass_reconciliation(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: pytest.fail("unguarded POST"))
    with pytest.raises(ValueError, match="journal reconciliation"):
        rig.request_json("http://rig", "start", fields={})


@pytest.mark.parametrize(
    "code,stderr,stdout,absent",
    [
        (1, "", "", True),
        (255, "SSH failed", "", False),
        (0, "Permission denied", "", False),
        (1, "", "partial output", False),
    ],
)
def test_journal_absence_is_distinct_from_failed_read(
    monkeypatch, tmp_path, code, stderr, stdout, absent
):
    monkeypatch.setattr(
        rig.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=code, stderr=stderr, stdout=stdout),
    )
    submission = {"agent_name": "unique-token", "created_at": 123}
    if absent:
        assert rig.recover_submission("http://rig", submission, tmp_path) is None
    else:
        with pytest.raises(RuntimeError, match="incomplete"):
            rig.recover_submission("http://rig", submission, tmp_path)
    assert not (tmp_path / "start.json").exists()


def test_successful_http_latency_counts_toward_execution_budget(
    monkeypatch, clock, tmp_path
):
    calls = []

    def post(*args, **kwargs):
        calls.append(clock.now)
        clock.now += 5
        return reply(body={"status": "running"})

    monkeypatch.setattr(requests, "post", post)
    with pytest.raises(RuntimeError, match="execution deadline"):
        rig.wait_for_result("http://rig", "key", "job", tmp_path, 3)
    assert len(calls) == 2
    assert clock.now == 11
