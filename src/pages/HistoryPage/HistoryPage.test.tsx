/**
 * Tests for HistoryPage — analysis history from localStorage.
 * Covers: empty state, history list, delete entry, clear all,
 * restore from history, storage warning, error states.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { AnalysisProvider } from '../../context/AnalysisContext';
import type { HistoryEntry } from '../../types/api';
import HistoryPage from './HistoryPage';

// ─── Mock useNavigate ────────────────────────────────────

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

// ─── Mock API client ─────────────────────────────────────

const mockGetResults = vi.fn();

vi.mock('../../api/client', () => ({
  getResults: (...args: unknown[]) => mockGetResults(...args),
  ApiError: class extends Error { status = 0; body?: unknown; },
}));

// ─── Mock history storage ────────────────────────────────

const mockGetAll = vi.fn<() => HistoryEntry[]>(() => []);
const mockRemove = vi.fn<(...args: unknown[]) => boolean>(() => true);
const mockClearAll = vi.fn();
const mockGetStorageUsage = vi.fn(() => ({
  usedBytes: 1024,
  totalBytes: 5242880,
  percentage: 0.0002,
}));
const mockIsStorageNearCapacity = vi.fn(() => false);

vi.mock('../../storage/history', () => ({
  getAll: () => mockGetAll(),
  remove: (...args: unknown[]) => mockRemove(...args),
  clearAll: () => mockClearAll(),
  add: vi.fn(),
  getStorageUsage: () => mockGetStorageUsage(),
  isStorageNearCapacity: () => mockIsStorageNearCapacity(),
  cleanupOldEntries: vi.fn(() => 0),
}));

// ─── Helper ───────────────────────────────────────────────

function renderHistoryPage() {
  return render(
    <MemoryRouter>
      <AnalysisProvider>
        <HistoryPage />
      </AnalysisProvider>
    </MemoryRouter>,
  );
}

// ─── Sample data ──────────────────────────────────────────

const SAMPLE_ENTRIES: HistoryEntry[] = [
  {
    id: 'entry-1',
    analysisId: 'analysis-1',
    sessionId: 'session-1',
    date: '2025-06-17T10:00:00.000Z',
    fileName: 'dialog1.rtf',
    dictionaryNames: ['Словарь 1'],
    totalMatches: 5,
    matchesByLevel: { '1': 2, '2': 2, '3': 1 },
    status: 'completed',
  },
  {
    id: 'entry-2',
    analysisId: 'analysis-2',
    sessionId: 'session-2',
    date: '2025-06-16T15:30:00.000Z',
    fileName: 'dialog2.rtf',
    dictionaryNames: ['Словарь A', 'Словарь B'],
    totalMatches: 0,
    matchesByLevel: {},
    status: 'failed',
  },
];

// ─── Tests ────────────────────────────────────────────────

describe('HistoryPage', () => {
  beforeEach(() => {
    mockNavigate.mockReset();
    mockGetAll.mockReset();
    mockRemove.mockReset();
    mockClearAll.mockReset();
    mockGetResults.mockReset();
    mockGetStorageUsage.mockReset();
    mockIsStorageNearCapacity.mockReset();

    mockGetAll.mockReturnValue([]);
    mockGetStorageUsage.mockReturnValue({
      usedBytes: 1024,
      totalBytes: 5242880,
      percentage: 0.0002,
    });
    mockIsStorageNearCapacity.mockReturnValue(false);
  });

  it('renders empty state when no history entries', () => {
    renderHistoryPage();
    expect(screen.getByText(/История пуста/)).toBeInTheDocument();
    expect(screen.getByText('Загрузить диалог')).toBeInTheDocument();
  });

  it('renders history table with entries', () => {
    mockGetAll.mockReturnValue(SAMPLE_ENTRIES);
    renderHistoryPage();

    expect(screen.getByText('dialog1.rtf')).toBeInTheDocument();
    expect(screen.getByText('dialog2.rtf')).toBeInTheDocument();
  });

  it('shows status badges for entries', () => {
    mockGetAll.mockReturnValue(SAMPLE_ENTRIES);
    renderHistoryPage();

    expect(screen.getByText('Завершён')).toBeInTheDocument();
    expect(screen.getByText('Ошибка')).toBeInTheDocument();
  });

  it('calls clearAll when "Очистить всё" is clicked', () => {
    mockGetAll.mockReturnValue(SAMPLE_ENTRIES);
    renderHistoryPage();

    const clearButton = screen.getByText('Очистить всё');
    fireEvent.click(clearButton);

    expect(mockClearAll).toHaveBeenCalled();
  });

  it('shows storage warning when near capacity', () => {
    mockGetAll.mockReturnValue(SAMPLE_ENTRIES);
    mockIsStorageNearCapacity.mockReturnValue(true);
    mockGetStorageUsage.mockReturnValue({
      usedBytes: 4194304,
      totalBytes: 5242880,
      percentage: 0.8,
    });

    renderHistoryPage();

    expect(screen.getByText(/Хранилище заполнено/)).toBeInTheDocument();
  });

  it('shows entry count summary', () => {
    mockGetAll.mockReturnValue(SAMPLE_ENTRIES);
    renderHistoryPage();

    expect(screen.getByText(/Записей: 2/)).toBeInTheDocument();
  });

  it('navigates to results when entry is clicked and backend available', async () => {
    mockGetAll.mockReturnValue(SAMPLE_ENTRIES);
    mockGetResults.mockResolvedValue({
      analysis_id: 'analysis-1',
      session_id: 'session-1',
      status: 'completed',
      search_result: { segments: [], total_matches: 5, matches: [], matches_by_level: {} },
      llm_result: null,
      error: null,
      warning: null,
    });

    renderHistoryPage();

    const dialogRow = screen.getByText('dialog1.rtf');
    fireEvent.click(dialogRow);

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/results');
    }, { timeout: 10000 });
  });

  it('shows error when backend unavailable and cache empty', async () => {
    const entryWithoutCache = [
      {
        ...SAMPLE_ENTRIES[0],
        searchResult: undefined,
        llmResult: undefined,
      },
    ];
    mockGetAll.mockReturnValue(entryWithoutCache);
    mockGetResults.mockRejectedValue(new Error('Server error'));

    renderHistoryPage();

    const dialogRow = screen.getByText('dialog1.rtf');
    fireEvent.click(dialogRow);

    await waitFor(() => {
      expect(screen.getByText(/Результаты недоступны/)).toBeInTheDocument();
    }, { timeout: 10000 });
  });

  it('deletes entry when delete button is clicked', () => {
    mockGetAll.mockReturnValue(SAMPLE_ENTRIES);
    renderHistoryPage();

    const deleteButtons = screen.getAllByLabelText(/Удалить запись/);
    fireEvent.click(deleteButtons[0]);

    expect(mockRemove).toHaveBeenCalledWith('entry-1');
  });

  it('shows dictionary names in table', () => {
    mockGetAll.mockReturnValue(SAMPLE_ENTRIES);
    renderHistoryPage();

    expect(screen.getByText('Словарь 1')).toBeInTheDocument();
    expect(screen.getByText('Словарь A, Словарь B')).toBeInTheDocument();
  });

  it('updates local state and removes from storage when delete succeeds', () => {
    mockGetAll.mockReturnValue(SAMPLE_ENTRIES);
    // Simulate: remove succeeds, getAll returns remaining entry
    mockRemove.mockReturnValue(true);
    mockRemove.mockImplementation(() => {
      mockGetAll.mockReturnValue([SAMPLE_ENTRIES[1]]);
      return true;
    });
    renderHistoryPage();

    // Both entries visible initially
    expect(screen.getByText('dialog1.rtf')).toBeInTheDocument();
    expect(screen.getByText('dialog2.rtf')).toBeInTheDocument();

    const deleteButtons = screen.getAllByLabelText(/Удалить запись/);
    fireEvent.click(deleteButtons[0]);

    // storage.remove was called
    expect(mockRemove).toHaveBeenCalledWith('entry-1');
    // Local state updated: dialog1.rtf removed from UI
    expect(screen.queryByText('dialog1.rtf')).not.toBeInTheDocument();
    // dialog2.rtf still visible
    expect(screen.getByText('dialog2.rtf')).toBeInTheDocument();
  });

  it('reverts local state when storage.remove fails (localStorage full)', () => {
    mockGetAll.mockReturnValue(SAMPLE_ENTRIES);
    // Simulate remove failure: storage still has all entries
    mockRemove.mockImplementation(() => {
      // remove() fails — returns false, getAll still returns both entries
      mockGetAll.mockReturnValue(SAMPLE_ENTRIES);
      return false;
    });
    renderHistoryPage();

    const deleteButtons = screen.getAllByLabelText(/Удалить запись/);
    fireEvent.click(deleteButtons[0]);

    // storage.remove was called
    expect(mockRemove).toHaveBeenCalledWith('entry-1');
    // When remove fails, entries should remain in UI (no stale state)
    expect(screen.getByText('dialog1.rtf')).toBeInTheDocument();
    expect(screen.getByText('dialog2.rtf')).toBeInTheDocument();
  });
});
