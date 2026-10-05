"""MKA fork: the shell logic of ``.github/workflows/mka-automation-cron.yaml`` against a local stub server.

The ``run:`` scripts are extracted from the workflow file and executed with bash. A deterministic stub plays the API
(scripted JSON answers, one per call), so the green / warning / red semantics are tested without GitHub. Nothing leaves
the machine (127.0.0.1) and no address appears anywhere. Skipped when bash, curl or jq is missing."""

import json
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")
pytestmark = pytest.mark.skipif(
    not all(shutil.which(t) for t in ("bash", "curl", "jq")), reason="needs bash, curl and jq"
)

WORKFLOW = Path(__file__).resolve().parents[5] / ".github" / "workflows" / "mka-automation-cron.yaml"


def step(name_starts: str) -> str:
    doc = yaml.safe_load(WORKFLOW.read_text())
    for s in doc["jobs"]["run"]["steps"]:
        if s.get("name", "").startswith(name_starts):
            return s["run"]
    raise AssertionError(name_starts)


def serve(answers):
    """answers: list of (status, body) consumed one per request; the last one repeats."""
    calls = {"n": 0}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            status, body = answers[min(calls["n"], len(answers) - 1)]
            calls["n"] += 1
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, calls


def run(script, answers, tmp_path, *, dry="false", secret="abc123"):
    server, calls = serve(answers)
    try:
        proc = subprocess.run(
            ["bash", "-c", script], cwd=tmp_path, capture_output=True, text=True, timeout=60,
            env={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "BASE_URL": f"http://127.0.0.1:{server.server_port}",
                 "MKA_AUTOMATION_CRON_SECRET": secret, "DRY_RUN": dry, "KIND": "all"},
        )
    finally:
        server.shutdown()
    out = proc.stdout + proc.stderr
    return proc.returncode, out, calls["n"]


def resp(**kw):
    base = dict(sent=0, would_send=0, failed=0, remaining=0, newly_quarantined=0, time_budget_hit=False, stopped=None,
                last_window_day=False, disabled_reason=None)
    base.update(kw)
    return (200, base)


REMINDERS = step("Run reminders")


def test_green_when_everything_was_sent(tmp_path):
    rc, out, n = run(REMINDERS, [resp(sent=40)], tmp_path)
    assert rc == 0 and n == 1 and "::error::" not in out and "::warning::" not in out and "Nothing left to do" in out


def test_a_few_failures_below_the_threshold_are_a_warning_with_counts_only(tmp_path):
    rc, out, _ = run(REMINDERS, [resp(sent=98, failed=2)], tmp_path)
    assert rc == 0 and "::warning::2 of 100 sends failed" in out and "::error::" not in out
    rc, out, _ = run(REMINDERS, [resp(sent=97, failed=3)], tmp_path)  # 3 % of the run: still only a warning
    assert rc == 0 and "::warning::" in out and "::error::" not in out


@pytest.mark.parametrize("sent, failed", [(8, 3), (12, 3), (100, 25)])
def test_red_when_a_fifth_or_more_of_the_sends_fail(tmp_path, sent, failed):
    rc, out, _ = run(REMINDERS, [resp(sent=sent, failed=failed)], tmp_path)
    assert rc == 1 and "::error::" in out and "(>= 20 %)" in out


def test_the_share_is_measured_across_all_calls_of_the_run(tmp_path):
    answers = [resp(sent=5, failed=2, remaining=3, time_budget_hit=True, stopped="time_budget_reached"),
               resp(sent=2, failed=1)]
    rc, out, n = run(REMINDERS, answers, tmp_path)  # neither call alone qualifies; together 3 of 10 failed
    assert n == 2 and rc == 1 and "3 of 10 sends failed" in out


def test_red_when_an_address_was_newly_quarantined(tmp_path):
    rc, out, _ = run(REMINDERS, [resp(sent=60, failed=1, newly_quarantined=1)], tmp_path)
    assert rc == 1 and "newly quarantined" in out


