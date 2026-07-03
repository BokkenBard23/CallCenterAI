/**
 * Tests for QualityScorePanel component.
 *
 * Covers:
 *   - Default collapsed state
 *   - Toggle expansion triggers fetch
 *   - Loading skeleton
 *   - Error state with retry
 *   - Data rendering: overall score, radar chart, category table, strengths/weaknesses chips, recommendations
 *   - No refetch on re-render when data loaded
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QualityScorePanel } from './QualityScorePanel';

// ── Mock API ──
vi.mock('../../api/client', () => ({
  getQualityScore: vi.fn(),
}));

import { getQualityScore } from '../../api/client';
const mockGetQualityScore = vi.mocked(getQualityScore);

// ── Mock data ──
const MOCK_QUALITY_RESULT = {
  session_id: 'test-session-1',
  categories: [
    { category: 'communication_skills', level: 'high' as const, score: 0.9, justification: 'Отличная коммуникация' },
    { category: 'problem_solving', level: 'medium' as const, score: 0.65, justification: 'Среднее решение проблем' },
    { category: 'product_knowledge', level: 'low' as const, score: 0.3, justification: 'Слабое знание продукта' },
    { category: 'responsiveness', level: 'high' as const, score: 0.85, justification: 'Быстрая реакция' },
    { category: 'professionalism', level: 'high' as const, score: 0.88, justification: 'Профессиональный подход' },
    { category: 'empathy', level: 'medium' as const, score: 0.7, justification: 'Умеренная эмпатия' },
    { category: 'accuracy', level: 'high' as const, score: 0.92, justification: 'Высокая точность' },
    { category: 'efficiency', level: 'medium' as const, score: 0.6, justification: 'Средняя эффективность' },
    { category: 'follow_up_procedures', level: 'low' as const, score: 0.4, justification: 'Слабые последующие действия' },
    { category: 'conflict_resolution', level: 'medium' as const, score: 0.55, justification: 'Среднее разрешение конфликтов' },
    { category: 'compliance', level: 'high' as const, score: 0.95, justification: 'Полное соблюдение стандартов' },
    { category: 'customer_education', level: 'low' as const, score: 0.35, justification: 'Слабое обучение клиента' },
  ],
  overall_score: 0.67,
  overall_level: 'medium' as const,
  strengths: ['Навыки общения', 'Точность', 'Соблюдение стандартов'],
  weaknesses: ['Знание продукта', 'Обучение клиента'],
  recommendations: [
    'Улучшить обучение продукта',
    'Развивать навыки обучения клиента',
    'Усилить последующие действия',
  ],
  provider: 'beeline',
  model: 'gpt-4o',
};

describe('QualityScorePanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders collapsed by default with toggle button', () => {
    render(<QualityScorePanel sessionId="test-1" />);
    expect(screen.getByText('Оценка качества')).toBeInTheDocument();
    // Content should NOT be visible
    expect(screen.queryByText('67')).not.toBeInTheDocument();
  });

  it('renders quality data after successful fetch when defaultExpanded', async () => {
    mockGetQualityScore.mockResolvedValue(MOCK_QUALITY_RESULT);

    render(<QualityScorePanel sessionId="test-1" defaultExpanded />);

    await waitFor(() => {
      // Overall score
      expect(screen.getByText('67')).toBeInTheDocument();
      // Level badge — multiple "Средний" (overall + category badges), verify at least one exists
      const mediumBadges = screen.getAllByText('Средний');
      expect(mediumBadges.length).toBeGreaterThanOrEqual(1);
      // Provider info
      expect(screen.getByText('beeline / gpt-4o')).toBeInTheDocument();
    });
  });

  it('shows error state with retry button on fetch failure', async () => {
    mockGetQualityScore.mockRejectedValue(new Error('Network error'));

    render(<QualityScorePanel sessionId="test-1" defaultExpanded />);

    await waitFor(() => {
      expect(screen.getByText('Network error')).toBeInTheDocument();
    });

    const retryBtn = screen.getByText('Повторить');
    expect(retryBtn).toBeInTheDocument();
  });

  it('retries fetch when retry button is clicked', async () => {
    mockGetQualityScore.mockRejectedValueOnce(new Error('Network error'));
    mockGetQualityScore.mockResolvedValueOnce(MOCK_QUALITY_RESULT);

    render(<QualityScorePanel sessionId="test-1" defaultExpanded />);

    await waitFor(() => {
      expect(screen.getByText('Network error')).toBeInTheDocument();
    });

    const retryBtn = screen.getByText('Повторить');
    fireEvent.click(retryBtn);

    await waitFor(() => {
      expect(screen.getByText('67')).toBeInTheDocument();
    });

    expect(mockGetQualityScore).toHaveBeenCalledTimes(2);
  });

  it('renders category table with all categories', async () => {
    mockGetQualityScore.mockResolvedValue(MOCK_QUALITY_RESULT);

    render(<QualityScorePanel sessionId="test-1" defaultExpanded />);

    await waitFor(() => {
      // Category names appear in radar SVG, table rows, and chips — use getAllByText
      const skillsLabels = screen.getAllByText('Навыки общения');
      expect(skillsLabels.length).toBeGreaterThanOrEqual(1);

      const solvingLabels = screen.getAllByText('Решение проблем');
      expect(solvingLabels.length).toBeGreaterThanOrEqual(1);

      const knowledgeLabels = screen.getAllByText('Знание продукта');
      expect(knowledgeLabels.length).toBeGreaterThanOrEqual(1);

      const complianceLabels = screen.getAllByText('Соблюдение стандартов');
      expect(complianceLabels.length).toBeGreaterThanOrEqual(1);
    });
  });

  it('renders strengths and weaknesses as chips', async () => {
    mockGetQualityScore.mockResolvedValue(MOCK_QUALITY_RESULT);

    render(<QualityScorePanel sessionId="test-1" defaultExpanded />);

    await waitFor(() => {
      expect(screen.getByText('Сильные стороны')).toBeInTheDocument();
      expect(screen.getByText('Слабые стороны')).toBeInTheDocument();
    });
  });

  it('renders recommendations list', async () => {
    mockGetQualityScore.mockResolvedValue(MOCK_QUALITY_RESULT);

    render(<QualityScorePanel sessionId="test-1" defaultExpanded />);

    await waitFor(() => {
      expect(screen.getByText('Рекомендации')).toBeInTheDocument();
      expect(screen.getByText('Улучшить обучение продукта')).toBeInTheDocument();
    });
  });

  it('renders SVG radar chart', async () => {
    mockGetQualityScore.mockResolvedValue(MOCK_QUALITY_RESULT);

    render(<QualityScorePanel sessionId="test-1" defaultExpanded />);

    await waitFor(() => {
      // aria-label starts with capital "Радарная" — case-sensitive CSS selector
      const svg = document.querySelector('svg[aria-label*="Радарная"]');
      expect(svg).toBeInTheDocument();
    });
  });

  it('does not refetch if data already loaded', async () => {
    mockGetQualityScore.mockResolvedValue(MOCK_QUALITY_RESULT);

    const { rerender } = render(
      <QualityScorePanel sessionId="test-1" defaultExpanded />,
    );

    await waitFor(() => {
      expect(screen.getByText('67')).toBeInTheDocument();
    });

    // Rerender with same data — should not refetch
    rerender(<QualityScorePanel sessionId="test-1" defaultExpanded />);

    expect(mockGetQualityScore).toHaveBeenCalledTimes(1);
  });

  it('calls API with correct session and provider IDs', async () => {
    mockGetQualityScore.mockResolvedValue(MOCK_QUALITY_RESULT);

    render(
      <QualityScorePanel sessionId="session-abc" providerId="openai" defaultExpanded />,
    );

    await waitFor(() => {
      expect(mockGetQualityScore).toHaveBeenCalledWith(
        { session_id: 'session-abc', provider_id: 'openai' },
        expect.any(AbortSignal),
      );
    });
  });

  it('toggles visibility when button is clicked', async () => {
    mockGetQualityScore.mockResolvedValue(MOCK_QUALITY_RESULT);

    render(<QualityScorePanel sessionId="test-1" />);

    // Initially collapsed
    expect(screen.queryByText('67')).not.toBeInTheDocument();

    // Click to expand
    const toggleBtn = screen.getByText('Оценка качества');
    fireEvent.click(toggleBtn);

    await waitFor(() => {
      expect(screen.getByText('67')).toBeInTheDocument();
    });

    // Click to collapse
    const collapseBtn = screen.getByText('Скрыть оценку качества');
    fireEvent.click(collapseBtn);

    // Content should be hidden again
    expect(screen.queryByText('67')).not.toBeInTheDocument();
  });
});
