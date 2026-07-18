---
type: Architecture
title: Frontend Architecture
description: Detailed frontend architecture of CallCenterAI covering routing, 60+ React components, state management via Context, Beeline Design System integration, and build configuration.
tags: [frontend, react, typescript, beeline, design-system, vite]
resource: /src/
---

# Frontend Architecture

The CallCenterAI frontend is a **React 18 + TypeScript** single-page application built with Vite 7, using `@beeline/design-system-react` 2.5 as the primary UI component library. It consists of 7 routes, 60+ components, and a Context-based state management layer with no external state libraries.

## Routing

The application uses `react-router-dom` v7 with **lazy-loaded** routes wrapped in `ErrorBoundary` components:

| Path | Component | Description |
|------|-----------|-------------|
| `/` | `UploadPage` | File upload stepper wizard (auto-advances on success) |
| `/results` | `ResultsPage` | Analysis results for current session (ID from `AnalysisContext`) |
| `/batch-results/:batchId` | `BatchResultsPage` | Batch analysis results (ID from URL params, 2s polling) |
| `/history` | `HistoryPage` | LocalStorage-backed call analysis history |
| `/speechlab` | `SpeechLabPage` | 3-panel resizable speech analytics workspace |
| `/speechlab/:sessionId` | `SpeechLabPage` | SpeechLab with preloaded session |
| `/dictionary` | `DictionaryLandingPage` | Landing page when no session is active — redirects to `/dictionary/:sessionId` or prompts upload |
| `/dictionary/:sessionId` | `DictionaryEditorPage` | Full CRUD dictionary editor with AI and mining panels |

**Critical:** Session IDs are NOT passed via URL for single-session flows. The `/results` route reads `sessionId` from `AnalysisContext` rather than URL params, keeping URLs clean and centralizing session state.

## Component Hierarchy

### Shared UI Primitives (`src/components/ui/`)

Animation and visual utility components: `animated-circular-progress-bar`, `animated-list`, `animated-theme-toggler`, `blur-fade`, `border-beam`, `number-ticker`.

### Core Components (`src/components/`)

| Component | Purpose |
|-----------|---------|
| `ErrorBoundary` | Global error boundary wrapper |
| `RouterLink` | Custom `react-router-dom` link wrapper |
| `PageBreadcrumbs` | Navigation breadcrumbs |
| `HighlightedTextView` / `HighlightRenderer` | Phrase matching in transcriptions |
| `MatchLegend` / `MatchCounter` | Match visual indicators |
| `PhrasePopover` | Detail popovers for matched phrases |
| `SummaryView` | AI-generated analysis summaries |
| `RestructuredDialogue` | Reorganized dialogue view |
| `QualityScorePanel` | Quality scoring rubric display |
| `SemanticSearchPanel` | Vector/hybrid search interface |
| `DropZone` | File upload drag-and-drop zone |
| `StatusBadge` | Semantic status indicators |

### SpeechLab Components (`src/components/SpeechLab/`)

The SpeechLab is a **3-panel resizable layout** using `react-resizable-panels`:

- `SpeechLabLayout` — Main 3-panel container
- `LeftPanel` — Tree navigation with `SpeechLabTree` and `treeDataMapper`
- `FoundRecordsTab` — Tab panel for search results
- `KeywordsDisplay` — Keyword matching display
- `QueryTab` — Query construction interface
- `SpeechLabTopBar` — Toolbar and controls
- `SpeechLabRtfDialog` — Transcript viewer dialog

### Dictionary Editor (`src/components/DictionaryEditor/`)

A complex editor using `@tanstack/react-table` 8.21 for the conditions grid:

| Component | Purpose |
|-----------|---------|
| `DictionaryTreePanel` | Hierarchical dictionary tree view |
| `ConditionsTable` | TanStack Table-powered conditions grid |
| `AIAnalysisPanel` | LLM-powered analysis (Sidesheet) |
| `PhraseSuggestionsModal` | AI-generated phrase suggestions |
| `DuplicatesModal` | Duplicate phrase detection |
| `XmlExportDialog` | XML export with SmartLogger round-trip |
| `StatisticsPanel` / `WordFrequencyBar` | Dictionary analytics |
| `MiningPanel` | Mining operations (audit, false negatives, similar dialogues) |

