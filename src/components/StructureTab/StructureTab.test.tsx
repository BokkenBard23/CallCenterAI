/**
 * Tests for StructureTab — third ResultsPage tab ("Структура").
 * Covers: match counting per dictionary node, hierarchy rendering,
 * zero-match badge, empty states (no dictionaries / no matches).
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { StructureTab } from './StructureTab';
import type { DictionaryNode, SearchResult } from '../../types/api';

// ─── Fixtures ──────────────────────────────────────────────

function makeNode(overrides: Partial<DictionaryNode>): DictionaryNode {
  return {
    id: 'node',
    name: 'Node',
    parent_name: null,
    conditions: [],
    children: [],
    condition_count: 0,
    has_children: false,
    children_count: 0,
    ...overrides,
  };
}

const dictionaries: DictionaryNode[] = [
  makeNode({
    id: 'root-1',
    name: 'Риск расторжения',
    condition_count: 1,
    children: [
      makeNode({
        id: 'child-1',
        name: 'Уровень 2',
        parent_name: 'Риск расторжения',
        condition_count: 1,
      }),
    ],
  }),
  makeNode({
    id: 'root-2',
    name: 'sample_limitations',
    condition_count: 1,
  }),
];

// Conditions: root-1 has "задание не создано", child-1 has "перевод на ОСО",
// root-2 has "лимит исчерпан".
dictionaries[0].conditions = [
  {
    text: 'задание не создано',
    word_distance: 1,
    word_count: 3,
    channel_constraint: 'ANY',
    without_list: [],
    is_exact: false,
  },
];
dictionaries[0].children[0].conditions = [
  {
    text: 'перевод на ОСО',
    word_distance: 1,
    word_count: 3,
    channel_constraint: 'ANY',
    without_list: [],
    is_exact: false,
  },
];
dictionaries[1].conditions = [
  {
    text: 'лимит исчерпан',
    word_distance: 0,
    word_count: 2,
    channel_constraint: 'ANY',
    without_list: [],
    is_exact: false,
  },
];

const searchResult: SearchResult = {
  segments: [],
  total_matches: 3,
  matches: [
    {
      phrase_text: 'задание не создано',
      matched_text: 'задание не создано',
      matched_start: 0,
      matched_end: 10,
      quarter: 'Риск расторжения',
      turn_index: 0,
      speaker: 'Сотрудник',
      match_type: 'morph',
      word_distance_used: 1,
      cascade_order: 1,
      is_exact_match: false,
    },
    {
      phrase_text: 'перевод на ОСО',
      matched_text: 'перевод на ОСО',
      matched_start: 0,
      matched_end: 10,
      quarter: 'Уровень 2',
      turn_index: 1,
      speaker: 'Клиент',
      match_type: 'morph',
      word_distance_used: 1,
      cascade_order: 2,
      is_exact_match: false,
    },
    {
      phrase_text: 'перевод на ОСО',
      matched_text: 'перевод на ОСО',
      matched_start: 0,
      matched_end: 10,
      quarter: 'Уровень 2',
      turn_index: 4,
      speaker: 'Клиент',
      match_type: 'morph',
      word_distance_used: 1,
      cascade_order: 2,
      is_exact_match: false,
    },
  ],
  matches_by_level: { '1': 1, '2': 2 },
};

// ─── Tests ──────────────────────────────────────────────────

describe('StructureTab', () => {
  it('renders dictionary names from the tree', () => {
    render(<StructureTab dictionaries={dictionaries} searchResult={searchResult} />);
    expect(screen.getByText('Риск расторжения')).toBeTruthy();
    expect(screen.getByText('Уровень 2')).toBeTruthy();
    expect(screen.getByText('sample_limitations')).toBeTruthy();
  });

  it('counts matches per node (root-1=1, child-1=2, root-2=0)', () => {
    render(<StructureTab dictionaries={dictionaries} searchResult={searchResult} />);
    expect(screen.getByText('1 совп.')).toBeTruthy();
    expect(screen.getByText('2 совп.')).toBeTruthy();
    expect(screen.getByText('нет')).toBeTruthy();
  });

  it('shows total matches badge', () => {
    render(<StructureTab dictionaries={dictionaries} searchResult={searchResult} />);
    expect(screen.getByText('3')).toBeTruthy();
  });

  it('shows empty state when no dictionaries are loaded', () => {
    render(<StructureTab dictionaries={[]} searchResult={searchResult} />);
    expect(screen.getByText('Словари не загружены')).toBeTruthy();
  });

  it('shows info alert when there are no matches but dictionaries exist', () => {
    const emptyResult: SearchResult = {
      segments: [],
      total_matches: 0,
      matches: [],
      matches_by_level: {},
    };
    render(<StructureTab dictionaries={dictionaries} searchResult={emptyResult} />);
    expect(
      screen.getByText(/Совпадений не найдено — отображается полная структура/),
    ).toBeTruthy();
  });

  it('handles null searchResult without crashing', () => {
    render(<StructureTab dictionaries={dictionaries} searchResult={null} />);
    expect(screen.getByText('Риск расторжения')).toBeTruthy();
    expect(screen.getByText('0')).toBeTruthy();
  });
});
