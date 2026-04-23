# Implementation Notes

## Current state

The repository now has a minimal but coherent MVP scaffold:

- Worker entry and route dispatch
- D1-schema-compatible SQLite persistence under `.taskmate/taskmate.db`
- Conversation agent with intent routing
- Summary plus recent-buffer context management
- Natural-language task CRUD protocol and persistent repository
- Minimal UI for chat, tasks, files, upload status, and research output
- D1 schema migration and environment variable examples
- Profile completion gating before normal task/search/research flows when user info is incomplete
- Assistant nickname sync between persistence layer and frontend UI
- Task details extraction and rendering in the workspace sidebar
- Queue-backed research execution with running progress snapshots, persisted step state, and structured final reports
- File rename support with synchronized Qdrant payload metadata updates
- Semantic long-term memory retrieval based on stored conversation vectors
- Image OCR support for `.png/.jpg/.jpeg` routed through the same OCR and vectorization flow as PDFs
- Simplified ToT-style recommendation section in generated research reports

## Cloudflare adapters

The code now supports two runtime modes behind the same service interfaces:

- local mode:
  - `SQLiteAppRepository`
  - local filesystem-backed R2 adapter
  - local JSON-backed Qdrant-style store
- Cloudflare mode:
  - `CloudflareD1Repository`
  - `CloudflareR2FileStore`
  - Qdrant Cloud REST-backed `QdrantStore`

`app/entry.py` selects the runtime path automatically based on whether `env.DB`, `env.FILES_BUCKET`, and `QDRANT_URL` are available.

## Architecture Diagram

```mermaid
flowchart LR
  Browser["Browser UI"] --> Worker["Cloudflare Worker API"]
  Worker --> Agent["Agent / Intent Router"]
  Agent --> Repo["SQLite local adapter<br/>D1-compatible schema"]
  Agent --> Search["Serper search service"]
  Agent --> Research["Queue-backed research service"]
  Agent --> Files["File upload + RAG service"]
  Files --> R2["Local R2 adapter"]
  Files --> Qdrant["Local Qdrant-style vector store"]
```

## Worker Strategy

- Standard Worker remains the recommended deployment target for the MVP because chat, task CRUD, lightweight search, and file upload are all short-lived requests.
- Deep research should not stay inside a single request. The current code now uses "submit + queue + poll" so the UI can survive long-running research without blocking the request.
- Unbound Worker is not necessary for the MVP, but it can be reconsidered if the product later centralizes heavier fetch-and-summarize workloads inside one runtime instead of queueing them.

## Deployment steps

1. create D1 and R2 resources
2. bind them in `wrangler.toml`
3. set OpenRouter, Mistral OCR, Serper, and Qdrant secrets
4. create the Cloudflare Queue used by research jobs
5. run the initial D1 schema apply command
6. deploy with Wrangler

This keeps the code path identical between preview and production, with only the bindings and secrets changing.

## Context window strategy

The current `ConversationContextManager` implements the first version of the planned sliding-window design:

- Keep a recent raw-message buffer
- Compact older messages into a stored summary
- Refresh the summary once the message count crosses a threshold

This matches the TODO constraint that model context must not grow forever.

## Research design

Research mode is now implemented as a durable queue-backed flow:

1. Detect deep-research intent
2. Build a small plan with 3 to 5 sub-steps
3. Persist `research_jobs` and `research_job_states`
4. Send the job into Cloudflare Queue (`taskmate-research-jobs`, binding `RESEARCH_QUEUE`)
5. Let the queue consumer execute one sub-step at a time and write progress back to D1

Video and other deferred media ingest messages go to a **separate** queue (`taskmate-media-ingest`, binding `MEDIA_INGEST_QUEUE`) so backlog or failures on research jobs do not block media processing, and operators can clear one queue independently.
6. Poll the job state from the UI and render the final markdown report

## Queue and Durable Object assessment

- Cloudflare Queues is now the selected execution model because Free-plan Workflows limits are too restrictive for multi-step research jobs.
- Durable Objects still becomes attractive if research jobs later need shared mutable coordination, streamed progress, or per-job event fan-out.
- The current implementation keeps the topology simple: one Worker acts as both producer and consumer, while D1 stores durable state and the UI only polls persisted progress.

## Sub-agent planning

The project keeps sub-agent planning at the logical level instead of introducing real distributed agents:

1. detect that the question is research-heavy
2. split it into 3 to 5 sub-questions
3. search and fetch evidence per sub-question
4. consolidate everything into one markdown report

This preserves the architecture signal from the original design while keeping the runtime simple enough for a Worker-hosted MVP.

## RAG design

The current repository includes placeholder services for:

- file parsing
- embedding generation
- local Qdrant-style storage
- retrieval assembly

The upload flow now:

1. validates file size and suffix
2. stores the raw file through the R2 abstraction
3. parses text
4. chunks text
5. embeds chunks
6. writes vectors with `user_id`, `file_id`, `chunk_index`, and `source_type`
7. retrieves by `user_id` and optional `file_id`

The next production step is to replace the local adapters with real R2 and Qdrant Cloud requests while preserving the same metadata filters.

## Planned next slice

1. Add stronger source attribution formatting inside generated report paragraphs, not only as a trailing references section
2. Extend memory retrieval with stronger de-duplication and recency balancing
3. Add richer multimodal ingestion on top of the current text-first RAG pipeline

## Challenges and solutions

- Worker runtime constraints: long research chains are moved behind Cloudflare Queue consumer execution and D1-persisted polling instead of in-process background tasks.
- Context growth: the context manager keeps a summary plus a bounded recent-message buffer to stop prompt size from growing forever.
- Local development without cloud credentials: the code uses local adapters that preserve the same interfaces and metadata contracts as the planned cloud services.
- RAG isolation: every stored chunk carries `user_id` and optional `file_id` filters so retrieval never falls back to broad unscoped search.