State is managed by `useDictionaryEditor.ts` (18KB) and `useDirtyState.ts` hooks.

## State Management

The frontend uses **pure React Context + hooks** with no external state library:

| Mechanism | File | Purpose |
|-----------|------|---------|
| `AnalysisContext` | `context/AnalysisContext.tsx` | Global app state (session, results, view mode) via reducer |
| `HoverContext` | `context/HoverContext.tsx` | Cross-component hover state |
| `SnackbarContext` | `context/SnackbarContext.tsx` | Toast notification system |
| `useSpeechLabState` | `hooks/useSpeechLabState.ts` | Aggregates API + context for SpeechLab |
| `useMiningState` | `hooks/useMiningState.ts` | Mining operation state machine |
| `useLocalStorage` | `hooks/useLocalStorage.ts` | Persistent LocalStorage wrapper |
| `useTheme` | `hooks/useTheme.ts` | Light/dark theme toggle |

**Flow:** `api/client.ts` → custom hooks → Context providers → Pages → Components

## API Client

`src/api/client.ts` (24KB) is the central HTTP client layer. It:

- Wraps `fetch` with error handling and session management
- Handles file uploads (FormData for RTF/XML)
- Streams analysis progress via SSE/polling
- Provides typed methods for all backend endpoints
- Supports batch operations and file downloads

## Beeline Design System Integration

The frontend is tightly coupled to `@beeline/design-system-react` 2.5.0:

- **47 inventoried DS components** tracked for drift
- **Custom UI components are FORBIDDEN** — gaps solved with minimal DS-styled wrappers
- **Drift detection**: `scripts/check-ds-drift.ts` runs weekly in CI, checks tracked components for prop changes, and generates GitHub issues on drift
- **8 documented DS gotchas** (v2.5): Slider infinite loop, TableCell vs TableData, InlineEdit requiring forwardRef, removed props, etc.

### Highlight Color Scheme (6 depth levels)

| Depth | Severity | Color |
|-------|----------|-------|
| 1 | Critical | Red |
| 2 | Important | Orange |
| 3 | Moderate | Amber |
| 4 | Info | Teal |
| 5 | Reference | Blue |
| 6 | Legacy | Brown |

### Channel Color-Coding

| Channel | Color | Badge |
|---------|-------|-------|
| OPERATOR | Green (`#81c784`) | violet |
| CLIENT | Blue (`#4fc3f7`) | success |
| ANY | Orange (`#ffb74d`) | neutral |

## Build Configuration

### Vite (`vite.config.ts`)

- `@/` path alias maps to `./src`
- API proxy: `/api` → `http://localhost:8000` (dev mode)
- Manual chunks: `react-vendor`, `ds-vendor`, `table-vendor`, `markdown-vendor`
- Vitest: jsdom environment, v8 coverage, `@beeline/*` inlined

### TypeScript (`tsconfig.json`)

**Critical gotcha:** Uses composite project references (`tsconfig.app.json` + `tsconfig.node.json`). Running `tsc --noEmit` on root is a no-op (always exit 0). Must use `tsc -b --force` for actual type checking.

### ESLint

Flat config with `@eslint/js`, `typescript-eslint`, `react-hooks`, `react-refresh`. Pre-commit hook via `husky` + `lint-staged` runs `eslint --fix` on `*.ts,*.tsx` files.

## Bundle Splitting

4 vendor chunks for optimized loading:
- `react-vendor` — React + ReactDOM + React Router
- `ds-vendor` — Beeline Design System + tokens
- `table-vendor` — TanStack Table
- `markdown-vendor` — react-markdown

## Source Map

| Area | Path |
|------|------|
| Entry point | `src/main.tsx`, `src/App.tsx` |
| Routing | `src/App.tsx` (route definitions) |
| API client | `src/api/client.ts` |
| Pages | `src/pages/` |
| Components | `src/components/` |
| Context | `src/context/` |
| Hooks | `src/hooks/` |
| Types | `src/types/api.ts` (30KB), `src/types/speechlab.ts` |
| Utilities | `src/utils/xmlParser.ts` (SmartLogger XML round-trip) |
| Storage | `src/storage/history.ts` |
