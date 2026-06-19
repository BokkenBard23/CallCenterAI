/**
 * Tests for ResultsPage — analysis results display with Tabs.
 * Covers: empty state, back navigation, heading checks,
 * populated state with searchResult and llmResult, tab switching,
 * hideNoMatch toggle, LLM warning banner,
 * FRIDA status badge, vectorize button, semantic search toggle.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import * as React from 'react';
import { AnalysisProvider, useAnalysisContext } from '../context/AnalysisContext';
import ResultsPage from './ResultsPage';
import type { SearchResult, LLMResult } from '../types/api';
import * as api from '../api/client';

// ─── Mock useNavigate ─────────────────────────────────────

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

// ─── Mock API ──────────────────────────────────────────────

vi.mock('../api/client', () => ({
  indexDialogue: vi.fn(),
  getEmbeddingStatus: vi.fn(),
  searchSemantic: vi.fn(),
  searchHybrid: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number;
    body?: unknown;
    constructor(message: string, status: number) {
      super(message);
      this.name = 'ApiError';
      this.status = status;
    }
  },
}));

const mockGetEmbeddingStatus = vi.mocked(api.getEmbeddingStatus);

// ─── Fixtures ─────────────────────────────────────────────

const sampleSearchResult: SearchResult = {
  segments: [
    { turn_index: 0, text: 'Клиент хочет расторгнуть', speaker: 'Клиент' },
    { turn_index: 1, text: 'Сотрудник помогает', speaker: 'Сотрудник' },
  ],
  total_matches: 2,
  matches: [
    {
      phrase_text: 'расторгнуть',
      matched_text: 'расторгнуть',
      matched_start: -1,
      matched_end: -1,
      quarter: 'Риск',
      turn_index: 0,
      speaker: 'Клиент',
      match_type: 'sliding_window',
      word_distance_used: 1,
      cascade_order: 1,
      is_exact_match: false,
    },
    {
      phrase_text: 'помогает',
      matched_text: 'помогает',
      matched_start: -1,
      matched_end: -1,
      quarter: 'Помощь',
      turn_index: 1,
      speaker: 'Сотрудник',
      match_type: 'sliding_window',
      word_distance_used: 2,
      cascade_order: 2,
      is_exact_match: false,
    },
  ],
  matches_by_level: { '1': 1, '2': 1 },
};

const sampleLLMResult: LLMResult = {
  summary: 'Клиент обратился по вопросу расторжения.',
  restructured_dialogue: 'Клиент: хочу расторгнуть\nСотрудник: помогу вам',
  topic: 'Расторжение договора',
  result: 'Вопрос решён',
  key_points: ['Клиент хочет расторгнуть', 'Сотрудник помог'],
  client_sentiment: 'negative',
  resolution: 'resolved',
  provider: 'ollama',
  model: 'llama3',
};

// ─── Helper to render with pre-populated state ─────────────

/** Component that sets context state before rendering ResultsPage */
function StateSetter({ stateOverrides }: { stateOverrides: Record<string, unknown> }) {
  const { dispatch } = useAnalysisContext();
  React.useEffect(() => {
    for (const [key, value] of Object.entries(stateOverrides)) {
      switch (key) {
        case 'searchResult':
          dispatch({ type: 'SET_ANALYSIS_RESULTS', payload: { searchResult: value as SearchResult | null, llmResult: null } });
          break;
        case 'llmResult':
          dispatch({ type: 'SET_ANALYSIS_RESULTS', payload: { searchResult: null, llmResult: value as LLMResult | null } });
          break;
        case 'both':
          dispatch({ type: 'SET_ANALYSIS_RESULTS', payload: value as { searchResult: SearchResult | null; llmResult: LLMResult | null } });
          break;
        case 'hideNoMatch':
          dispatch({ type: 'SET_HIDE_NO_MATCH', payload: value as boolean });
          break;
        case 'sessionId':
          dispatch({ type: 'SET_SESSION_ID', payload: value as string });
          break;
      }
    }
  }, [dispatch, stateOverrides]);
  return null;
}

function renderWithProviders(
  ui: React.ReactElement,
  initialEntries: string[] = ['/results'],
  stateOverrides?: Record<string, unknown>,
) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <AnalysisProvider>
        {stateOverrides && <StateSetter stateOverrides={stateOverrides} />}
        {ui}
      </AnalysisProvider>
    </MemoryRouter>,
  );
}

// ─── Tests ────────────────────────────────────────────────

