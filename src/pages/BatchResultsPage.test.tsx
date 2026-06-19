/**
 * Tests for BatchResultsPage — batch analysis progress and summary table.
 * Covers: loading state, completed batch, partial batch, error states,
 * unmount safety (AbortController), and interval cleanup.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { AnalysisProvider } from '../context/AnalysisContext';
import BatchResultsPage from './BatchResultsPage';

// ─── Mock useNavigate / useParams ────────────────────────

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
    useParams: () => ({ batchId: 'test-batch-123' }),
  };
});

// ─── Mock API client ─────────────────────────────────────

const mockGetBatchStatus = vi.fn();
const mockGetResults = vi.fn();

vi.mock('../api/client', () => ({
  getBatchStatus: (...args: unknown[]) => mockGetBatchStatus(...args),
  getResults: (...args: unknown[]) => mockGetResults(...args),
  getBatchResults: vi.fn(),
  ApiError: class extends Error { status = 0; body?: unknown; },
}));

// ─── Mock history storage ────────────────────────────────

vi.mock('../storage/history', () => ({
  add: vi.fn(),
  remove: vi.fn(() => true),
  getAll: vi.fn(() => []),
  clearAll: vi.fn(),
  getStorageUsage: vi.fn(() => ({ usedBytes: 0, totalBytes: 5242880, percentage: 0 })),
  isStorageNearCapacity: vi.fn(() => false),
  cleanupOldEntries: vi.fn(() => 0),
}));

// ─── Helper ───────────────────────────────────────────────

function renderBatchResultsPage() {
  return render(
    <MemoryRouter>
      <AnalysisProvider>
        <BatchResultsPage />
      </AnalysisProvider>
    </MemoryRouter>,
  );
}

const COMPLETED_BATCH = {
  batch_id: 'test-batch-123',
  session_id: 'session-1',
  total_files: 2,
  status: 'completed',
  items: [
    {
      filename: 'file1.rtf',
      status: 'completed',
      analysis_id: 'analysis-1',
      total_matches: 5,
      matches_by_level: { '1': 2, '2': 2, '3': 1 },
      error: null,
    },
    {
      filename: 'file2.rtf',
      status: 'completed',
      analysis_id: 'analysis-2',
      total_matches: 3,
      matches_by_level: { '1': 1, '2': 1, '3': 1 },
      error: null,
    },
  ],
  completed_count: 2,
  failed_count: 0,
  error: null,
};

const PARTIAL_BATCH = {
  ...COMPLETED_BATCH,
  status: 'partial',
  completed_count: 1,
  failed_count: 1,
  items: [
    COMPLETED_BATCH.items[0],
    {
      filename: 'file2.rtf',
      status: 'failed',
      analysis_id: null,
      total_matches: 0,
      matches_by_level: {},
      error: 'Processing failed',
    },
  ],
};

// ─── Tests ────────────────────────────────────────────────

describe('BatchResultsPage', () => {
  beforeEach(() => {
    mockNavigate.mockReset();
    mockGetBatchStatus.mockReset();
    mockGetResults.mockReset();
  });

  it('renders loading state initially', () => {
    mockGetBatchStatus.mockReturnValue(new Promise(() => {})); // never resolves
    renderBatchResultsPage();
    expect(screen.getByText('Batch-анализ')).toBeInTheDocument();
    expect(screen.getByText('Загрузка статуса…')).toBeInTheDocument();
  });

  it('renders completed batch with summary table', async () => {
    mockGetBatchStatus.mockResolvedValue(COMPLETED_BATCH);
    renderBatchResultsPage();

    await waitFor(() => {
      expect(screen.getByText('file1.rtf')).toBeInTheDocument();
    }, { timeout: 10000 });
    expect(screen.getByText('file2.rtf')).toBeInTheDocument();
  });

  it('renders partial batch with inline alert', async () => {
    mockGetBatchStatus.mockResolvedValue(PARTIAL_BATCH);
    renderBatchResultsPage();

    await waitFor(() => {
      expect(screen.getByText(/Часть файлов обработана с ошибкой/)).toBeInTheDocument();
    }, { timeout: 10000 });
  });

  it('renders error state when API fails', async () => {
    mockGetBatchStatus.mockRejectedValue(new Error('Network error'));
    renderBatchResultsPage();

    await waitFor(() => {
      expect(screen.getByText('Network error')).toBeInTheDocument();
    }, { timeout: 10000 });
  });

  it('shows file count in progress text', async () => {
    mockGetBatchStatus.mockResolvedValue(COMPLETED_BATCH);
    renderBatchResultsPage();

    await waitFor(() => {
      expect(screen.getByText(/Обработано 2 из 2 файлов/)).toBeInTheDocument();
    }, { timeout: 10000 });
  });

  it('shows status badges for completed and failed items', async () => {
    mockGetBatchStatus.mockResolvedValue(PARTIAL_BATCH);
    renderBatchResultsPage();

    await waitFor(() => {
      expect(screen.getByText('Завершён')).toBeInTheDocument();
    }, { timeout: 10000 });
  });

  it('aborts in-flight fetch and clears interval on unmount', async () => {
    // Create a controlled promise for the initial load
    let resolveInitial: (value: unknown) => void;
    const initialPromise = new Promise((resolve) => {
      resolveInitial = resolve;
    });
    mockGetBatchStatus.mockReturnValue(initialPromise);

    const { unmount } = renderBatchResultsPage();

    // Initial load is in-flight
    expect(mockGetBatchStatus).toHaveBeenCalledTimes(1);

    // Resolve initial load
    await act(async () => {
      resolveInitial!(COMPLETED_BATCH);
    });

    await waitFor(() => {
      expect(screen.getByText('file1.rtf')).toBeInTheDocument();
    }, { timeout: 10000 });

    const callCountAfterLoad = mockGetBatchStatus.mock.calls.length;

    // Unmount — should clear interval and abort any in-flight request
    unmount();

    // After unmount, wait to see if any more API calls happen
    await act(async () => {
      await new Promise((r) => setTimeout(r, 3500));
    });

    // No additional API calls after unmount (interval was cleared)
    expect(mockGetBatchStatus.mock.calls.length).toBe(callCountAfterLoad);
  });

  it('does not update state after unmount when fetch resolves late', async () => {
    // Create a slow promise that we resolve after unmount
    let resolveSlow: (value: unknown) => void;
    const slowPromise = new Promise((resolve) => {
      resolveSlow = resolve;
    });

    // First call is slow, never resolves during component lifecycle
    mockGetBatchStatus.mockReturnValue(slowPromise);

    const { unmount } = renderBatchResultsPage();

    // Wait for initial load call
    await waitFor(() => {
      expect(mockGetBatchStatus).toHaveBeenCalled();
    });

    // Unmount while fetch is still in-flight
    unmount();

    // Now resolve the slow request — should NOT cause React state update error
    // (AbortError is caught and ignored in fetchStatus, or component is already unmounted)
    await act(async () => {
      resolveSlow!(COMPLETED_BATCH);
    });

    // No error thrown = test passes
  });
});
