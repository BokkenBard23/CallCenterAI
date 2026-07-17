/**
 * MiningPanel.test.tsx — Component tests for Track B Quick Win MiningPanel.
 *
 * Covers reviewer condition m-5: MiningPanel component tests were absent.
 *
 * Mock strategy: useMiningState is mocked at module level so the panel
 * renders in isolation (no API calls, no polling). The mock return value
 * is configured per-test via mockUseMiningState.mockReturnValue(...).
 *
 * MINING-LAYOUT-FIX: tests 9–12 were updated to match the new inline
 * DirectoryPicker flow (no nested DS Dialog — see DirectoryPicker.tsx).
 * The picker now auto-confirms on file selection via a hidden input;
 * there is no "Подтвердить" button or modal dialog anymore.
 *
 * Coverage (12 tests):
 *   1.  Renders 3 tab labels + picker row + process button
 *   2.  "Обработать" disabled when no directory selected
 *   3.  Shows dictionary hint when dictionaryId is null
 *   4.  Error InlineAlert when index job failed
 *   5.  Partial warning InlineAlert when index job partial
 *   6.  Cancelled info InlineAlert when index job cancelled
 *   7.  MiningProgress renders when index job exists (running)
 *   8.  Tab switching updates active tab indicator
 *   9.  DirectoryPicker renders a hidden webkitdirectory input
 *   10. No directory label shown until a directory is picked
 *   11. Directory selection flow enables "Обработать" button
 *   12. indexCorpus called when "Обработать" clicked after selection
 */
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ─── Module mock: useMiningState ──────────────────────────────
// Must be declared before imports of modules that use it.
vi.mock('../../../hooks/useMiningState', () => ({
  useMiningState: vi.fn(),
}));

import { useMiningState } from '../../../hooks/useMiningState';
import type { UseMiningState } from '../../../hooks/useMiningState';
import { MiningPanel } from './MiningPanel';
import type { DictionaryNode, DictionarySuggestion, MiningJobStatus } from '../../../types/api';

const mockUseMiningState = vi.mocked(useMiningState);

// ─── Fixtures ────────────────────────────────────────────────

const mockTree: DictionaryNode[] = [
  {
    id: 'root-1',
    name: 'Root Dict',
    parent_name: null,
    conditions: [],
    children: [],
    condition_count: 0,
    has_children: false,
    children_count: 0,
  },
];

const mockActions = {
  indexCorpus: vi.fn().mockResolvedValue(undefined),
  findSimilar: vi.fn().mockResolvedValue(undefined),
  findFalseNegatives: vi.fn().mockResolvedValue(undefined),
  auditDictionary: vi.fn().mockResolvedValue(undefined),
  cancelJob: vi.fn().mockResolvedValue(undefined),
};

function createMockMiningState(overrides: Partial<UseMiningState> = {}): UseMiningState {
  return {
    indexJob: null,
    fnJob: null,
    auditJob: null,
    similarResults: null,
    fnCandidates: null,
    auditResults: null,
    fnPartial: false,
    auditPartial: false,
    loadingSimilar: false,
    loadingFN: false,
    loadingAudit: false,
    cancelling: false,
    errors: { index: null, findSimilar: null, findFN: null, audit: null },
    ...mockActions,
    ...overrides,
  };
}

function makeJob(overrides: Partial<MiningJobStatus> = {}): MiningJobStatus {
  return {
    job_id: 'job-test-1',
    status: 'running',
    progress: 0.5,
    processed_dialogues: 50,
    total_dialogues: 100,
    checkpoint_at: '2026-07-12T10:00:00Z',
    started_at: '2026-07-12T09:50:00Z',
    completed_at: null,
    error: null,
    warning: null,
    ...overrides,
  };
}

interface RenderOptions {
  sessionId?: string;
  dictionaryId?: string | null;
  tree?: DictionaryNode[];
  onAddSuggestion?: (s: DictionarySuggestion) => void;
  miningState?: Partial<UseMiningState>;
}

function renderPanel(options: RenderOptions = {}) {
  const props = {
    sessionId: options.sessionId ?? 'session-1',
    // Use `=== undefined` check so that explicit `null` is preserved
    // (nullish coalescing `??` would coerce `null` back to the default).
    dictionaryId: options.dictionaryId === undefined ? 'dict-1' : options.dictionaryId,
    tree: options.tree ?? mockTree,
    onAddSuggestion: options.onAddSuggestion ?? vi.fn(),
  };
  mockUseMiningState.mockReturnValue(createMockMiningState(options.miningState));
  return render(<MiningPanel {...props} />);
}

/**
 * Create a mock File with webkitRelativePath set.
 * jsdom's File constructor does not populate webkitRelativePath
 * (only the browser does when <input webkitdirectory> is used).
 */
function createMockFile(name: string, relativePath: string): File {
  const file = new File(['rtf content'], name, { type: 'application/rtf' });
  Object.defineProperty(file, 'webkitRelativePath', {
    value: relativePath,
    configurable: true,
    writable: false,
  });
  return file;
}

/**
 * Set files on a hidden <input type="file"> and dispatch a change event.
 * jsdom's input.files is read-only, so we use Object.defineProperty.
 */
function setInputFiles(input: HTMLInputElement, files: File[]) {
  Object.defineProperty(input, 'files', {
    configurable: true,
    value: files,
  });
  fireEvent.change(input);
}

// ─── Tests ───────────────────────────────────────────────────

