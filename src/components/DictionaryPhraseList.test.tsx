/**
 * Tests for DictionaryPhraseList — sidebar list of all dictionary phrases.
 */

import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import DictionaryPhraseList from './DictionaryPhraseList';
import { HoverProvider } from '../context/HoverContext';
import type { DictionaryNode, SearchResult } from '../types/api';

/** Render with HoverProvider (DictionaryPhraseItem uses useHoverContext) */
function renderWithProviders(ui: React.ReactElement) {
  return render(<HoverProvider>{ui}</HoverProvider>);
}

// ═══════════════════════════════════════════════════════════
// Test fixtures
// ═══════════════════════════════════════════════════════════

function makeDictionary(overrides: Partial<DictionaryNode> = {}): DictionaryNode {
  return {
    id: 'test-id',
    name: 'TestDict',
    parent_name: null,
    conditions: [],
    children: [],
    condition_count: 0,
    has_children: false,
    children_count: 0,
    ...overrides,
  };
}

const sampleDictionaries: DictionaryNode[] = [
  makeDictionary({
    name: 'Угрозы',
    conditions: [
      { text: 'расторжение договора', channel_constraint: 'OPERATOR', is_exact: true, word_distance: 0, word_count: 2, without_list: [] },
      { text: 'отказ', channel_constraint: 'CLIENT', is_exact: false, word_distance: 2, word_count: 1, without_list: [] },
    ],
    children: [],
  }),
  makeDictionary({
    name: 'Приветствия',
    conditions: [
      { text: 'добрый день', channel_constraint: 'ANY', is_exact: false, word_distance: 1, word_count: 2, without_list: [] },
    ],
    children: [],
  }),
];

const sampleSearchResult: SearchResult = {
  segments: [],
  total_matches: 3,
  matches: [
    { phrase_text: 'расторжение договора', matched_text: 'расторжение договора', matched_start: 0, matched_end: 20, quarter: 'Угрозы', turn_index: 0, speaker: 'OPERATOR', match_type: 'phrase', word_distance_used: 0, cascade_order: 1, is_exact_match: true, channel_constraint: 'OPERATOR', word_distance: 0, dict_level: 1 },
    { phrase_text: 'расторжение договора', matched_text: 'расторжение договора', matched_start: 50, matched_end: 70, quarter: 'Угрозы', turn_index: 1, speaker: 'OPERATOR', match_type: 'phrase', word_distance_used: 0, cascade_order: 1, is_exact_match: true, channel_constraint: 'OPERATOR', word_distance: 0, dict_level: 1 },
    { phrase_text: 'отказ', matched_text: 'отказ', matched_start: 100, matched_end: 105, quarter: 'Угрозы', turn_index: 2, speaker: 'CLIENT', match_type: 'phrase', word_distance_used: 2, cascade_order: 1, is_exact_match: false, channel_constraint: 'CLIENT', word_distance: 2, dict_level: 1 },
  ],
  matches_by_level: { '1': 3 },
};

// ═══════════════════════════════════════════════════════════
// Tests
// ═══════════════════════════════════════════════════════════

describe('DictionaryPhraseList', () => {
  it('renders "Словари не загружены" when no dictionaries', () => {
    renderWithProviders(<DictionaryPhraseList dictionaries={[]} searchResult={null} />);
    expect(screen.getByText('Словари не загружены')).toBeInTheDocument();
  });

  it('renders "Нет фраз в словаре" when dictionaries have no conditions', () => {
    const emptyDicts = [makeDictionary({ conditions: [] })];
    renderWithProviders(<DictionaryPhraseList dictionaries={emptyDicts} searchResult={null} />);
    expect(screen.getByText('Нет фраз в словаре')).toBeInTheDocument();
  });

  it('renders all unique conditions as phrase items', () => {
    renderWithProviders(<DictionaryPhraseList dictionaries={sampleDictionaries} searchResult={null} />);
    // 3 unique conditions: "расторжение договора", "отказ", "добрый день"
    expect(screen.getByText(/расторжение договора/)).toBeInTheDocument();
    expect(screen.getByText('отказ')).toBeInTheDocument();
    expect(screen.getByText('добрый день')).toBeInTheDocument();
  });

  it('shows phrase count in header', () => {
    renderWithProviders(<DictionaryPhraseList dictionaries={sampleDictionaries} searchResult={null} />);
    expect(screen.getByText(/Фраз: 3/)).toBeInTheDocument();
  });

  it('shows total match count from search result', () => {
    renderWithProviders(<DictionaryPhraseList dictionaries={sampleDictionaries} searchResult={sampleSearchResult} />);
    // 3 total matches
    expect(screen.getByText(/Совпадений: 3/)).toBeInTheDocument();
  });

  it('shows 0 matches when no search result', () => {
    renderWithProviders(<DictionaryPhraseList dictionaries={sampleDictionaries} searchResult={null} />);
    expect(screen.getByText(/Совпадений: 0/)).toBeInTheDocument();
  });

  it('deduplicates conditions by text across dictionaries', () => {
    const dupDicts: DictionaryNode[] = [
      makeDictionary({
        name: 'Dict1',
        conditions: [{ text: 'тест', channel_constraint: 'ANY', is_exact: false, word_distance: 2, word_count: 1, without_list: [] }],
        children: [],
      }),
      makeDictionary({
        name: 'Dict2',
        conditions: [{ text: 'тест', channel_constraint: 'OPERATOR', is_exact: true, word_distance: 0, word_count: 1, without_list: [] }],
        children: [],
      }),
    ];
    renderWithProviders(<DictionaryPhraseList dictionaries={dupDicts} searchResult={null} />);
    // Only one "тест" should appear (deduped by text)
    const testItems = screen.getAllByText(/тест/).filter(el => el.closest('[role="listitem"]'));
    expect(testItems.length).toBe(1);
    // Phrase count should be 1
    expect(screen.getByText(/Фраз: 1/)).toBeInTheDocument();
  });

  it('renders with complementary role', () => {
    const { container } = renderWithProviders(<DictionaryPhraseList dictionaries={sampleDictionaries} searchResult={null} />);
    expect(container.querySelector('[role="complementary"]')).toBeInTheDocument();
  });

  it('handles nested dictionary conditions via children', () => {
    const nestedDicts: DictionaryNode[] = [
      makeDictionary({
        name: 'Root',
        conditions: [{ text: 'корень', channel_constraint: 'ANY', is_exact: false, word_distance: 2, word_count: 1, without_list: [] }],
        children: [
          makeDictionary({
            name: 'Child',
            conditions: [{ text: 'потомок', channel_constraint: 'CLIENT', is_exact: false, word_distance: 1, word_count: 1, without_list: [] }],
            children: [],
          }),
        ],
      }),
    ];
    renderWithProviders(<DictionaryPhraseList dictionaries={nestedDicts} searchResult={null} />);
    expect(screen.getByText(/корень/)).toBeInTheDocument();
    expect(screen.getByText('потомок')).toBeInTheDocument();
    expect(screen.getByText(/Фраз: 2/)).toBeInTheDocument();
  });
});
