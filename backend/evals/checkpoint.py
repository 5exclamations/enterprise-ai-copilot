"""Crash-safe, resumable checkpoint store for long evaluation runs.

File layout (JSON lines, append-only):

    {"manifest": {... fingerprint inputs, code revision, created ...}}      <- always line 1
    {"id": "doc-01", "status": "ok",    "attempt": 1, ...case result...}
    {"id": "calc-03", "status": "error", "attempt": 1, ...}                 <- infra failure (e.g. timeout)
    {"id": "calc-03", "status": "ok",    "attempt": 2, ...}                 <- a later retry supersedes it

* Each finished case is appended and fsync'd immediately, so an interruption loses at most the case in flight.
* A torn (partially written) last line is ignored, never fatal.
* The manifest carries a *fingerprint* of everything that changes what the numbers mean (models, embedding
  settings, prompt, dataset, code). Resuming with a different fingerprint is refused (`IncompatibleCheckpoint`);
  the caller should start a separate run (different tag) instead of mixing results.
* Only `status == "ok"` records count as completed. `error` records (provider timeouts / unavailable) are kept
  on disk for the audit trail but are retried on resume.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

FINGERPRINT_KEYS = ("provider", "model", "embedder", "embedding_dim", "embedding_query_prefix", "embedding_document_prefix",
                    "ollama_num_ctx", "retrieval_top_k", "max_agent_steps", "prompt_sha", "dataset_sha", "code_sha")


class IncompatibleCheckpoint(RuntimeError):
    pass


def sha256_text(*parts: str | bytes) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p if isinstance(p, bytes) else p.encode())
    return h.hexdigest()


def hash_tree(root: Path, pattern: str = "**/*.py") -> str:
    """Hash source files with normalised line endings (a Windows checkout must equal a Linux one)."""
    h = hashlib.sha256()
    for f in sorted(root.glob(pattern)):
        if "__pycache__" in f.parts:
            continue
        h.update(f.relative_to(root).as_posix().encode())
        h.update(f.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()


def fingerprint(manifest: dict) -> str:
    return sha256_text(json.dumps({k: manifest.get(k) for k in FINGERPRINT_KEYS}, sort_keys=True))


def with_status(rec: dict) -> dict:
    """Records written before `status` existed: a provider failure (llm_error flag) is an error, anything else ok."""
    if isinstance(rec, dict) and "status" not in rec and "id" in rec and "passed" in rec:
        rec = {**rec, "status": "error" if "llm_error" in (rec.get("flags") or []) else "ok"}
    return rec


def is_valid_record(rec: dict) -> bool:
    return isinstance(rec, dict) and isinstance(rec.get("id"), str) and rec.get("status") in ("ok", "error") and "passed" in rec


@dataclass
class Loaded:
    manifest: dict | None
    records: dict[str, dict]  # latest valid record per case id
    errors: list[dict]  # every error record ever written (audit trail)
    torn_lines: int = 0

    def completed_ids(self) -> set[str]:
        return {i for i, r in self.records.items() if r["status"] == "ok"}


class Checkpoint:
    def __init__(self, path: Path):
        self.path = Path(path)

    # ------------------------------------------------------------------ reading
    def load(self) -> Loaded:
        if not self.path.exists():
            return Loaded(None, {}, [])
        manifest, records, errors, torn = None, {}, [], 0
        for n, line in enumerate(self.path.read_text(encoding="utf-8").splitlines()):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                torn += 1  # an interrupted write; the case will simply be re-run
                continue
            obj = with_status(obj)
            if n == 0 and "manifest" in obj:
                manifest = obj["manifest"]
            elif is_valid_record(obj):
                if obj["status"] == "error":
                    errors.append(obj)
                    records.setdefault(obj["id"], obj)  # visible, but never overrides an ok record
                else:
                    records[obj["id"]] = obj  # later ok record supersedes earlier error or ok
            else:
                torn += 1
        return Loaded(manifest, records, errors, torn)

    # ------------------------------------------------------------------ writing
    def start(self, manifest: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        manifest = {**manifest, "fingerprint": fingerprint(manifest)}
        self._write_all([json.dumps({"manifest": manifest})])

    def append(self, record: dict) -> None:
        if not is_valid_record(record):
            raise ValueError("refusing to checkpoint an invalid record")
        with self.path.open("ab+") as raw:  # a torn previous write leaves no newline; never glue onto it
            raw.seek(0, os.SEEK_END)
            needs_break = raw.tell() > 0 and (raw.seek(-1, os.SEEK_END), raw.read(1))[1] != b"\n"
        with self.path.open("a", encoding="utf-8") as fh:
            if needs_break:
                fh.write("\n")
            fh.write(json.dumps(record, default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def _write_all(self, lines: list[str]) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)  # atomic on POSIX and Windows

    # ------------------------------------------------------------------ session
    def open_for_run(self, manifest: dict, *, adopt_legacy: bool = False, fresh: bool = False,
                     accept_code_change: bool = False) -> Loaded:
        """Return prior state for a compatible checkpoint, or initialise a new one.

        Raises IncompatibleCheckpoint if an existing checkpoint was produced under a different configuration.
        """
        want = fingerprint(manifest)
        if fresh and self.path.exists():
            self.path.rename(self.path.with_suffix(f".{sha256_text(str(os.times()))[:8]}.bak"))
        loaded = self.load()
        if not self.path.exists() or (loaded.manifest is None and not loaded.records and not loaded.errors):
            self.start(manifest)
            return self.load()
        if loaded.manifest is None:  # file from before manifests existed
            if not adopt_legacy:
                raise IncompatibleCheckpoint(
                    f"{self.path.name} has no manifest (written by an older runner). Re-run with --adopt-legacy to adopt its "
                    "records under the current configuration (only do this if the run really used it), or use --fresh.")
            records = [r for r in loaded.records.values()] + loaded.errors
            seen = set()
            lines = [json.dumps({"manifest": {**manifest, "fingerprint": want, "adopted_legacy": True}})]
            for r in records:
                key = (r["id"], r["status"], json.dumps(r.get("answer")))
                if key not in seen:
                    seen.add(key)
                    lines.append(json.dumps(r, default=str))
            self._write_all(lines)
            return self.load()
        if loaded.manifest.get("fingerprint") != want:
            diff = [k for k in FINGERPRINT_KEYS if loaded.manifest.get(k) != manifest.get(k)]
            if diff == ["code_sha"] and accept_code_change:
                # Explicit, audited override: the operator asserts the code change does not affect results
                # (e.g. a transport retry). Everything else (models, prompt, dataset, embeddings) still must match.
                history = [*loaded.manifest.get("code_sha_history", []), {"code_sha": loaded.manifest.get("code_sha"),
                                                                           "git": loaded.manifest.get("git")}]
                new = {**loaded.manifest, "code_sha": manifest["code_sha"], "git": manifest.get("git"), "code_sha_history": history}
                new["fingerprint"] = fingerprint(new)
                body = self.path.read_text(encoding="utf-8").splitlines()[1:]
                self._write_all([json.dumps({"manifest": new}), *body])
                return self.load()
            raise IncompatibleCheckpoint(
                f"checkpoint {self.path.name} was made with a different configuration (changed: {', '.join(diff) or 'unknown'}). "
                "Use a different --tag for a separate run, or --fresh to discard it.")
        return loaded
