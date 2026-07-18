---
type: Testing
title: Testing Strategy
description: Testing strategy and quality gates for CallCenterAI, covering frontend tests (Vitest), backend tests (pytest), design system drift detection, vision auditing, and CI/CD quality gates.
tags: [testing, vitest, pytest, coverage, quality-gates, vision, drift]
---

# Testing Strategy

## Overview

CallCenterAI maintains **over 1800 tests** across frontend and backend, with multiple quality gates enforced in CI and pre-commit hooks.

| Suite | Count | Framework |
|-------|-------|-----------|
| Frontend | 565 | Vitest + Testing Library |
| Backend | 1307+ | pytest |
| **Total** | **1872+** | |

## Frontend Testing

### Framework

- **Vitest** with `jsdom` environment and `@testing-library/react`
- **Coverage**: v8 provider, reports in text/json/html formats
- **Setup**: `src/test/setup.ts` with Testing Library DOM matchers

### Test Organization

Tests are colocated with source files using the `.test.tsx` / `.test.ts` convention:

| Area | Location | Count |
|------|----------|-------|
| API client | `src/api/client.test.ts` | Provider and endpoint tests |
| Dictionary Editor | `src/components/DictionaryEditor/*.test.tsx` | 61 tests |
| SpeechLab | `src/components/SpeechLab/*.test.tsx` | Component tests |
| Context/Hooks | `src/context/*.test.tsx`, `src/hooks/*.test.tsx` | State management |
| Utilities | `src/utils/*.test.ts` | Parser and utility tests |
| Components | `src/components/**/*.test.tsx` | UI component tests |

### Known Issues

- 1 known failure in `client.test.ts` (`getProviders` test)
- Tests for `HoverContext` require a custom wrapper (`HoverContextWrapper.tsx`)

### Running Tests

```bash
npm run test           # Run all tests
npm run test:coverage  # Run with coverage report
npm run test:watch     # Watch mode
```

## Backend Testing

### Framework

- **pytest** with comprehensive fixture setup
- Tests cover routers, services, schemas, and integrations

### Coverage Areas

| Area | Tests |
|------|-------|
| API routers | Endpoint behavior, request/response validation |
| Services | Business logic, matching, analysis |
| PII masking | 182 tests for Presidio + custom recognizers |
| SmartLogger | Matching accuracy, morphological handling |
| Database | Session CRUD, batch operations |
| LLM providers | Provider connectivity, fallback behavior |

### Running Tests

```bash
cd backend
pytest                # Run all tests
pytest -v             # Verbose output
pytest --cov=app      # Coverage report
```

## Quality Gates

### Pre-Commit

```
husky + lint-staged
    └── eslint --fix on *.ts,*.tsx
```

Every commit on TypeScript/TSX files runs ESLint auto-fix before committing.

### Type Checking

```bash
tsc -b --force        # Composite project type check
```

**Critical:** `tsc --noEmit` on the root config is a no-op (always exit 0). Always use `tsc -b --force`.

### Linting

```bash
npm run lint          # ESLint (flat config)
```

### Design System Drift Detection

```bash
npm run check:ds-drift
```

Runs `scripts/check-ds-drift.ts` to detect prop changes in 47 tracked Beeline DS components. Configured as a weekly CI cron job. Generates GitHub issues on drift.

### Pipeline State Validation

```bash
npm run validate:state
```

Validates `docs/specs/pipeline-state.yaml` for syntax errors, duplicate keys, missing routing keys, and type mismatches. Exit code 1 blocks commit/CI.

### Visual Testing

Vision-based UI auditing using LLM:

1. `scripts/h2-screenshots.mjs` — Captures screenshots at 319/768/1440 breakpoints via CDP
2. `scripts/h2-vision-batch.mjs` — Batch vision analysis
3. Results verified through `.loops/` artifacts

## Coverage Baseline (as of 2026-07-13)

| Metric | Value |
|--------|-------|
| `tsc -b --force` | ExitCode 0 |
| `vitest run` | 565/565 passing |
| `eslint .` | 0 errors |
| Dictionary Editor tests | 61/61 passing |
| PII masking tests | 182/182 passing |
| Mining audit tests | 46/46 passing |

## Testing Tips

- **Frontend**: Component tests use `@testing-library/react` — query by role/text, not implementation details
- **Backend**: Use pytest fixtures for database isolation and mock LLM providers
- **PII tests**: The 182 PII masking tests are comprehensive — add new Russian entity patterns with corresponding test cases
- **DS drift**: When a Beeline DS update introduces breaking changes, check the 8 documented gotchas in `UI_GUIDELINES.md` before updating tests
