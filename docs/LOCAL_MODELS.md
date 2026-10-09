# Running with local models (Ollama)

This project can run end-to-end on a local model with **no API key and no per-token cost**:
`LLM_PROVIDER=ollama` (chat + tool calling) and `EMBEDDING_PROVIDER=ollama` (neural embeddings).
The deterministic mock LLM + hashing embedder remain the default, and the whole test-suite and CI
gate still run on them - local models are an opt-in layer, never a requirement.

## Hardware this was developed and measured on

| Component | Value |
|---|---|
| CPU | Intel Core i3-6100 (2 cores / 4 threads, 3.7 GHz) |
| RAM | 7.9 GB (about 0.6 GB free with the desktop running) |
| GPU | NVIDIA GeForce GTX 745, **4 GB VRAM** (Maxwell, 2014) + Intel HD 530 |
| Disk | 20.9 GB free on C: |
| OS / tools | Windows 10 Pro, Python 3.12, Ollama 0.40.2, Git. No Node, no running Docker daemon |

This is a *small* machine, so the model choice below is about fitting, not about maximising quality.

## Model selection

| Role | Model | Size | Why |
|---|---|---|---|
| Chat + tool calling | `qwen2.5:3b` (Q4) | 1.9 GB on disk, ~2.2 GB loaded | Fits fully in 4 GB VRAM (`ollama ps` reports **100% GPU**), leaving room for the embedder. Has native tool-calling support in Ollama, which the agent needs. A 7-8B model (4.7+ GB) would not fit in VRAM and would spill to a 2-core CPU and 8 GB RAM - unusably slow and likely to swap. |
| Embeddings | `nomic-embed-text` | 274 MB, 768-d | Strong retrieval quality for its size, runs on the GPU alongside the chat model, 2048-token context (our chunks are ~900 chars). Needs task prefixes (`search_query: ` / `search_document: `), supported via `EMBEDDING_QUERY_PREFIX` / `EMBEDDING_DOCUMENT_PREFIX`. |

Alternatives considered: `qwen2.5:1.5b` / `llama3.2:1b` (faster but noticeably worse at choosing tools),
`all-minilm` (46 MB, 384-d, weaker retrieval), `mxbai-embed-large` / `bge-m3` (better but 670 MB-1.2 GB and 1024-d;
unnecessary for a 14-document corpus on this hardware).

## Setup

```bash
# 1. install Ollama (https://ollama.com), then
ollama pull qwen2.5:3b
ollama pull nomic-embed-text

# 2. configure (backend/.env or exported variables)
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5:3b
EMBEDDING_PROVIDER=ollama
EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_DIM=768
EMBEDDING_QUERY_PREFIX="search_query: "
EMBEDDING_DOCUMENT_PREFIX="search_document: "

# 3. migrate the schema (vector(256) -> vector(768) on Postgres) and re-embed
cd backend
alembic upgrade head
python -m app.reindex
```

On SQLite (the zero-dependency mode) vectors are stored as JSON, so no migration is needed - just reseed
(`python -m app.seed --reset`) or run `python -m app.reindex`.

Tuning knobs: `OLLAMA_BASE_URL`, `OLLAMA_NUM_CTX` (default 4096; lower it if VRAM is tight),
`OLLAMA_KEEP_ALIVE` (default `10m`), `OLLAMA_TIMEOUT_SECONDS` (default 300).

## Migrations and changing embedding models

Schema changes go through Alembic (`backend/migrations`), configured from `DATABASE_URL`:

| Revision | What it does |
|---|---|
| `0001` | Baseline schema (256-d embeddings, GIN full-text and HNSW vector indexes on Postgres). **Adopts** databases that were created before Alembic by `init_db()` without touching their data. |
| `0002` | Adds `chunks.embedding_model` so every vector records the model that produced it. Existing vectors are labelled `hashing-v1`. |
| `0003` | Resizes the pgvector column to `EMBEDDING_DIM` (clears vectors, rebuilds the HNSW index). No-op on SQLite and when the width already matches. Downgrade restores 256. |

Vectors from different models are **not comparable**, so the system never silently mixes them:
`update_document` only reuses embeddings produced by the *current* model, and `python -m app.reindex`
re-embeds every chunk that is missing a vector or was embedded by a different model (`--all` forces everything).

A unit test applies the migrations to a fresh SQLite file, asserts the result has **no drift from the SQLAlchemy models**,
round-trips `downgrade base` / `upgrade head`, and checks that a pre-Alembic database is adopted with its data intact.

## Evaluation with real models

See [REAL_MODEL_ANALYSIS.md](REAL_MODEL_ANALYSIS.md) (mock vs real, failure by failure), [EVAL_RESULTS_OLLAMA_QWEN2_5_3B_NOMIC_EMBED_TEXT.md](EVAL_RESULTS_OLLAMA_QWEN2_5_3B_NOMIC_EMBED_TEXT.md) (v2 report; v1 baseline is the `_V1_BASELINE` file)
(full 80-case agent run) and [RETRIEVAL_NOMIC_EMBED_TEXT.md](RETRIEVAL_NOMIC_EMBED_TEXT.md) /
[RETRIEVAL_HASHING_V1.md](RETRIEVAL_HASHING_V1.md) (retrieval ablation per embedder). Reproduce with:

```bash
python -m evals.run --retrieval-only                       # embedder ablation only (fast)
python -m evals.run --provider ollama --resume             # full agent run; checkpoints, resumable
```

Real-model runs write to their own files, so they never overwrite the deterministic baseline
(`docs/EVAL_RESULTS.md`, `evals/results/latest.json`) that the CI gate uses.
