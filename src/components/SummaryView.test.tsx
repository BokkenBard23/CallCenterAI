/**
 * Tests for SummaryView — LLM analysis summary display.
 * Covers: no LLM result, full result, partial fields, sentiment/resolution badges,
 * key points, restructured dialogue integration.
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import SummaryView from './SummaryView';
import type { LLMResult, SearchResult } from '../types/api';

// ─── Fixtures ─────────────────────────────────────────────

const fullLlmResult: LLMResult = {
  summary: 'Диалог о расторжении договора.',
  restructured_dialogue: 'Клиент: Хочу расторгнуть\nСотрудник: Уточните причину',
  topic: 'Расторжение договора',
  result: 'Клиент не удовлетворён',
  key_points: ['Клиент хочет расторгнуть', 'Сотрудник предлагает альтернативу'],
  client_sentiment: 'negative',
  resolution: 'partial',
  provider: 'ollama',
  model: 'llama3',
};

const fullSearchResult: SearchResult = {
  segments: [
    { turn_index: 0, text: 'Привет', speaker: 'Клиент' },
    { turn_index: 1, text: 'Здравствуйте', speaker: 'Сотрудник' },
  ],
  total_matches: 3,
  matches: [],
  matches_by_level: { '1': 2, '2': 1 },
};

// ─── Tests ────────────────────────────────────────────────

describe('SummaryView', () => {
  // R-H1 FIX (vision-audit iter 3): canonical "LLM-сводка недоступна" status
  // lives HERE in SummaryView as the single consolidated card (heading +
  // cause subtitle + actionable hint). The page-level Banner was removed
  // to avoid the duplicate-status state-mix defect.
  it('shows consolidated LLM-unavailable card with heading when no LLM result', () => {
    render(<SummaryView llmResult={null} searchResult={null} />);
    expect(screen.getByText('LLM-сводка недоступна')).toBeTruthy();
    expect(screen.getByText(/Сводный анализ не выполнен/)).toBeTruthy();
  });

  it('shows hint about highlighted text tab when no LLM result', () => {
    render(<SummaryView llmResult={null} searchResult={null} />);
    expect(screen.getByText(/Выделенный текст/)).toBeTruthy();
  });

  it('shows "Анализ не выполнен" badge in LLM-unavailable state', () => {
    render(<SummaryView llmResult={null} searchResult={null} />);
    expect(screen.getByText('Анализ не выполнен')).toBeTruthy();
  });

  it('renders topic when present', () => {
    render(<SummaryView llmResult={fullLlmResult} searchResult={null} />);
    expect(screen.getByText('Расторжение договора')).toBeTruthy();
  });

  it('renders summary text', () => {
    render(<SummaryView llmResult={fullLlmResult} searchResult={null} />);
    expect(screen.getByText('Диалог о расторжении договора.')).toBeTruthy();
  });

  it('renders key points as list', () => {
    render(<SummaryView llmResult={fullLlmResult} searchResult={null} />);
    expect(screen.getByText('Клиент хочет расторгнуть')).toBeTruthy();
    expect(screen.getByText('Сотрудник предлагает альтернативу')).toBeTruthy();
  });

  it('renders result text', () => {
    render(<SummaryView llmResult={fullLlmResult} searchResult={null} />);
    expect(screen.getByText('Клиент не удовлетворён')).toBeTruthy();
  });

  it('renders provider/model caption', () => {
    render(<SummaryView llmResult={fullLlmResult} searchResult={null} />);
    expect(screen.getByText(/ollama/)).toBeTruthy();
    expect(screen.getByText(/llama3/)).toBeTruthy();
  });

  it('renders restructured dialogue section', () => {
    render(<SummaryView llmResult={fullLlmResult} searchResult={null} />);
    expect(screen.getByText('Реорганизованный диалог')).toBeTruthy();
  });

  it('renders match statistics when searchResult is present', () => {
    render(<SummaryView llmResult={fullLlmResult} searchResult={fullSearchResult} />);
    expect(screen.getByText(/Всего совпадений: 3/)).toBeTruthy();
    expect(screen.getByText(/Сегментов: 2/)).toBeTruthy();
  });

  it('does not render match statistics when no searchResult', () => {
    render(<SummaryView llmResult={fullLlmResult} searchResult={null} />);
    expect(screen.queryByText(/Всего совпадений/)).toBeNull();
  });

  it('renders section headings', () => {
    render(<SummaryView llmResult={fullLlmResult} searchResult={fullSearchResult} />);
    expect(screen.getByText('Сводка')).toBeTruthy();
    expect(screen.getByText('Ключевые моменты')).toBeTruthy();
    expect(screen.getByText('Результат')).toBeTruthy();
    expect(screen.getByText('Статистика совпадений')).toBeTruthy();
  });

  it('hides sections with empty data', () => {
    const minimalLlm: LLMResult = {
      ...fullLlmResult,
      summary: '',
      result: '',
      key_points: [],
      restructured_dialogue: '',
    };
    render(<SummaryView llmResult={minimalLlm} searchResult={null} />);

    // Summary and key points and result sections should not appear
    expect(screen.queryByText('Сводка')).toBeNull();
    expect(screen.queryByText('Ключевые моменты')).toBeNull();
    expect(screen.queryByText('Результат')).toBeNull();
    expect(screen.queryByText('Реорганизованный диалог')).toBeNull();
  });

  it('handles positive sentiment', () => {
    const positiveLlm: LLMResult = { ...fullLlmResult, client_sentiment: 'positive' };
    render(<SummaryView llmResult={positiveLlm} searchResult={null} />);
    expect(screen.getByText('Позитивный')).toBeTruthy();
  });

  it('handles mixed sentiment', () => {
    const mixedLlm: LLMResult = { ...fullLlmResult, client_sentiment: 'mixed' };
    render(<SummaryView llmResult={mixedLlm} searchResult={null} />);
    expect(screen.getByText('Смешанный')).toBeTruthy();
  });

  it('handles resolved resolution', () => {
    const resolvedLlm: LLMResult = { ...fullLlmResult, resolution: 'resolved' };
    render(<SummaryView llmResult={resolvedLlm} searchResult={null} />);
    expect(screen.getByText('Решён')).toBeTruthy();
  });

  it('handles escalated resolution', () => {
    const escalatedLlm: LLMResult = { ...fullLlmResult, resolution: 'escalated' };
    render(<SummaryView llmResult={escalatedLlm} searchResult={null} />);
    expect(screen.getByText('Эскалация')).toBeTruthy();
  });

  it('handles neutral sentiment fallback', () => {
    const neutralLlm: LLMResult = { ...fullLlmResult, client_sentiment: 'neutral' };
    render(<SummaryView llmResult={neutralLlm} searchResult={null} />);
    expect(screen.getByText('Нейтральный')).toBeTruthy();
  });

  it('handles unresolved resolution fallback', () => {
    const unresolvedLlm: LLMResult = { ...fullLlmResult, resolution: 'unresolved' };
    render(<SummaryView llmResult={unresolvedLlm} searchResult={null} />);
    expect(screen.getByText('Не решён')).toBeTruthy();
  });
});
