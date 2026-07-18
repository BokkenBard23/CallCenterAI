---
type: Workflow
title: Key Workflows
description: "Detailed walkthrough of the main user workflows in CallCenterAI: call upload and analysis, dictionary management and mining, batch processing, and semantic search."
tags: [workflows, upload, analysis, dictionary, mining, batch, search]
---

# Key Workflows

## Upload and Analysis Pipeline

The primary user flow: upload a transcript, get AI-analyzed results with matched keywords.

```
User uploads RTF/XML
       │
       ▼
  Backend parses file
  (rtf_parser / xml_parser)
       │
       ▼
  SmartLogger matching
  (morphological engine)
       │
       ▼
  LLM analysis (parallel)
  ├── Sentiment
  ├── Conflict detection
  ├── Profanity filter
  └── Topic classification
       │
       ▼
  Results stored in SQLite
  (sessions table)
       │
       ▼
  Frontend polls /status/:id
  (2s intervals until done)
       │
       ▼
  ResultsPage renders
  (highlights + summary + scores)
```

**Key details:**

- Upload uses `FormData` for file uploads through `api/client.ts`
- Analysis runs the matching engine and LLM analysis **in parallel** (partial loading — LLM results are non-blocking for initial match display)
- Session IDs are managed in `AnalysisContext`, not URL params
- Quality scoring runs as a separate step after basic analysis

### Batch Processing

```
User submits batch
       │
       ▼
  Backend creates batch job
  (batches table)
       │
       ▼
  Each file processed
  (parallel analysis)
       │
       ▼
  Results aggregated
  │
  ▼
BatchResultsPage polls
/:batchId (2s intervals)
```

**Note:** The `submitBatch` method exists in `api/client.ts` but is not yet wired to the UploadPage UI — this is a known feature gap.

## Dictionary Management Workflow

The Dictionary Editor provides full CRUD for keyword dictionaries with AI assistance:

```
Load dictionary (XML or DB)
       │
       ▼
  DictionaryTreePanel (hierarchy)
       │
       ▼
  ConditionsTable (TanStack Table)
  ├── Add / Edit / Delete entries
  ├── Duplicate detection
  └── Phrase suggestions (AI)
       │
       ▼
  MiningPanel
  ├── Audit (false negatives)
  ├── Similar dialogues
  └── Directory picker
       │
       ▼
  XmlExportDialog
  (SmartLogger round-trip)
```

The `useDictionaryEditor.ts` hook (18KB) manages the entire dictionary state machine, including dirty state tracking, AI-assisted operations, and mining result integration.

## Mining Workflow

Dictionary mining identifies improvement opportunities:

```
Trigger mining job
       │
       ▼
  Mining backend service
  ├── Scans corpus for false negatives
  ├── Finds similar dialogues
  └── Generates improvement candidates
       │
       ▼
  Results stored in mining tables
  (mining_jobs, mining_corpus,
   mining_fn_candidates, etc.)
       │
       ▼
  MiningPanel displays results
  ├── Audit tab
  ├── False negatives tab
  └── Similar dialogues tab
```

## Semantic Search Workflow

Hybrid search combines vector similarity and keyword matching:

```
User enters query
       │
       ▼
  FRIDA embedding generation
  │
  ▼
  FAISS vector search
  + keyword match
  │
  ▼
  Hybrid ranking
  │
  ▼
  SemanticSearchPanel
  (results display)
```

## Vision Gate Workflow

The Vision Gate is an automated UI quality assurance workflow that runs multimodal LLM analysis on screenshots:

```
UI change committed
       │
       ▼
Automated screenshot capture
(Playwright / Chrome DevTools MCP)
       │
       ▼
Vision analysis pipeline
(gpt-5.4 primary → qwen-medium fallback)
       │
       ▼
Defect detection & classification
(High/Medium/Low severity)
       │
       ▼
Fix iteration
       │
       ▼
Verification screenshot
(Vision Gate passes → pipeline advances)
```

**Key details:**
- Vision prompts are stored in `backend/.vision-prompts/`
- Batch mode uses `asyncio.Semaphore` to respect per-model concurrency limits (gpt-5.4: 3, qwen-medium-dense: 6)
- `VisionAnalysisService` in `backend/app/services/vision_analysis.py` provides the fallback chain
- Vision Gate is enforced as a pipeline quality gate before advancement (see `.opencode/rules/05-vision-gate.md`)

## PII Masking Workflow

```
Transcript text
       │
       ▼
  Presidio base recognizers
  (email, phone, SSN, etc.)
       │
       ▼
  Custom Russian NER recognizers (7)
  ├── Passport numbers
  ├── Russian phone formats
  ├── INN/TIN numbers
  └── Custom entity types
       │
       ▼
  Masked output
  ([PERSON], [PHONE], etc.)
```

## Source Anchors

| Workflow | Frontend | Backend |
|----------|----------|---------|
| Upload | `src/pages/UploadPage.tsx` | `backend/app/routers/upload.py` |
| Analysis | `src/context/AnalysisContext.tsx` | `backend/app/services/` (analysis services) |
| Dictionary | `src/components/DictionaryEditor/` | `backend/app/routers/dictionary.py` |
| Mining | `src/components/DictionaryEditor/MiningPanel/` | `backend/app/routers/mining.py` |
| Vision Gate | N/A | `backend/app/services/vision_analysis.py` |
| Search | `src/components/SemanticSearchPanel/` | `backend/app/services/` (search services) |
| PII | Frontend display | `backend/app/routers/pii.py` |
