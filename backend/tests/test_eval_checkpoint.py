"""Resumable evaluation checkpoints (deterministic: no LLM, no network)."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from evals.checkpoint import Checkpoint, IncompatibleCheckpoint, fingerprint, hash_tree, with_status

BACKEND = Path(__file__).resolve().parent.parent
ENV = {**os.environ, "LLM_PROVIDER": "mock", "EMBEDDING_PROVIDER": "hashing", "EMBEDDING_DIM": "256"}
MANIFEST = {"provider": "ollama", "model": "qwen2.5:3b", "embedder": "nomic-embed-text", "embedding_dim": 768,
            "embedding_query_prefix": "q: ", "embedding_document_prefix": "d: ", "ollama_num_ctx": 4096, "retrieval_top_k": 5,
            "max_agent_steps": 5, "prompt_sha": "p", "dataset_sha": "d", "code_sha": "c", "git": "abc"}


def rec(i, status="ok", passed=True, **kw):
    return {"id": i, "status": status, "passed": passed, "flags": [], **kw}


def test_roundtrip_and_completed_ids(tmp_path):
    ck = Checkpoint(tmp_path / "r.partial.jsonl")
    ck.open_for_run(MANIFEST)
    ck.append(rec("a"))
    ck.append(rec("b", passed=False))
    s = ck.load()
    assert s.completed_ids() == {"a", "b"} and s.manifest["fingerprint"] == fingerprint(MANIFEST)


def test_retry_supersedes_error_and_errors_stay_in_audit_trail(tmp_path):
    ck = Checkpoint(tmp_path / "r.jsonl")
    ck.open_for_run(MANIFEST)
    ck.append(rec("a", status="error", passed=False, attempt=1))
    assert ck.load().completed_ids() == set()  # an error is not a completed case
    ck.append(rec("a", attempt=2))
    s = ck.load()
    assert s.completed_ids() == {"a"} and len(s.errors) == 1 and s.records["a"]["attempt"] == 2


def test_duplicate_ok_records_do_not_duplicate_results(tmp_path):
    ck = Checkpoint(tmp_path / "r.jsonl")
    ck.open_for_run(MANIFEST)
    ck.append(rec("a", answer="first"))
    ck.append(rec("a", answer="second"))
    s = ck.load()
    assert list(s.records) == ["a"] and s.records["a"]["answer"] == "second"


def test_torn_last_line_is_ignored(tmp_path):
    ck = Checkpoint(tmp_path / "r.jsonl")
    ck.open_for_run(MANIFEST)
    ck.append(rec("a"))
    with ck.path.open("a", encoding="utf-8") as fh:
        fh.write('{"id": "b", "status": "ok", "pass')  # process killed mid-write
    s = ck.load()
    assert s.completed_ids() == {"a"} and s.torn_lines == 1
    ck.append(rec("b"))  # and the run can carry on appending
    assert Checkpoint(ck.path).load().completed_ids() == {"a", "b"}


@pytest.mark.parametrize("field,value", [("model", "llama3.2:1b"), ("embedder", "all-minilm"), ("embedding_dim", 384),
                                         ("dataset_sha", "other"), ("code_sha", "other"), ("prompt_sha", "other"),
                                         ("ollama_num_ctx", 2048), ("embedding_query_prefix", "")])
def test_incompatible_configuration_is_rejected(tmp_path, field, value):
    ck = Checkpoint(tmp_path / "r.jsonl")
    ck.open_for_run(MANIFEST)
    ck.append(rec("a"))
    with pytest.raises(IncompatibleCheckpoint, match=field):
        ck.open_for_run({**MANIFEST, field: value})
    assert ck.load().completed_ids() == {"a"}  # nothing was lost or modified


def test_code_change_needs_explicit_acceptance_and_is_audited(tmp_path):
    ck = Checkpoint(tmp_path / "r.jsonl")
    ck.open_for_run(MANIFEST)
    ck.append(rec("a"))
    changed = {**MANIFEST, "code_sha": "c2", "git": "def"}
    with pytest.raises(IncompatibleCheckpoint, match="code_sha"):
        ck.open_for_run(changed)
    s = ck.open_for_run(changed, accept_code_change=True)
    assert s.completed_ids() == {"a"} and s.manifest["code_sha_history"][0]["code_sha"] == "c"
    assert ck.open_for_run(changed).completed_ids() == {"a"}  # now compatible without the flag
    with pytest.raises(IncompatibleCheckpoint, match="model"):  # the override never covers other fields
        ck.open_for_run({**changed, "model": "x", "code_sha": "c3"}, accept_code_change=True)


def test_git_revision_alone_does_not_invalidate(tmp_path):
    ck = Checkpoint(tmp_path / "r.jsonl")
    ck.open_for_run(MANIFEST)
    ck.append(rec("a"))
    assert ck.open_for_run({**MANIFEST, "git": "def"}).completed_ids() == {"a"}


def test_legacy_checkpoint_requires_explicit_adoption(tmp_path):
    p = tmp_path / "old.jsonl"
    old = [rec("a"), {"id": "b", "passed": False, "flags": ["llm_error"]}, {"id": "c", "passed": True, "flags": []}]
    p.write_text("\n".join(json.dumps({k: v for k, v in r.items() if k != "status"}) for r in old) + "\n")
    ck = Checkpoint(p)
    with pytest.raises(IncompatibleCheckpoint, match="--adopt-legacy"):
        ck.open_for_run(MANIFEST)
    s = ck.open_for_run(MANIFEST, adopt_legacy=True)
    assert s.completed_ids() == {"a", "c"} and s.records["b"]["status"] == "error"  # provider failure is not a result
    assert s.manifest["adopted_legacy"] is True
    assert ck.open_for_run(MANIFEST).completed_ids() == {"a", "c"}  # now a normal compatible checkpoint


def test_fresh_backs_up_instead_of_deleting(tmp_path):
    ck = Checkpoint(tmp_path / "r.jsonl")
    ck.open_for_run(MANIFEST)
    ck.append(rec("a"))
    assert ck.open_for_run(MANIFEST, fresh=True).completed_ids() == set()
    assert len(list(tmp_path.glob("*.bak"))) == 1


def test_invalid_records_are_refused_and_status_is_derived():
    with pytest.raises(ValueError):
        Checkpoint(Path("x")).append({"id": "a"})
    assert with_status({"id": "a", "passed": False, "flags": ["llm_error"]})["status"] == "error"


def test_hash_tree_ignores_line_endings(tmp_path):
    (tmp_path / "a.py").write_bytes(b"x = 1\r\ny = 2\r\n")
    h1 = hash_tree(tmp_path)
    (tmp_path / "a.py").write_bytes(b"x = 1\ny = 2\n")
    assert hash_tree(tmp_path) == h1
    (tmp_path / "a.py").write_bytes(b"x = 1\ny = 3\n")
    assert hash_tree(tmp_path) != h1


def test_runner_batches_resumes_and_only_reports_when_complete():
    """End-to-end through evals.run with the deterministic mock: interrupted batch -> resume -> validated full run."""
    results = BACKEND / "evals" / "results"
    out = results / "ckpt-e2e.json"
    ckpt = results / "ckpt-e2e.partial.jsonl"
    for f in (out, ckpt):
        f.unlink(missing_ok=True)
    cmd = [sys.executable, "-m", "evals.run", "--tag", "ckpt-e2e", "--limit", "6", "--no-report"]
    try:
        first = subprocess.run([*cmd, "--max-cases", "4"], cwd=BACKEND, capture_output=True, text=True, timeout=300, env=ENV)
        assert first.returncode == 3 and "INCOMPLETE" in first.stderr and not out.exists()
        assert len(Checkpoint(ckpt).load().completed_ids()) == 4
        second = subprocess.run(cmd, cwd=BACKEND, capture_output=True, text=True, timeout=300, env=ENV)
        assert second.returncode == 0, second.stderr
        assert "4/6 cases already completed" in second.stderr
        data = json.loads(out.read_text())
        assert data["meta"]["complete"] is True and len(data["cases"]) == 6 and data["summary"]["cases"] == 6
        assert len({c["id"] for c in data["cases"]}) == 6 and not ckpt.exists()
    finally:
        for f in (out, ckpt):
            f.unlink(missing_ok=True)
