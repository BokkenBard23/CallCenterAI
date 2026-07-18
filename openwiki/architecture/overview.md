---
type: Architecture
title: System Architecture Overview
description: High-level architecture of the CallCenterAI call center analytics platform, covering component relationships, data flows, technology layers, and deployment topology.
tags: [architecture, system-design, call-center, ai, analytics, beeline]
resource: /ARCHITECTURE.md
---

# System Architecture Overview

CallCenterAI follows a **two-tier client-server architecture** with a React SPA frontend communicating with a FastAPI backend through a REST API. The system is designed around the analysis of call center transcripts, using a combination of rule-based morphological matching and LLM-powered analysis.

## Component Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Nginx Reverse Proxy                     │
│                    (port 80, production)                     │
└──────────────────────────┬──────────────────────────────────┘
                           │
              ┌────────────┴────────────┐
              │                         │
    /api/* ──►│                         │◄── /* (static)
              │                         │
   ┌──────────▼──────────┐   ┌─────────▼─────────┐
   │   FastAPI Backend   │   │   Vite Dev Server  │
   │   (port 8000)       │   │   (port 5173)      │
   │                     │   │   React SPA        │
   │   12 Routers        │   │   7 Routes         │
   │   28+ Services      │   │   60+ Components   │
   │   SQLite + FAISS    │   │                    │
   └──────────┬──────────┘   └────────────────────┘
              │
              │  LLM calls
              ▼
   ┌──────────────────────┐
   │   LLM Providers       │
   │  Ollama | YandexGPT  │
   │  GigaChat | Beeline  │
   └──────────────────────┘
```

## Data Flow

The core data flow moves through four stages:

1. **Ingestion** — Call transcripts (RTF/XML) are uploaded and parsed by the backend. The RTF parser extracts dialogue turns (speaker labels, text, timestamps). XML dictionaries are parsed for keyword entries with morphological attributes.

2. **Matching** — The SmartLogger engine (`Transcrib/smartlogger/`) performs morphological matching against keyword dictionaries using pymorphy3. This produces DisplayToken objects (WORD/PHRASE/LEXEME/BRACKET types) with channel attribution (OPERATOR/CLIENT/ANY) and depth levels.

3. **Analysis** — LLM providers run sentiment analysis, conflict detection, profanity filtering, and topic classification. Results are merged with rule-based matching tokens.

4. **Presentation** — The frontend renders matched dialogues with color-coded highlights, quality scores, and AI-generated summaries.

## Technology Layers

| Layer | Technologies | Purpose |
|-------|-------------|---------|
| **Presentation** | React 18, `@beeline/design-system-react` 2.5 | UI rendering, theme management |
| **Routing** | `react-router-dom` v7 | Client-side navigation |
| **State** | React Context + reducers | Session, view mode, hover state |
| **HTTP Client** | Custom `api/client.ts` | Backend communication |
| **API** | FastAPI, Pydantic | REST endpoints |
| **Matching** | SmartLogger (pymorphy3) | Morphological keyword matching |
| **Embeddings** | FRIDA + FAISS | Vector similarity search |
| **LLM** | Multi-provider orchestrator | Sentiment, conflict, topic analysis |
| **PII** | Presidio + custom NER | Personal data masking |
| **Storage** | SQLite (sessions, batches, mining_jobs) | Persistence with PG migration path |
| **Reverse Proxy** | Nginx | Production routing |

## Key Architectural Decisions

### SmartLogger as Core Engine

The `Transcrib/smartlogger/` package is the authoritative matching engine. It was developed as a standalone Python prototype before the current FastAPI backend was built. The backend imports and wraps SmartLogger rather than reimplementing its logic. This preserves the morphological matching, aspectual pair handling, and dictionary CRUD that were refined through v4-v7 build iterations.

### Multi-Provider LLM Orchestration

The system supports **four LLM providers** simultaneously: Ollama (local), YandexGPT, GigaChat, and Beeline AI. The orchestrator (`backend/app/services/`) routes different analysis types to different providers based on configuration, supports parallel execution for batch operations, and falls back gracefully when providers are unavailable.

### No URL-Based Session IDs

A deliberate frontend decision: the `/results` route gets its `sessionId` from `AnalysisContext` (React Context), not from URL parameters. This keeps the URL clean and centralizes session state management.

### SQLite with PostgreSQL Migration Path

The database uses SQLite for development and single-node deployments. The schema is designed with PostgreSQL compatibility in mind (proper foreign keys, typed columns) for eventual production migration.

### Pipeline-Driven Development

The project uses an AI agent pipeline (orchestrator + stage agents) tracked by `pipeline-state.yaml` in `docs/specs/`. This enables automated design-implement-review-test cycles with quality gates at each stage.

## Source Map

| Area | Key Files |
|------|-----------|
| Architecture docs | `ARCHITECTURE.md`, `DOMAIN_LOGIC.md` |
| Project map | `PROJECT_MAP.md` |
| Pipeline state | `docs/specs/pipeline-state.yaml` |
| Backlog | `docs/specs/backlog.json` |
| Roadmap | `TODO_AND_ROADMAP.md` |
| Docker | `docker-compose.yml`, `Dockerfile.backend`, `Dockerfile.frontend` |
| Nginx | `nginx.conf` |
