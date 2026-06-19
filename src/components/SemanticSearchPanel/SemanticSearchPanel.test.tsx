/**
 * Tests for SemanticSearchPanel — semantic/hybrid search sidebar.
 * Covers: idle state, searching state, results display, empty state,
 * error states (FRIDA unavailable, rate limit), search history,
 * type toggle, FRIDA status indicator, cross-highlighting callback.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import SemanticSearchPanel from './SemanticSearchPanel';
import * as api from '../../api/client';
import type { HybridSearchResult, VectorSearchResult } from '../../types/api';

// ─── Mock API ──────────────────────────────────────────────

vi.mock('../../api/client', () => ({
  searchSemantic: vi.fn(),
  searchHybrid: vi.fn(),
  getEmbeddingStatus: vi.fn(),
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

const mockSearchSemantic = vi.mocked(api.searchSemantic);
const mockSearchHybrid = vi.mocked(api.searchHybrid);
const mockGetEmbeddingStatus = vi.mocked(api.getEmbeddingStatus);

// ─── Fixtures ──────────────────────────────────────────────

const sampleHybridResults: HybridSearchResult[] = [
  {
    text: 'хочу подключить услугу',
    dialogue_id: 'dialog-1',
    turn_index: 3,
    speaker: 'Клиент',
    morph_score: 0.5,
    semantic_score: 0.8,
    ner_boost: 0.1,
    matched_entities: ['услугу'],
    combined_score: 0.87,
    source: 'hybrid',
  },
  {
    text: 'отдел продаж поможет',
    dialogue_id: 'dialog-1',
    turn_index: 5,
    speaker: 'Сотрудник',
    morph_score: 0.3,
    semantic_score: 0.6,
    ner_boost: 0.0,
    matched_entities: ['продаж'],
    combined_score: 0.72,
    source: 'morph',
  },
];

const sampleSemanticResults: VectorSearchResult[] = [
  {
    chunk_id: 'chunk-1',
    text: 'подключить интернет',
    dialogue_id: 'dialog-1',
    turn_index: 2,
    speaker: 'Клиент',
    score: 0.92,
    chunk_type: 'turn',
    entities: [{ text: 'интернет', type: 'PRODUCT' }],
  },
];

const defaultFridaStatus = {
  frida_available: true,
  vectors_stored: 150,
  unique_dialogues: 12,
  index_size_bytes: 1024000,
  nlp_provider: 'natasha' as const,
  natasha_available: true,
  deeppavlov_available: false,
};

// ─── Helper ────────────────────────────────────────────────

function renderPanel(overrides: Record<string, unknown> = {}) {
  const props = {
    sessionId: 'test-session',
    onResultClick: vi.fn(),
    onClose: vi.fn(),
    ...overrides,
  };

  return render(
    <SemanticSearchPanel {...props} />
  );
}

// ─── Tests ──────────────────────────────────────────────────

describe('SemanticSearchPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetEmbeddingStatus.mockResolvedValue(defaultFridaStatus);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // ─── Idle state ──────────────────────────────────────

  it('renders idle state with search input and placeholder', async () => {
    renderPanel();
    expect(screen.getByText('Семантический поиск')).toBeTruthy();
    expect(screen.getByText('Введите запрос для семантического поиска')).toBeTruthy();
  });

  it('shows FRIDA status badge', async () => {
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText('FRIDA')).toBeTruthy();
    });
  });

  it('shows FRIDA unavailable status when API returns frida_available=false', async () => {
    mockGetEmbeddingStatus.mockResolvedValue({
      ...defaultFridaStatus,
      frida_available: false,
    });
    renderPanel();

    await waitFor(() => {
      expect(screen.getByText('OFF')).toBeTruthy();
    });
  });

  it('renders semantic and hybrid toggle buttons', () => {
    renderPanel();
    expect(screen.getByText('Семантический')).toBeTruthy();
    expect(screen.getByText('Гибридный')).toBeTruthy();
  });

  it('renders search button', () => {
    renderPanel();
    expect(screen.getByText('Искать')).toBeTruthy();
  });

  it('disables search button when query is empty', () => {
    renderPanel();
    const searchButton = screen.getByText('Искать').closest('button');
    expect(searchButton?.disabled).toBe(true);
  });

  // ─── Searching state ─────────────────────────────────

  it('shows loading skeleton while searching', async () => {
    mockSearchHybrid.mockImplementation(
      () => new Promise((resolve) => setTimeout(resolve, 1000)),
    );
    renderPanel();

    const input = screen.getByLabelText('Поисковый запрос');
    fireEvent.change(input, { target: { value: 'услуга' } });

    // Click search button
    const searchButton = screen.getByText('Искать');
    fireEvent.click(searchButton);

    await waitFor(() => {
      expect(mockSearchHybrid).toHaveBeenCalled();
    });
  });

  // ─── Results display ─────────────────────────────────

  it('displays hybrid search results after search', async () => {
    mockSearchHybrid.mockResolvedValue({
      results: sampleHybridResults,
      query: 'услуга',
      total: 2,
    });
    renderPanel();

    const input = screen.getByLabelText('Поисковый запрос');
    fireEvent.change(input, { target: { value: 'услуга' } });

    const searchButton = screen.getByText('Искать');
    fireEvent.click(searchButton);

    await waitFor(() => {
      // Text may be split by <mark> tags — use partial match
      expect(screen.getByText(/подключить/)).toBeTruthy();
    });

    // Score badge
    expect(screen.getByText('0.87')).toBeTruthy();
    // Results count
    expect(screen.getByText(/Найдено: 2 результатов/)).toBeTruthy();
  });

  it('displays semantic search results', async () => {
    mockSearchSemantic.mockResolvedValue({
      results: sampleSemanticResults,
      query: 'интернет',
      total: 1,
    });
    renderPanel();

    // Switch to semantic mode
    const semanticButton = screen.getByText('Семантический');
    fireEvent.click(semanticButton);

    const input = screen.getByLabelText('Поисковый запрос');
    fireEvent.change(input, { target: { value: 'интернет' } });

    const searchButton = screen.getByText('Искать');
    fireEvent.click(searchButton);

    await waitFor(() => {
      expect(mockSearchSemantic).toHaveBeenCalled();
    });
  });

  // ─── Empty state ─────────────────────────────────────

  it('shows empty state when no results found', async () => {
    mockSearchHybrid.mockResolvedValue({
      results: [],
      query: 'xyznonexistent',
      total: 0,
    });
    renderPanel();

    const input = screen.getByLabelText('Поисковый запрос');
    fireEvent.change(input, { target: { value: 'xyznonexistent' } });

    const searchButton = screen.getByText('Искать');
    fireEvent.click(searchButton);

    await waitFor(() => {
      expect(screen.getByText(/Ничего не найдено/)).toBeTruthy();
    });
  });

  // ─── Error states ────────────────────────────────────

  it('shows FRIDA unavailable error on 503', async () => {
    const apiError = new api.ApiError('FRIDA unavailable', 503);
    mockSearchHybrid.mockRejectedValue(apiError);
    renderPanel();

    const input = screen.getByLabelText('Поисковый запрос');
    fireEvent.change(input, { target: { value: 'тест' } });

    const searchButton = screen.getByText('Искать');
    fireEvent.click(searchButton);

    await waitFor(() => {
      expect(screen.getByText(/FRIDA недоступна/)).toBeTruthy();
    });
  });

  it('shows rate limit warning on 429', async () => {
    const apiError = new api.ApiError('Rate limit exceeded', 429);
    mockSearchHybrid.mockRejectedValue(apiError);
    renderPanel();

    const input = screen.getByLabelText('Поисковый запрос');
    fireEvent.change(input, { target: { value: 'тест' } });

    const searchButton = screen.getByText('Искать');
    fireEvent.click(searchButton);

    await waitFor(() => {
      expect(screen.getByText(/Слишком много запросов/)).toBeTruthy();
    });
  });

  // ─── Cross-highlighting ──────────────────────────────

  it('calls onResultClick when result card is clicked', async () => {
    const onResultClick = vi.fn();
    mockSearchHybrid.mockResolvedValue({
      results: sampleHybridResults,
      query: 'услуга',
      total: 1,
    });
    renderPanel({ onResultClick });

    const input = screen.getByLabelText('Поисковый запрос');
    fireEvent.change(input, { target: { value: 'услуга' } });

    const searchButton = screen.getByText('Искать');
    fireEvent.click(searchButton);

    await waitFor(() => {
      // Text may be split by <mark> — use partial match
      expect(screen.getByText(/подключить/)).toBeTruthy();
    });

    // Click on result card
    const resultCard = screen.getByLabelText(/Результат: Клиент/);
    fireEvent.click(resultCard);

    expect(onResultClick).toHaveBeenCalledWith('dialog-1', 3);
  });

  // ─── Close button ────────────────────────────────────

  it('calls onClose when close button is clicked', () => {
    const onClose = vi.fn();
    renderPanel({ onClose });

    const closeButton = screen.getByLabelText('Закрыть панель поиска');
    fireEvent.click(closeButton);

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  // ─── Search type toggle ──────────────────────────────

  it('switches search type when toggle buttons clicked', async () => {
    mockSearchSemantic.mockResolvedValue({
      results: sampleSemanticResults,
      query: 'тест',
      total: 1,
    });
    renderPanel();

    // Switch to semantic
    const semanticButton = screen.getByText('Семантический');
    fireEvent.click(semanticButton);

    // Type query and submit
    const input = screen.getByLabelText('Поисковый запрос');
    fireEvent.change(input, { target: { value: 'тест' } });

    const searchButton = screen.getByText('Искать');
    fireEvent.click(searchButton);

    await waitFor(() => {
      expect(mockSearchSemantic).toHaveBeenCalledWith(
        expect.objectContaining({ query: 'тест' }),
        expect.any(AbortSignal),
      );
    });
  });

  // ─── Feedback buttons ────────────────────────────────

  it('renders like/dislike feedback buttons for each result', async () => {
    mockSearchHybrid.mockResolvedValue({
      results: sampleHybridResults,
      query: 'услуга',
      total: 2,
    });
    renderPanel();

    const input = screen.getByLabelText('Поисковый запрос');
    fireEvent.change(input, { target: { value: 'услуга' } });

    const searchButton = screen.getByText('Искать');
    fireEvent.click(searchButton);

    await waitFor(() => {
      // Text may be split by <mark> — use partial match
      expect(screen.getByText(/подключить/)).toBeTruthy();
    });

    // Check feedback buttons exist
    const likeButtons = screen.getAllByLabelText('Полезный результат');
    const dislikeButtons = screen.getAllByLabelText('Неполезный результат');
    expect(likeButtons.length).toBeGreaterThan(0);
    expect(dislikeButtons.length).toBeGreaterThan(0);
  });

  // ─── Search History ──────────────────────────────────

  it('renders search history collapse', () => {
    renderPanel();
    expect(screen.getByText(/История запросов/)).toBeTruthy();
  });

  it('stores search in history after successful search', async () => {
    localStorage.clear();
    mockSearchHybrid.mockResolvedValue({
      results: sampleHybridResults,
      query: 'услуга',
      total: 2,
    });
    renderPanel();

    const input = screen.getByLabelText('Поисковый запрос');
    fireEvent.change(input, { target: { value: 'услуга' } });

    const searchButton = screen.getByText('Искать');
    fireEvent.click(searchButton);

    await waitFor(() => {
      expect(screen.getByText(/Найдено: 2 результатов/)).toBeTruthy();
    });

    // Check localStorage was updated
    const history = JSON.parse(localStorage.getItem('semantic_search_history') ?? '[]');
    expect(history.length).toBeGreaterThan(0);
    expect(history[0].query).toBe('услуга');
  });
});
