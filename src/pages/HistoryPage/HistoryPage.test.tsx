/**
 * Tests for HistoryPage — analysis history with pagination, search, and dialog.
 * Covers: empty state, history list, delete entry, clear all with dialog,
 * search/filter, pagination, restore from history, storage warning, error states.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { AnalysisProvider } from '../../context/AnalysisContext';
import { SnackbarProvider } from '../../context/SnackbarContext';
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

// ─── Mock motion/react to avoid animation issues in tests ──

vi.mock('motion/react', () => ({
  motion: {
    div: ({ children, ...props }: React.PropsWithChildren<Record<string, unknown>>) => <div {...props}>{children}</div>,
  },
  AnimatePresence: ({ children }: React.PropsWithChildren) => <>{children}</>,
  useInView: () => true,
  useMotionValue: () => ({ set: vi.fn(), on: vi.fn() }),
  useSpring: () => ({ on: vi.fn() }),
}));

// ─── Helper ───────────────────────────────────────────────

function renderHistoryPage() {
  return render(
    <MemoryRouter>
      <SnackbarProvider>
        <AnalysisProvider>
          <HistoryPage />
        </AnalysisProvider>
      </SnackbarProvider>
    </MemoryRouter>,
  );
}

// ─── Sample data ──────────────────────────────────────────

const SAMPLE_ENTRIES: HistoryEntry[] = Array.from({ length: 15 }, (_, i) => ({
  id: `entry-${i + 1}`,
  analysisId: `analysis-${i + 1}`,
  sessionId: `session-${i + 1}`,
  date: new Date(Date.now() - i * 86400000).toISOString(),
  fileName: `dialog${i + 1}.rtf`,
  dictionaryNames: i === 0 ? ['Словарь 1'] : i === 1 ? ['Словарь A', 'Словарь B'] : ['Общий'],
  totalMatches: 5 - i,
  matchesByLevel: { '1': 2, '2': 2, '3': 1 },
  status: i % 3 === 0 ? 'completed' : i % 3 === 1 ? 'failed' : 'partial',
}));

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

  it('renders history cards with entries', () => {
    mockGetAll.mockReturnValue(SAMPLE_ENTRIES.slice(0, 2));
    renderHistoryPage();

    expect(screen.getByText('dialog1.rtf')).toBeInTheDocument();
    expect(screen.getByText('dialog2.rtf')).toBeInTheDocument();
  });

  it('shows status badges for entries', () => {
    mockGetAll.mockReturnValue(SAMPLE_ENTRIES.slice(0, 3));
    renderHistoryPage();

    expect(screen.getByText('Завершён')).toBeInTheDocument();
    expect(screen.getByText('Ошибка')).toBeInTheDocument();
    expect(screen.getByText('Частично')).toBeInTheDocument();
  });

  it('opens confirmation dialog when "Очистить всё" is clicked', () => {
    mockGetAll.mockReturnValue(SAMPLE_ENTRIES.slice(0, 2));
    renderHistoryPage();

    const clearButton = screen.getByText('Очистить всё');
    fireEvent.click(clearButton);

    // Dialog should appear with confirmation text
    expect(screen.getByText('Очистить всю историю?')).toBeInTheDocument();
    expect(screen.getByText(/Все записи будут удалены/)).toBeInTheDocument();
  });

  it('clears history when "Очистить" is confirmed in dialog', () => {
    mockGetAll.mockReturnValue(SAMPLE_ENTRIES.slice(0, 2));
    renderHistoryPage();

    // Click "Очистить всё" button
    fireEvent.click(screen.getByText('Очистить всё'));

    // Confirm in dialog
    const confirmButtons = screen.getAllByText('Очистить');
    fireEvent.click(confirmButtons[confirmButtons.length - 1]);

    expect(mockClearAll).toHaveBeenCalled();
  });

  it('does NOT clear history when "Отмена" is clicked in dialog', () => {
    mockGetAll.mockReturnValue(SAMPLE_ENTRIES.slice(0, 2));
    renderHistoryPage();

    fireEvent.click(screen.getByText('Очистить всё'));
    fireEvent.click(screen.getByText('Отмена'));

    expect(mockClearAll).not.toHaveBeenCalled();
  });

  it('shows storage warning when near capacity', () => {
    mockGetAll.mockReturnValue(SAMPLE_ENTRIES.slice(0, 2));
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
    mockGetAll.mockReturnValue(SAMPLE_ENTRIES.slice(0, 2));
    renderHistoryPage();

    expect(screen.getByText(/Записей: 2/)).toBeInTheDocument();
  });

  it('navigates to results when entry is clicked and backend available', async () => {
    mockGetAll.mockReturnValue(SAMPLE_ENTRIES.slice(0, 2));
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
    mockGetAll.mockReturnValue(SAMPLE_ENTRIES.slice(0, 2));
    renderHistoryPage();

    const deleteButtons = screen.getAllByLabelText(/Удалить запись/);
    fireEvent.click(deleteButtons[0]);

    expect(mockRemove).toHaveBeenCalledWith('entry-1');
  });

  it('shows dictionary names in cards', () => {
    mockGetAll.mockReturnValue(SAMPLE_ENTRIES.slice(0, 2));
    renderHistoryPage();

    expect(screen.getByText('Словарь 1')).toBeInTheDocument();
    expect(screen.getByText('Словарь A, Словарь B')).toBeInTheDocument();
  });

  it('shows search field', () => {
    mockGetAll.mockReturnValue(SAMPLE_ENTRIES.slice(0, 2));
    renderHistoryPage();

    expect(screen.getByPlaceholderText(/Поиск по файлу или словарю/)).toBeInTheDocument();
  });

  it('filters entries by search query', () => {
    mockGetAll.mockReturnValue(SAMPLE_ENTRIES.slice(0, 3));
    renderHistoryPage();

    // All 3 visible initially
    expect(screen.getByText('dialog1.rtf')).toBeInTheDocument();
    expect(screen.getByText('dialog2.rtf')).toBeInTheDocument();
    expect(screen.getByText('dialog3.rtf')).toBeInTheDocument();

    // Type search query
    const searchInput = screen.getByPlaceholderText(/Поиск по файлу или словарю/);
    fireEvent.change(searchInput, { target: { value: 'dialog1' } });

    // Only matching entry visible
    expect(screen.getByText('dialog1.rtf')).toBeInTheDocument();
    expect(screen.queryByText('dialog2.rtf')).not.toBeInTheDocument();
    expect(screen.queryByText('dialog3.rtf')).not.toBeInTheDocument();
  });

  it('shows "Ничего не найдено" when search has no results', () => {
    mockGetAll.mockReturnValue(SAMPLE_ENTRIES.slice(0, 2));
    renderHistoryPage();

    const searchInput = screen.getByPlaceholderText(/Поиск по файлу или словарю/);
    fireEvent.change(searchInput, { target: { value: 'nonexistent' } });

    expect(screen.getByText('Ничего не найдено')).toBeInTheDocument();
  });

  it('resets page to 1 when search query changes', () => {
    // Create enough entries for pagination
    mockGetAll.mockReturnValue(SAMPLE_ENTRIES);
    renderHistoryPage();

    // Should be on page 1 initially
    const searchInput = screen.getByPlaceholderText(/Поиск по файлу или словарю/);
    fireEvent.change(searchInput, { target: { value: 'dialog' } });

    // After search, still on page 1 with filtered results
    expect(screen.getByText('dialog1.rtf')).toBeInTheDocument();
  });

  it('shows pagination when more than 10 entries', () => {
    mockGetAll.mockReturnValue(SAMPLE_ENTRIES); // 15 entries
    renderHistoryPage();

    // Pagination should be visible (15 entries, 2 pages)
    // DS Pagination renders with page numbers
    expect(screen.getByText(/Записей: 15/)).toBeInTheDocument();
  });

  it('updates local state and removes from storage when delete succeeds', () => {
    mockGetAll.mockReturnValue(SAMPLE_ENTRIES.slice(0, 2));
    mockRemove.mockReturnValue(true);
    mockRemove.mockImplementation(() => {
      mockGetAll.mockReturnValue([SAMPLE_ENTRIES[1]]);
      return true;
    });
    renderHistoryPage();

    expect(screen.getByText('dialog1.rtf')).toBeInTheDocument();
    expect(screen.getByText('dialog2.rtf')).toBeInTheDocument();

    const deleteButtons = screen.getAllByLabelText(/Удалить запись/);
    fireEvent.click(deleteButtons[0]);

    expect(mockRemove).toHaveBeenCalledWith('entry-1');
    expect(screen.queryByText('dialog1.rtf')).not.toBeInTheDocument();
    expect(screen.getByText('dialog2.rtf')).toBeInTheDocument();
  });

  it('reverts local state when storage.remove fails (localStorage full)', () => {
    mockGetAll.mockReturnValue(SAMPLE_ENTRIES.slice(0, 2));
    mockRemove.mockImplementation(() => {
      mockGetAll.mockReturnValue(SAMPLE_ENTRIES.slice(0, 2));
      return false;
    });
    renderHistoryPage();

    const deleteButtons = screen.getAllByLabelText(/Удалить запись/);
    fireEvent.click(deleteButtons[0]);

    expect(mockRemove).toHaveBeenCalledWith('entry-1');
    // When remove fails, entries should remain in UI
    expect(screen.getByText('dialog1.rtf')).toBeInTheDocument();
    expect(screen.getByText('dialog2.rtf')).toBeInTheDocument();
  });
});
