/**
 * Tests for HighlightedTextView — segment container with Collapse, MatchLegend, match counts.
 * Covers: empty state, segments with/without matches, hideNoMatch toggle, level map building.
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import HighlightedTextView from './HighlightedTextView';
import type { SearchResult, DictMatch } from '../types/api';
import { HoverContextWrapper } from '../test/HoverContextWrapper';

// ─── Fixtures ─────────────────────────────────────────────

function makeMatch(overrides: Partial<DictMatch> & { phrase_text: string }): DictMatch {
  return {
    matched_text: overrides.matched_text ?? overrides.phrase_text ?? '',
    matched_start: -1,
    matched_end: -1,
    turn_index: 0,
    speaker: 'Клиент',
    match_type: 'exact',
    word_distance_used: 1,
    quarter: 'Словарь',
    cascade_order: 1,
    is_exact_match: true,
    ...overrides,
  };
}

/** Render with HoverContextWrapper so useHoverContext() works */
function renderWithHover(ui: React.ReactElement) {
  return render(ui, { wrapper: HoverContextWrapper });
}

const searchResultWithMatches: SearchResult = {
  segments: [
    { turn_index: 0, text: 'Клиент хочет расторгнуть договор', speaker: 'Клиент' },
    { turn_index: 1, text: 'Сотрудник предлагает альтернативу', speaker: 'Сотрудник' },
  ],
  total_matches: 2,
  matches: [
    makeMatch({ phrase_text: 'расторгнуть', word_distance_used: 1, turn_index: 0, speaker: 'Клиент' }),
    makeMatch({ phrase_text: 'предлагает', word_distance_used: 2, turn_index: 1, speaker: 'Сотрудник' }),
  ],
  matches_by_level: { '1': 1, '2': 1 },
};

const searchResultNoMatches: SearchResult = {
  segments: [
    { turn_index: 0, text: 'Привет', speaker: 'Клиент' },
  ],
  total_matches: 0,
  matches: [],
  matches_by_level: {},
};

// ─── Tests ────────────────────────────────────────────────

describe('HighlightedTextView', () => {
  it('shows empty state when searchResult is null', () => {
    renderWithHover(<HighlightedTextView searchResult={null} hideNoMatch={false} />);
    expect(screen.getByText('Нет данных для отображения.')).toBeTruthy();
  });

  it('shows empty state when segments are empty', () => {
    const emptyResult: SearchResult = {
      segments: [],
      total_matches: 0,
      matches: [],
      matches_by_level: {},
    };
    renderWithHover(<HighlightedTextView searchResult={emptyResult} hideNoMatch={false} />);
    expect(screen.getByText('Нет данных для отображения.')).toBeTruthy();
  });

  it('renders segments with speaker labels', () => {
    renderWithHover(
      <HighlightedTextView
        searchResult={searchResultWithMatches}
        hideNoMatch={false}
      />,
    );

    const cards = document.querySelectorAll('.segment-card');
    expect(cards).toHaveLength(2);
    expect(cards[0].getAttribute('data-speaker')).toBe('Клиент');
    expect(cards[1].getAttribute('data-speaker')).toBe('Сотрудник');
  });

  it('renders match count for segments with matches', () => {
    renderWithHover(
      <HighlightedTextView
        searchResult={searchResultWithMatches}
        hideNoMatch={false}
      />,
    );

    // Both segments have 1 match each → two "1 совпадение" texts
    const matchCounts = screen.getAllByText('1 совпадение');
    expect(matchCounts).toHaveLength(2);
  });

  it('renders MatchLegend', () => {
    renderWithHover(
      <HighlightedTextView
        searchResult={searchResultWithMatches}
        hideNoMatch={false}
      />,
    );

    expect(screen.getByText('Легенда:')).toBeTruthy();
  });

  it('renders highlights in segments', () => {
    const { container } = renderWithHover(
      <HighlightedTextView
        searchResult={searchResultWithMatches}
        hideNoMatch={false}
      />,
    );

    // Should have highlight spans
    const highlights = container.querySelectorAll('.highlight-match');
    expect(highlights.length).toBeGreaterThanOrEqual(1);
  });

  it('shows collapsed segments without matches when hideNoMatch=true', () => {
    const mixedResult: SearchResult = {
      segments: [
        { turn_index: 0, text: 'Совпадение здесь', speaker: 'Клиент' },
        { turn_index: 1, text: 'Нет совпадений', speaker: 'Сотрудник' },
      ],
      total_matches: 1,
      matches: [
        makeMatch({ phrase_text: 'Совпадение', word_distance_used: 1, turn_index: 0, speaker: 'Клиент' }),
      ],
      matches_by_level: { '1': 1 },
    };

    renderWithHover(
      <HighlightedTextView searchResult={mixedResult} hideNoMatch={true} />,
    );

    // No-match segment should be wrapped in Collapse
    // The Collapse component renders its label
    expect(screen.getByText(/Реплика 2.*показать/)).toBeTruthy();
  });

  it('does not collapse segments without matches when hideNoMatch=false', () => {
    const mixedResult: SearchResult = {
      segments: [
        { turn_index: 0, text: 'Совпадение здесь', speaker: 'Клиент' },
        { turn_index: 1, text: 'Нет совпадений', speaker: 'Сотрудник' },
      ],
      total_matches: 1,
      matches: [
        makeMatch({ phrase_text: 'Совпадение', word_distance_used: 1, turn_index: 0, speaker: 'Клиент' }),
      ],
      matches_by_level: { '1': 1 },
    };

    const { container } = renderWithHover(
      <HighlightedTextView searchResult={mixedResult} hideNoMatch={false} />,
    );

    // All segments rendered as cards (not collapsed)
    const cards = container.querySelectorAll('.segment-card');
    expect(cards).toHaveLength(2);
  });

  it('handles searchResult with no matches in segments', () => {
    renderWithHover(
      <HighlightedTextView
        searchResult={searchResultNoMatches}
        hideNoMatch={false}
      />,
    );

    const cards = document.querySelectorAll('.segment-card');
    expect(cards).toHaveLength(1);
    // No match count text
    expect(screen.queryByText(/совпадение/)).toBeNull();
  });
});
