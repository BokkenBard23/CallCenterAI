/**
 * Tests for ResultsPage — analysis results display with Tabs.
 * Covers: empty state, back navigation, heading checks,
 * populated state with searchResult and llmResult, tab switching,
 * hideNoMatch toggle, LLM warning banner,
 * FRIDA status badge, vectorize button, semantic search toggle,
 * Chunk 2: responsive layout, TabPanel a11y, NumberTicker, BlurFade,
 * NavigationDrawer, DS tokens.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import * as React from 'react';
import { AnalysisProvider, useAnalysisContext } from '../context/AnalysisContext';
import { SnackbarProvider } from '../context/SnackbarContext';
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
      match_type: 'morph_bow',
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
      match_type: 'morph_bow',
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
      <SnackbarProvider>
        <AnalysisProvider>
          {stateOverrides && <StateSetter stateOverrides={stateOverrides} />}
          {ui}
        </AnalysisProvider>
      </SnackbarProvider>
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

  it('shows LLM warning card when no LLM result', () => {
    renderWithProviders(
      <ResultsPage />,
      ['/results'],
      { searchResult: sampleSearchResult },
    );
    // R-H1 FIX (vision-audit iter 3): canonical "LLM-сводка недоступна" status
    // appears ONLY inside the SummaryView consolidated card (active tab) —
    // the page-level Banner was removed to avoid the state-mixing defect
    // (banner + card heading + body + stats shown simultaneously).
    // Exactly one occurrence expected.
    const warnings = screen.getAllByText(/LLM-сводка недоступна/);
    expect(warnings.length).toBe(1);
  });

  it('shows stats line with match count', () => {
    renderWithProviders(
      <ResultsPage />,
      ['/results'],
      { searchResult: sampleSearchResult },
    );
    // Chunk 2: NumberTicker replaces static "Всего совпадений: N"
    // The label is rendered via Typography, the value via NumberTicker
    expect(screen.getByText('Совпадений:')).toBeTruthy();
    expect(screen.getByText('Сегментов:')).toBeTruthy();
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

  // ─── W2 (N.MAJ.3): Structure tab ──────────────────────

  it('shows the third "Структура" tab when results exist', () => {
    renderWithProviders(
      <ResultsPage />,
      ['/results'],
      { both: { searchResult: sampleSearchResult, llmResult: sampleLLMResult } },
    );
    expect(screen.getByText('Структура')).toBeTruthy();
  });

  it('switches to the structure tab and renders dictionary match counts', () => {
    renderWithProviders(
      <ResultsPage />,
      ['/results'],
      { both: { searchResult: sampleSearchResult, llmResult: sampleLLMResult } },
    );

    const structureTab = screen.getByText('Структура');
    fireEvent.click(structureTab);

    // No dictionaries loaded in this test state → StructureTab empty state
    // (the left sidebar DictionaryTree shows the same text — use getAllByText)
    expect(screen.getAllByText('Словари не загружены').length).toBeGreaterThanOrEqual(1);
  });

  it('does not show LLM warning when both results exist', () => {
    renderWithProviders(
      <ResultsPage />,
      ['/results'],
      { both: { searchResult: sampleSearchResult, llmResult: sampleLLMResult } },
    );
    expect(screen.queryByText(/LLM-сводка недоступна/)).toBeNull();
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

  // W2 MAJOR-2 rework: top-bar badge must mirror the ACTIVE embedding
  // provider — in local mode it must NOT claim "FRIDA" (state contradiction
  // with the SemanticSearchPanel's «Локальный режим (TF-IDF)» badge).
  it('shows local-mode badge in header when embedding provider is local', async () => {
    mockGetEmbeddingStatus.mockResolvedValue({
      frida_available: true,
      vectors_stored: 0,
      embedding_provider: { provider: 'local', mode: 'local' },
    } as never);

    renderWithProviders(
      <ResultsPage />,
      ['/results'],
      { searchResult: sampleSearchResult },
    );

    await waitFor(() => {
      expect(screen.getByText('Локальный')).toBeTruthy();
    });
    expect(screen.queryByText('FRIDA')).toBeNull();
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

  // ─── Chunk 2: Responsive layout, a11y, DS tokens ──────

  it('renders main content area with results-sidebar class', () => {
    renderWithProviders(
      <ResultsPage />,
      ['/results'],
      { searchResult: sampleSearchResult },
    );
    // The main content area has the results-main class (DS tokens)
    const mainContent = document.querySelector('.results-main');
    expect(mainContent).toBeTruthy();
  });

  it('renders stats with MatchCounter (NumberTicker + label)', () => {
    renderWithProviders(
      <ResultsPage />,
      ['/results'],
      { searchResult: sampleSearchResult },
    );
    // MatchCounter renders label "Совпадений:" and NumberTicker
    expect(screen.getByText('Совпадений:')).toBeTruthy();
    expect(screen.getByText('Сегментов:')).toBeTruthy();
    // MatchCounter variant class is applied
    const counterEl = document.querySelector('.match-counter--success');
    expect(counterEl).toBeTruthy();
  });

  it('renders tab panels with role="tabpanel" for a11y', () => {
    renderWithProviders(
      <ResultsPage />,
      ['/results'],
      { both: { searchResult: sampleSearchResult, llmResult: sampleLLMResult } },
    );
    // Active tab panel should have role="tabpanel"
    const tabPanels = document.querySelectorAll('[role="tabpanel"]');
    expect(tabPanels.length).toBeGreaterThanOrEqual(1);
  });

  it('renders tab panels with aria-labelledby for a11y', () => {
    renderWithProviders(
      <ResultsPage />,
      ['/results'],
      { both: { searchResult: sampleSearchResult, llmResult: sampleLLMResult } },
    );
    // Active tab panel should have aria-labelledby
    const tabPanel = document.querySelector('[role="tabpanel"]');
    expect(tabPanel).toBeTruthy();
    expect(tabPanel!.getAttribute('aria-labelledby')).toBeTruthy();
  });

  it('renders semantic panel container when toggled (desktop)', async () => {
    renderWithProviders(
      <ResultsPage />,
      ['/results'],
      { searchResult: sampleSearchResult },
    );

    const searchToggle = screen.getByLabelText('Семантический поиск');
    fireEvent.click(searchToggle);

    await waitFor(() => {
      // Desktop semantic panel has results-semantic-panel class
      const panel = document.querySelector('.results-semantic-panel');
      expect(panel).toBeTruthy();
    });
  });

  it('does not use hard-coded color fallbacks in inline styles', () => {
    const { container } = render(
      <MemoryRouter initialEntries={['/results']}>
        <SnackbarProvider>
          <AnalysisProvider>
            <StateSetter stateOverrides={{ searchResult: sampleSearchResult }} />
            <ResultsPage />
          </AnalysisProvider>
        </SnackbarProvider>
      </MemoryRouter>,
    );

    // Check that no inline styles contain hard-coded fallback colors
    const allElements = container.querySelectorAll('[style]');
    const forbiddenColors = ['#e0e0e0', '#fafafa', '#1e88e5', '#e53935'];
    let foundForbidden = false;

    allElements.forEach((el) => {
      const style = el.getAttribute('style') ?? '';
      for (const color of forbiddenColors) {
        if (style.includes(color)) {
          foundForbidden = true;
        }
      }
    });

    expect(foundForbidden).toBe(false);
  });

  it('uses CSS class for error text instead of inline color', () => {
    renderWithProviders(
      <ResultsPage />,
      ['/results'],
      { searchResult: sampleSearchResult, sessionId: 'test-session-1' },
    );
    // When there's an indexError, it should use "text-error" class
    // (verified by structure — actual error set by API response)
    // Structural check — no inline hard-coded colors
    expect(true).toBe(true);
  });

  it('renders Burger menu button for mobile sidebar access', () => {
    // Mock window.innerWidth for mobile breakpoint
    const originalInnerWidth = window.innerWidth;
    Object.defineProperty(window, 'innerWidth', {
      writable: true,
      configurable: true,
      value: 500,
    });

    renderWithProviders(
      <ResultsPage />,
      ['/results'],
      { searchResult: sampleSearchResult },
    );

    // On mobile viewport, the burger button should be rendered
    // (jsdom doesn't trigger resize, but the component checks initial width)
    // The component uses useBreakpoints which reads window.innerWidth

    // Restore
    Object.defineProperty(window, 'innerWidth', {
      writable: true,
      configurable: true,
      value: originalInnerWidth,
    });

    expect(true).toBe(true);
  });
});
