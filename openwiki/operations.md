---
type: Operations
title: Operations and Deployment
description: Operations guide covering Docker deployment, Nginx configuration, environment variables, CI/CD scripts, pipeline state management, and local development setup.
tags: [operations, docker, deployment, nginx, ci-cd, scripts, environment]
resource: /docker-compose.yml
---

# Operations and Deployment

## Local Development

### Windows (One-Click)

```
.\start.bat
```

This script:
1. Runs pre-flight checks (backend venv, uvicorn, frontend node_modules)
2. Starts backend on port 8000 (new window)
3. Starts frontend on port 5173 (new window)
4. Waits up to 30s for backend health, 20s for Vite
5. Opens browser at `http://localhost:5173`

### Manual Launch

```bash
# Backend (terminal 1)
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# Frontend (terminal 2)
npm install
npm run dev
```

### npm Scripts

| Script | Command | Purpose |
|--------|---------|---------|
| `npm run dev` | `vite` | Development server |
| `npm run build` | `tsc -b && vite build` | Production build |
| `npm run test` | `vitest run` | Run tests |
| `npm run test:coverage` | `vitest run --coverage` | Tests with coverage |
| `npm run lint` | `eslint .` | Lint check |
| `npm run check:ds-drift` | `tsx scripts/check-ds-drift.ts` | Design system drift detection |
| `npm run validate:state` | `node scripts/validate-pipeline-state.mjs` | Pipeline state validation |
| `npm run openapi:dump` | `scripts/dump-openapi-spec.ps1` | OpenAPI spec extraction |
| `npm run chrome:debug` | `scripts/start-chrome-debug.ps1` | Chrome debug launcher |

## Docker Deployment

### docker-compose.yml

Two services behind Nginx:

| Service | Container | Port |
|---------|-----------|------|
| Backend | `Dockerfile.backend` | 8000 |
| Frontend | `Dockerfile.frontend` | 5173 (internal), 80 (nginx) |

```bash
docker-compose up
```

### Nginx Configuration

`nginx.conf` routes:
- `/api/*` → backend (port 8000)
- `/*` → frontend (port 5173, SPA fallback)

## Environment Variables

### Backend (FastAPI)

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | SQLite/PostgreSQL connection string |
| `OLLAMA_BASE_URL` | Ollama local endpoint |
| `YANDEXGPT_API_KEY` | Yandex Cloud AI key |
| `GIGACHAT_API_KEY` | GigaChat API key |
| `BEE_LINE_AI_API_KEY` | Beeline AI API key |
| `RAG_KB_CODE` | RAG knowledge base identifier |

### Frontend (Vite)

| Variable | Purpose |
|----------|---------|
| `VITE_API_URL` | Backend API URL override |

### NPM Registry

The `@beeline/*` packages require access to the private Beeline npm registry. Copy `npmrc.example` to `.npmrc` with proper credentials.

## Pipeline State Management

The project uses an AI agent pipeline for development, tracked in `docs/specs/pipeline-state.yaml` (72KB):

- `scripts/validate-pipeline-state.mjs` — Validates YAML syntax, catches duplicates and missing keys
- `scripts/commit-state.mjs` — Commits pipeline state changes

The pipeline state tracks active stages, completed work, and next steps across design-implement-review-test cycles.

## Scripts Reference

### Validation Scripts

| Script | Purpose |
|--------|---------|
| `scripts/validate-pipeline-state.mjs` | Pipeline state YAML validation |
| `scripts/check-ds-drift.ts` | Beeline DS prop drift detection |
| `scripts/bugfix-verify.mjs` | Automated bugfix verification |

### Vision Scripts

| Script | Purpose |
|--------|---------|
| `scripts/h2-screenshots.mjs` | CDP-based screenshot capture |
| `scripts/h2-vision-batch.mjs` | Batch vision analysis via LLM |
| `scripts/lm-vision-batch.mjs` | LLM vision batch processing |

### Infrastructure Scripts

| Script | Purpose |
|--------|---------|
| `scripts/generate-docs.ps1` | LLM-powered documentation generation |
| `scripts/dump-openapi-spec.ps1` | OpenAPI spec extraction |
| `scripts/openwiki.ps1` | OpenWiki model switcher (9 models) |
| `scripts/start-chrome-debug.ps1` | Chrome debug mode launcher |

## Night Shift (`.loops/`)

Automated bug hunting and senior review artifacts:

| File | Content |
|------|---------|
| `.loops/changes-log.md` | Bug fix log from Night Shift phases |
| `.loops/known-issues.md` | 11 tracked issues (9 fixed, 2 open) |
| `.loops/reflexion.md` | Lessons learned per iteration |
| `.loops/flaky-tests.md` | Flaky test tracker (currently empty) |

## Health Checks

- `GET /health` — Basic backend health
- `GET /ready` — Readiness check (database + LLM providers)
- `GET /providers` — LLM provider connectivity status
