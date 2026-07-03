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
    name: 'TestDict',
    conditions: [],
    children: [],
    ...overrides,
  };
}

const sampleDictionaries: DictionaryNode[] = [
  makeDictionary({
    name: 'Угрозы',
    conditions: [
      { text: 'расторжение договора', channel_constraint: 'OPERATOR', is_exact: true, word_distance: 0 },
      { text: 'отказ', channel_constraint: 'CLIENT', is_exact: false, word_distance: 2 },
    ],
    children: [],
  }),
  makeDictionary({
    name: 'Приветствия',
    conditions: [
      { text: 'добрый день', channel_constraint: 'ANY', is_exact: false, word_distance: 1 },
    ],
    children: [],
  }),
];

const sampleSearchResult: SearchResult = {
  dialogue_id: 'd1',
  matches: [
    { phrase_text: 'расторжение договора', start: 0, end: 20, turn_index: 0, dict_name: 'Угрозы', channel: 'OPERATOR', word_distance: 0, dict_level: 1 },
    { phrase_text: 'расторжение договора', start: 50, end: 70, turn_index: 1, dict_name: 'Угрозы', channel: 'OPERATOR', word_distance: 0, dict_level: 1 },
    { phrase_text: 'отказ', start: 100, end: 105, turn_index: 2, dict_name: 'Угрозы', channel: 'CLIENT', word_distance: 2, dict_level: 1 },
  ],
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
        conditions: [{ text: 'тест', channel_constraint: 'ANY', is_exact: false, word_distance: 2 }],
        children: [],
      }),
      makeDictionary({
        name: 'Dict2',
        conditions: [{ text: 'тест', channel_constraint: 'OPERATOR', is_exact: true, word_distance: 0 }],
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
        conditions: [{ text: 'корень', channel_constraint: 'ANY', is_exact: false, word_distance: 2 }],
        children: [
          makeDictionary({
            name: 'Child',
            conditions: [{ text: 'потомок', channel_constraint: 'CLIENT', is_exact: false, word_distance: 1 }],
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
