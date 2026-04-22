# TaskMate Homework

This repository contains a lightweight Cloudflare Worker MVP for a conversational task assistant.

## Public Demo

- Live URL: [taskmate-homework.keximing-taskmate.workers.dev](https://taskmate-homework.keximing-taskmate.workers.dev/)

## What is already implemented

- `app/` layered structure with `routes`, `core`, `providers`, `services`, and `ui`
- Worker entry scaffold in [`app/entry.py`](/Users/kkk/kkk-magic/homework/app/entry.py)
- Persistent local repository using the D1 schema and SQLite-backed storage
- Minimal chat UI with task sidebar, file workspace, upload flow, and research output area
- D1-compatible schema in [`migrations/001_init.sql`](/Users/kkk/kkk-magic/homework/migrations/001_init.sql)
- Intent routing, task tool protocol, context window manager, and task CRUD repository
- File upload, Mistral OCR PDF parsing, DOCX/text extraction, chunking, local vector search, and file deletion
- Queue-backed research job submission plus polling with markdown report output
- Serper and OpenRouter HTTP client wiring with graceful fallback when secrets are missing
- Profile completion gating when name or email is missing
- Assistant nickname persistence and frontend display sync
- Task details parsing, persistence, and sidebar rendering
- Dynamic research planner with step-by-step progress output and structured markdown reports
- File rename support plus source citations in file QA answers
- Vectorized long-term chat memory stored alongside file vectors with filtered retrieval
- Remote embedding provider support with local fallback when embedding secrets are absent
- Image OCR ingestion for `.png/.jpg/.jpeg` files, reusing the same RAG pipeline
- Simplified ToT-style comparison section in research reports

## Project structure

```text
app/
  entry.py
  routes/
  core/
  providers/
  services/
  ui/
migrations/
docs/
tests/
```

## Local development

1. Install Python dependencies such as `pytest` plus the Cloudflare Python Worker tooling you plan to use.
2. Copy `.dev.vars.example` to `.dev.vars` and fill in the secrets.
3. Apply the D1 migration with Wrangler when the database is created.
4. Start local Worker development with your preferred Python Worker command, for example `python -m pywrangler dev`.
5. Local demo state is persisted under `.taskmate/`.

## Cloudflare deployment prep

1. Create the D1 database: `npx wrangler d1 create taskmate-homework-db`
2. Put the returned `database_id` and `preview_database_id` into [`wrangler.toml`](/Users/kkk/kkk-magic/homework/wrangler.toml:1)
3. Create the R2 buckets:
   `npx wrangler r2 bucket create taskmate-homework-files`
   `npx wrangler r2 bucket create taskmate-homework-files-dev`
4. Set secrets:
   `npx wrangler secret put OPENROUTER_API_KEY`
   `npx wrangler secret put MISTRAL_API_KEY`
   `npx wrangler secret put SERPER_API_KEY`
   `npx wrangler secret put QDRANT_API_KEY`
5. Create the research queue:
   `npx wrangler queues create taskmate-research-jobs`
6. Apply the schema:
   `npx wrangler d1 execute taskmate-homework-db --file migrations/001_init.sql --remote`
7. Deploy:
   `npx wrangler deploy`

## Runtime adapters

- Local development: SQLite + local R2 adapter + local Qdrant-style JSON store
- Cloudflare runtime with bindings: D1 repository + R2 bucket adapter + Qdrant Cloud REST adapter
- The switch happens automatically in [`app/entry.py`](/Users/kkk/kkk-magic/homework/app/entry.py:1) based on available Worker bindings and environment variables

## Verification

- Syntax check: `python3 -m py_compile $(find app tests -name '*.py')`
- Tests: `python3 -m pytest`

## Demo Walkthrough

1. Open the public URL and provide your name and email when prompted.
2. Optionally rename the assistant with a message like `叫你阿塔`.
3. Create a task with details, for example:
   `帮我创建一个"简历优化"任务，要求突出 Agent、RAG 和 Cloudflare Worker 项目经验，下周五前完成，高优先级`
4. Upload a text, PDF, DOCX, or image file and ask a question against the selected file context.
5. Trigger research mode with a topic such as:
   `帮我调研 Cloudflare Worker 上做 RAG 的轻量实现方案`

## Current Limits

- Deep research now uses Cloudflare Queue backed background execution plus D1-persisted step state, but still keeps a single-worker producer/consumer topology for simplicity.
- The embedding layer now supports a real remote API, but local development still falls back to deterministic vectors when embedding credentials are absent.
- File management currently supports upload, list, select, rename, and delete.
- Image OCR depends on `MISTRAL_API_KEY`; without it, image parsing will fail fast with a clear error.

## Deployment notes

- Standard Worker is enough for chat, task CRUD, and lightweight search.
- Research mode now runs through Cloudflare Queues and D1-persisted job state instead of in-process background tasks.
- RAG must keep strict `user_id` and optional `file_id` metadata filters in Qdrant.
- The current repo uses local adapters for R2/Qdrant behavior during development; swap those adapters to Cloudflare R2 and Qdrant Cloud bindings for production.
- When `DB` and `FILES_BUCKET` bindings are present, the app now uses the real Cloudflare adapters automatically.
