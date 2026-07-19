---
type: Quickstart
title: CallCenterAI — Quickstart
description: Entry point for the CallCenterAI code wiki. Covers what the project is, how to run it locally, technology overview, and links to detailed documentation sections.
tags: [quickstart, call-center, ai-analytics, beeline, call-transcripts]
---

# CallCenterAI — Quickstart

CallCenterAI is an **AI-powered call center analytics platform** built for the Beeline telecommunications group. It ingests call transcripts (RTF/XML), matches phrases against configurable keyword dictionaries using the SmartLogger morphological matching engine, runs LLM-powered sentiment and quality analysis, and provides a rich web UI for exploration, dictionary management, and deep mining of agent-client dialogues.

## What It Does

- **Upload and analyze** call recording transcripts (RTF/XML formats)
- **Match phrases** against keyword dictionaries using morphological search (pymorphy3)
- **Run AI analysis** (sentiment, conflict detection, profanity filtering, topic classification) via multiple LLM providers
- **Manage keyword dictionaries** with a full CRUD editor, AI-assisted suggestions, and XML round-trip export
- **Mine dialogues** for false negatives, similar patterns, and improvement candidates
- **Search** across call corpora using hybrid vector (FRIDA + FAISS) and keyword search
- **Mask PII** using Presidio with custom Russian-language NER recognizers

## Quick Start

### Prerequisites

- **Node.js** 20+ (required for `@beeline/*` design system dependencies)
- **Python** 3.11+ (backend)
- **npm** access to `@beeline/*` private registry (see `npmrc.example`)
- Environment variables for LLM providers (Ollama, YandexGPT, GigaChat, Beeline AI)

### One-Click Launch (Windows)

```
.\start.bat
```

This starts the backend (port 8000), frontend (port 5173), runs health checks, and opens the browser.

### Manual Launch

```bash
# Backend
cd backend
python -m venv .venv && .venv\Scripts\activate
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# Frontend (separate terminal)
npm install
npm run dev
```

### Docker Deployment

```bash
docker-compose up
```

Nginx reverse proxy on port 80 routes `/api` to the backend (8000) and everything else to the frontend.

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18 + TypeScript + Vite 7 |
| UI | `@beeline/design-system-react` 2.5 (47 inventoried components) |
| Backend | FastAPI + Python 3.11 |
| Database | SQLite (with PostgreSQL migration path) |
| Search | FRIDA embeddings + FAISS vector index + hybrid keyword |
| LLM | Multi-provider: Ollama, YandexGPT, GigaChat, Beeline AI (Qwen3.6-27B primary) |
| Matching | SmartLogger (morphological, pymorphy3) |
| PII | Presidio + 7 custom Russian-language NER recognizers |
| Testing | Vitest (frontend) + pytest (backend) |

## Documentation Sections

- **[Architecture Overview](architecture/overview.md)** — System design, component relationships, data flow
- **[Frontend Architecture](architecture/frontend.md)** — Routing, components, state management, design system integration
- **[Backend Architecture](architecture/backend.md)** — API routers, services, LLM orchestration, persistence
- **[Key Workflows](workflows.md)** — Upload-to-analysis pipeline, dictionary mining, batch processing
- **[Domain Concepts](domain.md)** — SmartLogger matching, morphological search, PII masking, quality scoring
- **[Operations](operations.md)** — Deployment, CI/CD, environment config, scripts
- **[Testing](testing.md)** — Test strategy, quality gates, coverage, vision auditing

## Project Status

- **44/53 backlog items completed** (9 pending, all low priority)
- **565 frontend tests** passing
- **1976 backend tests** passing
- **Lighthouse score**: 92+
- Pipeline-driven development with AI agent orchestration via `pipeline-state.yaml`

## Backlog

The following areas are tracked but not yet fully implemented:

| Area | Source | Status |
|------|--------|--------|
| Visual `is_exact` highlight verification | `TODO_AND_ROADMAP.md` IP-1.5 | Medium priority |
| Runtime `attribute_tree` filtering | `TODO_AND_ROADMAP.md` IP-5.1 | Low priority |
| Dictionary Mining v2 (7 items) | `docs/specs/backlog.json` DM-3.0–3.6 | All low priority |
| Live transcription (SIPREC/WebSocket) | `TODO_AND_ROADMAP.md` Phase 7 | Deferred, 10+ days |
| Agent Assist / regex auto-routing | `TODO_AND_ROADMAP.md` Phase 7 | Deferred |
| Plugin system (CRM/Salesforce) | `TODO_AND_ROADMAP.md` Phase 7 | Deferred |
