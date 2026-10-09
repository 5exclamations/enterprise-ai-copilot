#!/usr/bin/env bash
# Resumable real-model evaluation: qwen2.5:3b + nomic-embed-text via a local Ollama server.
# Runs in small batches (default 10 cases) so an interrupted session loses at most the case in flight.
# Usage: scripts/eval_ollama.sh [extra evals.run args, e.g. --adopt-legacy]
set -u
cd "$(dirname "$0")/.."
export LLM_PROVIDER=ollama LLM_MODEL="${LLM_MODEL:-qwen2.5:3b}"
export EMBEDDING_PROVIDER=ollama EMBEDDING_MODEL="${EMBEDDING_MODEL:-nomic-embed-text}" EMBEDDING_DIM=768
export EMBEDDING_QUERY_PREFIX="search_query: " EMBEDDING_DOCUMENT_PREFIX="search_document: "
PY="${PYTHON:-.venv/Scripts/python}"; [ -x "$PY" ] || PY=.venv/bin/python
BATCH="${BATCH:-10}"
while true; do
  "$PY" -m evals.run --provider ollama --max-cases "$BATCH" "$@"
  rc=$?
  [ "$rc" -eq 3 ] || exit "$rc"   # 3 = incomplete: run another batch; anything else (0 done, 2 incompatible, ...) stops
  set -- "${@/--adopt-legacy/}"   # adoption only on the first batch
done