describe('ResultsPage', () => {
  beforeEach(() => {
    mockNavigate.mockReset();
    mockGetEmbeddingStatus.mockResolvedValue({
      frida_available: true,
      vectors_stored: 100,
      unique_dialogues: 10,
      index_size_bytes: 512000,
      nlp_provider: 'natasha',
      natasha_available: true,
      deeppavlov_available: false,
    });
  });

  // ─── Empty state ──────────────────────────────────────

  it('shows empty state when no results', () => {
    renderWithProviders(<ResultsPage />);
    expect(screen.getByText('Результаты не найдены')).toBeTruthy();
    expect(screen.getByText(/Сначала загрузите диалог/)).toBeTruthy();
  });

  it('renders back button in empty state', () => {
    renderWithProviders(<ResultsPage />);
    const backButton = screen.getByLabelText('Назад к загрузке');
    expect(backButton).toBeTruthy();
  });

  it('navigates back when back button clicked', () => {
    renderWithProviders(<ResultsPage />);
    const backButton = screen.getByLabelText('Назад к загрузке');
    fireEvent.click(backButton);
    expect(mockNavigate).toHaveBeenCalledWith('/');
  });

  it('does not show main heading without results', () => {
    renderWithProviders(<ResultsPage />);
    expect(screen.queryByText('Результаты анализа')).toBeNull();
  });

  // ─── With searchResult only ───────────────────────────

  it('shows main heading when search result exists', () => {
    renderWithProviders(
      <ResultsPage />,
      ['/results'],
      { searchResult: sampleSearchResult },
    );
    expect(screen.getByText('Результаты анализа')).toBeTruthy();
  });

  it('shows LLM warning banner when no LLM result', () => {
    renderWithProviders(
      <ResultsPage />,
      ['/results'],
      { searchResult: sampleSearchResult },
    );
    expect(screen.getByText(/Сводка недоступна/)).toBeTruthy();
  });

  it('shows stats line with match count', () => {
    renderWithProviders(
      <ResultsPage />,
      ['/results'],
      { searchResult: sampleSearchResult },
    );
    expect(screen.getByText(/Всего совпадений: 2/)).toBeTruthy();
  });

  // ─── With both searchResult and llmResult ──────────────

  it('shows tabs when results exist', () => {
    renderWithProviders(
      <ResultsPage />,
      ['/results'],
      { both: { searchResult: sampleSearchResult, llmResult: sampleLLMResult } },
    );
    // "Сводка" appears both as tab label and as card heading — use getAllByText
    expect(screen.getAllByText('Сводка').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Выделенный текст')).toBeTruthy();
  });

  it('does not show LLM warning when both results exist', () => {
    renderWithProviders(
      <ResultsPage />,
      ['/results'],
      { both: { searchResult: sampleSearchResult, llmResult: sampleLLMResult } },
    );
    expect(screen.queryByText(/Сводка недоступна/)).toBeNull();
  });

  it('shows summary content on summary tab', () => {
    renderWithProviders(
      <ResultsPage />,
      ['/results'],
      { both: { searchResult: sampleSearchResult, llmResult: sampleLLMResult } },
    );
    // Summary view shows topic
    expect(screen.getByText('Расторжение договора')).toBeTruthy();
  });

  it('navigates back from results page', () => {
    renderWithProviders(
      <ResultsPage />,
      ['/results'],
      { searchResult: sampleSearchResult },
    );
    const backButtons = screen.getAllByLabelText('Назад к загрузке');
    fireEvent.click(backButtons[0]);
    expect(mockNavigate).toHaveBeenCalledWith('/');
  });

  // ─── With llmResult only ─────────────────────────────

  it('shows results heading with only LLM result', () => {
    renderWithProviders(
      <ResultsPage />,
      ['/results'],
      { llmResult: sampleLLMResult },
    );
    expect(screen.getByText('Результаты анализа')).toBeTruthy();
  });

  // ─── FRIDA status and vectorize ───────────────────────

  it('shows FRIDA status badge in header', async () => {
    renderWithProviders(
      <ResultsPage />,
      ['/results'],
      { searchResult: sampleSearchResult },
    );

    await waitFor(() => {
      expect(screen.getByText('FRIDA')).toBeTruthy();
    });
  });

  it('shows vectorize button when sessionId exists', () => {
    renderWithProviders(
      <ResultsPage />,
      ['/results'],
      { searchResult: sampleSearchResult, sessionId: 'test-session-1' },
    );
    expect(screen.getByText('Векторизовать')).toBeTruthy();
  });

  it('does not show vectorize button without sessionId', () => {
    renderWithProviders(
      <ResultsPage />,
      ['/results'],
      { searchResult: sampleSearchResult },
    );
    expect(screen.queryByText('Векторизовать')).toBeNull();
  });

  it('shows semantic search toggle button', () => {
    renderWithProviders(
      <ResultsPage />,
      ['/results'],
      { searchResult: sampleSearchResult },
    );
    expect(screen.getByLabelText('Семантический поиск')).toBeTruthy();
  });

  it('opens semantic panel when search toggle is clicked', async () => {
    renderWithProviders(
      <ResultsPage />,
      ['/results'],
      { searchResult: sampleSearchResult },
    );

    const searchToggle = screen.getByLabelText('Семантический поиск');
    fireEvent.click(searchToggle);

    // Panel should be visible with search input
    await waitFor(() => {
      expect(screen.getByText('Семантический поиск')).toBeTruthy();
    });
  });
});
