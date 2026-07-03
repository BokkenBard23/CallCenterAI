/**
 * Tests for FoundRecordsTab — search results display.
 * Covers: no-search state, loading, empty results, loaded results, error state.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import FoundRecordsTab from './FoundRecordsTab';
import type { SearchResult, TextSegment } from '../../../types/api';

const sampleSegments: TextSegment[] = [
  { turn_index: 0, text: 'Здравствуйте, чем могу помочь?', speaker: 'Оператор' },
  { turn_index: 1, text: 'Я хочу переключиться на другого оператора', speaker: 'Клиент' },
];

const sampleSearchResult: SearchResult = {
  segments: sampleSegments,
  total_matches: 2,
  matches: [
    {
      phrase_text: 'переключиться',
      matched_text: 'переключиться',
      matched_start: 7,
      matched_end: 21,
      quarter: 'Словарь 1',
      turn_index: 1,
      speaker: 'Клиент',
      match_type: 'morph_bow',
      word_distance_used: 0,
      cascade_order: 1,
      is_exact_match: true,
      channel_constraint: 'CLIENT',
    },
  ],
  matches_by_level: { '1': 1 },
};

describe('FoundRecordsTab', () => {
  it('renders "Запустите анализ" when no search started', () => {
    render(
      <FoundRecordsTab
        searchResult={null}
        isSearching={false}
        error={null}
        onRunAnalysis={() => {}}
        segments={[]}
      />
    );
    expect(screen.getByText('Запустите анализ для поиска фраз в диалогах')).toBeInTheDocument();
    expect(screen.getByText('Найти')).toBeInTheDocument();
  });

  it('renders loading state', () => {
    render(
      <FoundRecordsTab
        searchResult={null}
        isSearching={true}
        error={null}
        onRunAnalysis={() => {}}
        segments={[]}
      />
    );
    expect(screen.getByText('Поиск фраз...')).toBeInTheDocument();
  });

  it('renders error state', () => {
    render(
      <FoundRecordsTab
        searchResult={null}
        isSearching={false}
        error="Сетевая ошибка"
        onRunAnalysis={() => {}}
        segments={[]}
      />
    );
    expect(screen.getByText(/Ошибка: Сетевая ошибка/)).toBeInTheDocument();
  });

  it('renders empty results when search returned 0 matches', () => {
    const emptyResult: SearchResult = {
      segments: [],
      total_matches: 0,
      matches: [],
      matches_by_level: {},
    };
    render(
      <FoundRecordsTab
        searchResult={emptyResult}
        isSearching={false}
        error={null}
        onRunAnalysis={() => {}}
        segments={sampleSegments}
      />
    );
    expect(screen.getByText('Фразы не найдены в загруженных диалогах')).toBeInTheDocument();
  });

  it('renders results with matched segments', () => {
    render(
      <FoundRecordsTab
        searchResult={sampleSearchResult}
        isSearching={false}
        error={null}
        onRunAnalysis={() => {}}
        segments={sampleSegments}
      />
    );
    expect(screen.getByText(/Найдено:/)).toBeInTheDocument();
  });

  it('calls onRunAnalysis when "Найти" button is clicked', () => {
    const onRun = vi.fn();
    render(
      <FoundRecordsTab
        searchResult={null}
        isSearching={false}
        error={null}
        onRunAnalysis={onRun}
        segments={[]}
      />
    );
    fireEvent.click(screen.getByText('Найти'));
    expect(onRun).toHaveBeenCalledTimes(1);
  });
});
