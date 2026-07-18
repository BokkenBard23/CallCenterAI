---
type: Architecture
title: Backend Architecture
description: Detailed backend architecture covering 12 API routers, 28+ service modules, multi-provider LLM orchestration, SQLite persistence, FRIDA+FAISS search, and SmartLogger integration.
tags: [backend, fastapi, python, llm, search, embeddings, smartlogger]
resource: /backend/
---

# Backend Architecture

The CallCenterAI backend is a **FastAPI** application with 12 API routers, 28+ service modules, and a SQLite database designed for PostgreSQL migration. It orchestrates call transcript analysis, dictionary management, LLM-powered insights, vector search, and PII masking.

## API Routers (12)

| Router | Endpoints | Purpose |
|--------|-----------|---------|
| **upload** | POST /upload, POST /upload-batch | File ingestion (RTF/XML) |
| **analysis** | POST /analyze, GET /status/:id | Single and batch analysis triggers |
| **dictionary** | CRUD operations | Dictionary management (import, export, search) |
| **embeddings** | POST /embed, GET /search | FRIDA embedding generation and FAISS search |
| **mining** | POST /mining/index, POST /mining/find_similar, POST /mining/find_fn, POST /mining/audit, GET /mining/status/:id | Offline corpus mining (indexing, false negatives, similar dialogues, LLM audit) |
| **rag** | POST /rag-query | RAG queries via Beeline AI API |
| **pii** | POST /mask, POST /redact | PII masking with Presidio |
| **export** | GET /export/:id | Result export in various formats |
| **health** | GET /health, GET /ready | Health and readiness checks |
| **providers** | GET /providers, POST /test/:name | LLM provider status and connectivity |
| **batch** | POST /batch, GET /batch/:id | Batch processing management |
| **feedback** | POST /feedback | User feedback collection |

## Service Architecture

The backend follows a **router → service → store** layered architecture:

### Core Services

| Service | Location | Purpose |
|---------|----------|---------|
| **Transcript Parser** | `backend/app/services/` | RTF and XML parsing, speaker turn extraction |
| **SmartLogger Wrapper** | `backend/app/services/` | Wraps `Transcrib/smartlogger/` matching engine |
| **Morphological Matcher** | `backend/app/services/` | pymorphy3-based stem/lemma matching |
| **DisplayToken Builder** | `backend/app/services/` | Token assembly (WORD/PHRASE/LEXEME/BRACKET) |
| **LLM Orchestrator** | `backend/app/services/` | Multi-provider routing and parallel execution |

### LLM Provider Implementations

| Provider | Service | Transport |
|----------|---------|-----------|
| **Ollama** | Local model hosting | HTTP (localhost:11434) |
| **YandexGPT** | Yandex Cloud AI | gRPC/REST |
| **GigaChat** | Sber AI | REST (Russian compliance) |
| **Beeline AI** | Internal corporate API | REST via MCP server (`pipeline/middleware/rag_server.py`) |

**Qwen3.6-27B Dense** (`qwen36_fast`) is now the primary LLM for restructuring tasks, configured with `max_tokens=32768` and anti-loop protection. Concurrency limits are dynamically fetched from Beeline AI's `/me/limits` API at startup (`backend/app/services/llm_limits.py`).

### Vision Analysis

`backend/app/services/vision_analysis.py` provides multimodal LLM screenshot analysis for UI quality assurance:

- **Fallback chain**: `gpt-5.4` (primary, 100% accuracy) → `qwen-medium-dense` (fastest) → `qwen-medium` (Beeline infra guaranteed)
- **Batch mode**: Parallel screenshot analysis with `asyncio.Semaphore` respecting per-model concurrency limits
- **Vision Gate**: Automated UI invariant checking — screenshots are analyzed against design specs, defects are logged, and fixes are verified before pipeline progression

### Analysis Services

| Service | Purpose |
|---------|---------|
| **Sentiment Analysis** | Call sentiment scoring |
| **Conflict Detection** | Agent-client conflict identification |
| **Profanity Filter** | Language violation detection |
| **Topic Classifier** | Call topic categorization |
| **Quality Scorer** | Agent performance scoring rubric |

### Search and Storage

| Service | Purpose |
|---------|---------|
| **FRIDA Embeddings** | Text-to-vector embedding generation |
| **FAISS Index** | Vector similarity search |
| **Hybrid Search** | Combines vector + keyword search |
| **PII Masking** | Presidio + 7 custom Russian-language NER recognizers |
| **SQLite Store** | Session, batch, and mining job persistence |
| **Vision Analysis** | Multimodal LLM screenshot analysis with fallback chain |
| **Dict Mining** | Offline corpus mining (false negatives, similar dialogues, audit) |
| **LLM Limits** | Dynamic concurrency limit discovery from Beeline AI API |

## Database Schema (SQLite)

| Table | Purpose |
|-------|---------|
| **sessions** | Call analysis sessions (upload → results) |
| **batches** | Batch processing jobs |
| **mining_jobs** | Dictionary mining operation tracking |
| **mining_corpus** | Mining corpus entries |
| **mining_fn_candidates** | False negative candidates |
| **mining_audit_results** | Mining audit result records |
| **mining_checkpoints** | Mining operation state checkpoints |

The schema uses proper foreign keys and typed columns, designed for a smooth migration path to PostgreSQL.

## SmartLogger Integration

The `Transcrib/smartlogger/` package is the **authoritative matching engine**. Key modules:

| Module | Purpose |
|--------|---------|
| `config.py` | Configuration management |
| `dictionary.py` | Dictionary loading and CRUD |
| `matcher.py` | Core morphological matching algorithm |
| `metrics.py` | Matching quality metrics |
| `reporter.py` | Result report generation |
| `rtf_parser.py` | RTF dialogue parsing |
| `tokenizer.py` | Text tokenization |
| `validator.py` | Dictionary validation |
| `xml_exporter.py` | XML export with SmartLogger round-trip |

The backend imports SmartLogger as a **read-only dependency** — modifications happen in the `Transcrib/` directory through the iterative build pipeline (v4-v7).

## MCP Integration

The backend connects to external MCP servers:

- **Beeline AI RAG** — `pipeline/middleware/rag_server.py` wraps the Beeline AI API (`https://api.ai.beeline.ru/api/v2`) with SSE transport, exposing a `rag_query` tool with configurable knowledge base
- **Figma MCP** — Design system and visual asset access
- **Chrome DevTools MCP** — Automated screenshot and DOM inspection
- **Sequential Thinking MCP** — Chain-of-thought reasoning for complex analysis

## Configuration

Backend configuration is loaded from environment variables and `backend/.env`:

- **LLM provider endpoints and keys**
- **Database path** (default: `data/sessions.db`)
- **Embedding model settings**
- **PII masking rules**
- **RAG knowledge base code** (`RAG_KB_CODE`)

Environment variables are never committed. See `backend/.env` patterns and `npmrc.example` for configuration structure.

## Source Map

| Area | Path |
|------|------|
| Main entry | `backend/app/main.py` |
| Routers | `backend/app/routers/` |
| Services | `backend/app/services/` |
| Schemas | `backend/app/schemas/` |
| SmartLogger | `Transcrib/smartlogger/` |
| RAG MCP server | `pipeline/middleware/rag_server.py` |
| Tests | `backend/tests/` |
