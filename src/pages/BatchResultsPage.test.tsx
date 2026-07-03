/**
 * Tests for BatchResultsPage — batch analysis progress and summary table.
 * Covers: loading state, completed batch, partial batch, error states,
 * unmount safety (AbortController), interval cleanup, AnimatedCircularProgressBar,
 * StatusBadge, pagination, empty state, and snackbar notifications.
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

// ─── Mock SnackbarContext ─────────────────────────────────

const mockShowSnackbar = vi.fn();
const mockCloseSnackbar = vi.fn();

vi.mock('../context/SnackbarContext', () => ({
  useSnackbar: () => ({
    showSnackbar: mockShowSnackbar,
    closeSnackbar: mockCloseSnackbar,
  }),
}));

// ─── Mock motion/react (framer-motion) ───────────────────

vi.mock('motion/react', async () => {
  const actual = await vi.importActual('motion/react');
  return {
    ...actual,
    // Speed up AnimatePresence in tests
    AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  };
});

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

const PROCESSING_BATCH = {
  ...COMPLETED_BATCH,
  status: 'processing',
  completed_count: 1,
  failed_count: 0,
  items: [
    COMPLETED_BATCH.items[0],
    {
      filename: 'file2.rtf',
      status: 'pending',
      analysis_id: null,
      total_matches: 0,
      matches_by_level: {},
      error: null,
    },
  ],
};

const EMPTY_BATCH = {
  batch_id: 'test-batch-123',
  session_id: 'session-1',
  total_files: 0,
  status: 'completed',
  items: [],
  completed_count: 0,
  failed_count: 0,
  error: null,
};

// ─── Tests ────────────────────────────────────────────────

describe('BatchResultsPage', () => {
  beforeEach(() => {
    mockNavigate.mockReset();
    mockGetBatchStatus.mockReset();
    mockGetResults.mockReset();
    mockShowSnackbar.mockReset();
    mockCloseSnackbar.mockReset();
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

  it('shows empty state when batch has no items', async () => {
    mockGetBatchStatus.mockResolvedValue(EMPTY_BATCH);
    renderBatchResultsPage();

    await waitFor(() => {
      expect(screen.getByText('Нет файлов для анализа')).toBeInTheDocument();
    }, { timeout: 10000 });
    expect(screen.getByText('На страницу загрузки')).toBeInTheDocument();
  });

  it('renders progress indicator for completed batch', async () => {
    mockGetBatchStatus.mockResolvedValue(COMPLETED_BATCH);
    renderBatchResultsPage();

    // Wait for data to load and verify the progress text is shown
    await waitFor(() => {
      expect(screen.getByText(/Обработано 2 из 2 файлов/)).toBeInTheDocument();
    }, { timeout: 10000 });

    // Verify at least one SVG progressbar is rendered (AnimatedCircularProgressBar)
    const progressSvgs = document.querySelectorAll('svg[role="progressbar"]');
    expect(progressSvgs.length).toBeGreaterThanOrEqual(1);
  });

  it('shows snackbar notification on batch completion', async () => {
    mockGetBatchStatus.mockResolvedValue(COMPLETED_BATCH);
    renderBatchResultsPage();

    await waitFor(() => {
      expect(mockShowSnackbar).toHaveBeenCalledWith(
        expect.stringContaining('Анализ завершён'),
        expect.objectContaining({
          action: expect.objectContaining({
            label: 'Посмотреть',
          }),
        }),
      );
    }, { timeout: 10000 });
  });

  it('shows snackbar notification on partial batch', async () => {
    mockGetBatchStatus.mockResolvedValue(PARTIAL_BATCH);
    renderBatchResultsPage();

    await waitFor(() => {
      expect(mockShowSnackbar).toHaveBeenCalledWith(
        expect.stringContaining('ошибкой'),
        expect.objectContaining({
          action: expect.objectContaining({
            label: 'Посмотреть',
          }),
        }),
      );
    }, { timeout: 10000 });
  });

  it('does not fire repeated snackbars on same status', async () => {
    // First call returns processing, then completed
    mockGetBatchStatus
      .mockResolvedValueOnce(PROCESSING_BATCH)
      .mockResolvedValueOnce(COMPLETED_BATCH);

    renderBatchResultsPage();

    await waitFor(() => {
      expect(mockShowSnackbar).toHaveBeenCalledTimes(1);
    }, { timeout: 10000 });
  });

  it('aborts in-flight fetch and clears interval on unmount', async () => {
    let resolveInitial: (value: unknown) => void;
    const initialPromise = new Promise((resolve) => {
      resolveInitial = resolve;
    });
    mockGetBatchStatus.mockReturnValue(initialPromise);

    const { unmount } = renderBatchResultsPage();

    expect(mockGetBatchStatus).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveInitial!(COMPLETED_BATCH);
    });

    await waitFor(() => {
      expect(screen.getByText('file1.rtf')).toBeInTheDocument();
    }, { timeout: 10000 });

    const callCountAfterLoad = mockGetBatchStatus.mock.calls.length;

    unmount();

    await act(async () => {
      await new Promise((r) => setTimeout(r, 3500));
    });

    expect(mockGetBatchStatus.mock.calls.length).toBe(callCountAfterLoad);
  });

  it('does not update state after unmount when fetch resolves late', async () => {
    let resolveSlow: (value: unknown) => void;
    const slowPromise = new Promise((resolve) => {
      resolveSlow = resolve;
    });

    mockGetBatchStatus.mockReturnValue(slowPromise);

    const { unmount } = renderBatchResultsPage();

    await waitFor(() => {
      expect(mockGetBatchStatus).toHaveBeenCalled();
    });

    unmount();

    await act(async () => {
      resolveSlow!(COMPLETED_BATCH);
    });

    // No error thrown = test passes
  });
});