describe('MiningPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseMiningState.mockReturnValue(createMockMiningState());
  });

  // ── 1. Renders 3 tab labels + picker row + process button ──

  it('renders 3 tab labels, directory picker button, and process button', () => {
    renderPanel();

    expect(screen.getByText('Похожие на фразы')).toBeInTheDocument();
    expect(screen.getByText('False Negatives')).toBeInTheDocument();
    expect(screen.getByText('LLM-аудит')).toBeInTheDocument();
    expect(screen.getByText('Указать директорию с RTF')).toBeInTheDocument();
    expect(screen.getByText('Обработать')).toBeInTheDocument();
  });

  // ── 2. "Обработать" disabled when no directory selected ──

  it('disables "Обработать" button when no directory selected', () => {
    renderPanel({ dictionaryId: 'dict-1' });

    const btn = screen.getByText('Обработать').closest('button')!;
    expect(btn).toBeDisabled();
  });

  // ── 3. Shows dictionary hint when dictionaryId is null ──

  it('shows dictionary hint when dictionaryId is null', () => {
    renderPanel({ dictionaryId: null });

    expect(screen.getByText(/Выберите словарь в дереве/)).toBeInTheDocument();
  });

  // ── 4. Error InlineAlert when index job failed ──

  it('renders error InlineAlert when index job failed', () => {
    renderPanel({
      miningState: {
        indexJob: makeJob({
          status: 'failed',
          error: 'Corpus directory not found',
        }),
      },
    });

    expect(screen.getByText('Corpus directory not found')).toBeInTheDocument();
  });

  // ── 5. Partial warning InlineAlert when index job partial ──

  it('renders partial warning InlineAlert when index job is partial', () => {
    renderPanel({
      miningState: {
        indexJob: makeJob({
          status: 'partial',
          warning: 'LLM rate limited, partial results',
        }),
      },
    });

    expect(screen.getByText('LLM rate limited, partial results')).toBeInTheDocument();
  });

  // ── 6. Cancelled info InlineAlert when index job cancelled ──

  it('renders cancelled info InlineAlert when index job is cancelled', () => {
    renderPanel({
      miningState: {
        indexJob: makeJob({
          status: 'cancelled',
          processed_dialogues: 30,
          total_dialogues: 100,
        }),
      },
    });

    // The cancelled InlineAlert text is unique (contains "до отмены")
    expect(screen.getByText(/до отмены/)).toBeInTheDocument();
  });

  // ── 7. MiningProgress renders when index job exists (running) ──

  it('renders MiningProgress when index job exists', () => {
    renderPanel({
      miningState: {
        indexJob: makeJob({
          status: 'running',
          processed_dialogues: 50,
          total_dialogues: 100,
        }),
      },
    });

    expect(screen.getByText(/Обработано 50 из 100/)).toBeInTheDocument();
  });

  // ── 8. Tab switching updates active tab indicator ──

  it('switches active tab on click', () => {
    renderPanel();

    const indicator = screen.getByTestId('mining-panel-active-tab');
    expect(indicator.getAttribute('data-tab')).toBe('similar');

    fireEvent.click(screen.getByText('False Negatives'));

    expect(indicator.getAttribute('data-tab')).toBe('fn');
  });

  // ── 9. DirectoryPicker renders a hidden webkitdirectory input ──
  // MINING-LAYOUT-FIX: previously this test verified that the DS Dialog
  // opened on button click. The Dialog was removed (nested-modal overlay
  // conflict with the Sidesheet). The picker now uses a hidden input that
  // is triggered directly from the button via a ref.

  it('renders a hidden webkitdirectory input for directory selection', () => {
    renderPanel();

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    expect(input).toBeTruthy();
    // webkitdirectory attribute is set (non-standard; React spreads it).
    expect(input.getAttribute('webkitdirectory')).not.toBeNull();
    // Input is visually hidden but present in the DOM.
    expect(input.className).toContain('directory-picker__input');
  });

  // ── 10. No directory label shown until a directory is picked ──

  it('does not show a directory label until a directory is picked', () => {
    renderPanel({ dictionaryId: 'dict-1' });

    // No label rendered initially.
    expect(screen.queryByText(/файлов/)).not.toBeInTheDocument();

    // "Обработать" is disabled because no directory has been picked.
    const processBtn = screen.getByText('Обработать').closest('button')!;
    expect(processBtn).toBeDisabled();
  });

  // ── 11. Directory selection flow enables "Обработать" button ──
  // MINING-LAYOUT-FIX: no "Подтвердить" step anymore — picking files
  // auto-confirms via the inline hidden input.

  it('enables "Обработать" after directory selection', async () => {
    renderPanel({ dictionaryId: 'dict-1' });

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    expect(input).toBeTruthy();

    const file1 = createMockFile('dialog1.rtf', 'corpus/dialog1.rtf');
    const file2 = createMockFile('dialog2.rtf', 'corpus/dialog2.rtf');
    setInputFiles(input, [file1, file2]);

    // Verify directory label shown (auto-confirm, no confirm button needed).
    await waitFor(() => {
      expect(screen.getByText(/corpus/)).toBeInTheDocument();
    });

    const processBtn = screen.getByText('Обработать').closest('button')!;
    expect(processBtn).not.toBeDisabled();
  });

  // ── 12. indexCorpus called when "Обработать" clicked after selection ──

  it('calls indexCorpus when "Обработать" clicked after directory selection', async () => {
    renderPanel({ dictionaryId: 'dict-1' });

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file1 = createMockFile('dialog1.rtf', 'corpus/dialog1.rtf');
    setInputFiles(input, [file1]);

    await waitFor(() => {
      expect(screen.getByText(/corpus/)).toBeInTheDocument();
    });

    // Click process button
    fireEvent.click(screen.getByText('Обработать').closest('button')!);

    expect(mockActions.indexCorpus).toHaveBeenCalledTimes(1);
    expect(mockActions.indexCorpus).toHaveBeenCalledWith('corpus', 'dict-1');
  });
});