def test_red_when_nothing_could_be_sent(tmp_path):
    rc, out, _ = run(REMINDERS, [resp(sent=0, failed=5, remaining=9, stopped="too_many_consecutive_failures")], tmp_path)
    assert rc == 1 and "Nothing could be sent" in out


def test_a_failure_stop_after_progress_is_a_warning_not_a_cap_message(tmp_path):
    rc, out, _ = run(REMINDERS, [resp(sent=60, failed=1, remaining=9, stopped="too_many_consecutive_failures")], tmp_path)
    assert rc == 0 and "stopped after repeated send failures" in out and "send cap" not in out


def test_out_of_time_on_the_last_window_day_is_red_but_not_on_an_earlier_day(tmp_path):
    busy = resp(sent=30, remaining=50, time_budget_hit=True, stopped="time_budget_reached")
    rc, out, n = run(REMINDERS, [(200, {**busy[1], "last_window_day": True})], tmp_path)
    assert n == 10 and rc == 1 and "LAST day of the reminder window" in out
    rc, out, n = run(REMINDERS, [busy], tmp_path)
    assert n == 10 and rc == 0 and "::error::" not in out


def test_the_send_cap_is_a_notice_and_stays_green(tmp_path):
    rc, out, n = run(REMINDERS, [resp(sent=400, remaining=300, stopped="send_cap_reached")], tmp_path)
    assert rc == 0 and n == 1 and "::notice::The run hit its send cap with 300 left" in out


def test_a_disabled_run_says_so_and_stays_green(tmp_path):
    rc, out, _ = run(REMINDERS, [resp(disabled_reason="feature_off")], tmp_path)
    assert rc == 0 and "::notice::Reminders are switched off on the server (feature_off)" in out


@pytest.mark.parametrize("answer", [(500, {"detail": "boom"}), (404, {"detail": "no"}), (200, b"<html>maintenance</html>")])
def test_red_on_a_non_2xx_or_a_non_json_answer_and_the_body_is_never_echoed(tmp_path, answer):
    rc, out, _ = run(REMINDERS, [answer], tmp_path)
    assert rc == 1 and "::error::" in out and "maintenance" not in out and "boom" not in out


def test_a_dry_run_makes_one_call_and_never_goes_red_for_counts(tmp_path):
    rc, out, n = run(REMINDERS, [resp(would_send=300, remaining=0)], tmp_path, dry="true")
    assert rc == 0 and n == 1


def test_an_unset_secret_exits_quietly_without_calling_anything(tmp_path):
    rc, out, n = run(REMINDERS, [resp(sent=1)], tmp_path, secret="")
    assert rc == 0 and n == 0 and "::notice::" in out and "::error::" not in out


SWEEP = step("Sweep receipts")


def test_the_sweep_is_green_on_json_and_red_on_a_2xx_that_is_not_json(tmp_path):
    rc, out, _ = run(SWEEP, [(200, {"dry_run": False, "candidates": 2, "results": {"sent": 2}})], tmp_path)
    assert rc == 0 and '"sent":2' in out
    rc, out, _ = run(SWEEP, [(200, b"<html>proxy error</html>")], tmp_path)
    assert rc == 1 and "not the expected JSON" in out and "proxy error" not in out
    rc, out, _ = run(SWEEP, [(404, {"detail": "x"})], tmp_path)
    assert rc == 1 and "HTTP 404" in out


def test_the_sweep_runs_before_the_reminders_and_the_job_has_room_for_the_loop():
    doc = yaml.safe_load(WORKFLOW.read_text())
    names = [s["name"] for s in doc["jobs"]["run"]["steps"]]
    assert names.index("Sweep receipts (seam B)") < names.index("Run reminders and digests")
    assert doc["jobs"]["run"]["timeout-minutes"] >= 30
