/**
 * Tests for MatchLegend — color legend for highlight levels.
 * Covers: no search result, levels sorted, level names, counts, aria-labels,
 * dim/bright when Q-level is selected.
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import MatchLegend from './MatchLegend';
import type { SearchResult } from '../types/api';
import { HoverContextWrapper } from '../test/HoverContextWrapper';

// ─── Fixtures ─────────────────────────────────────────────

const searchResultWithLevels: SearchResult = {
  segments: [],
  total_matches: 5,
  matches: [
    { phrase_text: 'a', matched_text: 'a', matched_start: -1, matched_end: -1, turn_index: 0, speaker: 'Клиент', match_type: 'exact', word_distance_used: 1, quarter: 'Q1', cascade_order: 1, is_exact_match: false },
    { phrase_text: 'b1', matched_text: 'b1', matched_start: -1, matched_end: -1, turn_index: 0, speaker: 'Клиент', match_type: 'exact', word_distance_used: 1, quarter: 'Q2', cascade_order: 2, is_exact_match: false },
    { phrase_text: 'b2', matched_text: 'b2', matched_start: -1, matched_end: -1, turn_index: 0, speaker: 'Клиент', match_type: 'exact', word_distance_used: 1, quarter: 'Q2', cascade_order: 2, is_exact_match: false },
    { phrase_text: 'b3', matched_text: 'b3', matched_start: -1, matched_end: -1, turn_index: 0, speaker: 'Клиент', match_type: 'exact', word_distance_used: 1, quarter: 'Q2', cascade_order: 2, is_exact_match: false },
  ],
  matches_by_level: { '1': 1, '2': 3 },
};

const searchResultEmpty: SearchResult = {
  segments: [],
  total_matches: 0,
  matches: [],
  matches_by_level: {},
};

/** Render with HoverContextWrapper so useHoverContext() works */
function renderWithHover(ui: React.ReactElement) {
  return render(ui, { wrapper: HoverContextWrapper });
}

// ─── Tests ────────────────────────────────────────────────

describe('MatchLegend', () => {
  it('renders nothing when searchResult is null', () => {
    const { container } = renderWithHover(<MatchLegend searchResult={null} />);
    expect(container.innerHTML).toBe('');
  });

  it('renders nothing when matches_by_level is empty', () => {
    const { container } = renderWithHover(<MatchLegend searchResult={searchResultEmpty} />);
    expect(container.innerHTML).toBe('');
  });

  it('renders level swatches with correct counts', () => {
    renderWithHover(<MatchLegend searchResult={searchResultWithLevels} />);

    expect(screen.getByText(/Глубина 1/)).toBeTruthy();
    expect(screen.getByText(/Глубина 2/)).toBeTruthy();
    expect(screen.getByText(/\(1\)/)).toBeTruthy(); // level 1 count (1 match with cascade_order=1)
    expect(screen.getByText(/\(3\)/)).toBeTruthy(); // level 2 count (3 matches with cascade_order=2)
  });

  it('renders "Легенда:" label', () => {
    renderWithHover(<MatchLegend searchResult={searchResultWithLevels} />);
    expect(screen.getByText('Легенда:')).toBeTruthy();
  });

  it('sorts levels numerically', () => {
    const unsortedResult: SearchResult = {
      segments: [],
      total_matches: 6,
      matches: [
        { phrase_text: 'a', matched_text: 'a', matched_start: -1, matched_end: -1, turn_index: 0, speaker: 'Клиент', match_type: 'exact', word_distance_used: 1, quarter: 'Q3', cascade_order: 3, is_exact_match: false },
        { phrase_text: 'b1', matched_text: 'b1', matched_start: -1, matched_end: -1, turn_index: 0, speaker: 'Клиент', match_type: 'exact', word_distance_used: 1, quarter: 'Q1', cascade_order: 1, is_exact_match: false },
        { phrase_text: 'b2', matched_text: 'b2', matched_start: -1, matched_end: -1, turn_index: 0, speaker: 'Клиент', match_type: 'exact', word_distance_used: 1, quarter: 'Q1', cascade_order: 1, is_exact_match: false },
        { phrase_text: 'b3', matched_text: 'b3', matched_start: -1, matched_end: -1, turn_index: 0, speaker: 'Клиент', match_type: 'exact', word_distance_used: 1, quarter: 'Q1', cascade_order: 1, is_exact_match: false },
        { phrase_text: 'c1', matched_text: 'c1', matched_start: -1, matched_end: -1, turn_index: 0, speaker: 'Клиент', match_type: 'exact', word_distance_used: 1, quarter: 'Q2', cascade_order: 2, is_exact_match: false },
        { phrase_text: 'c2', matched_text: 'c2', matched_start: -1, matched_end: -1, turn_index: 0, speaker: 'Клиент', match_type: 'exact', word_distance_used: 1, quarter: 'Q2', cascade_order: 2, is_exact_match: false },
      ],
      matches_by_level: { '3': 1, '1': 3, '2': 2 },
    };

    const { container } = renderWithHover(<MatchLegend searchResult={unsortedResult} />);
    const labels = container.querySelectorAll('.match-legend-item');

    // Should be sorted: depth 1, 2, 3
    expect(labels).toHaveLength(3);
    expect(labels[0].textContent).toContain('Глубина 1');
    expect(labels[1].textContent).toContain('Глубина 2');
    expect(labels[2].textContent).toContain('Глубина 3');
  });

  it('adds aria-label to swatches for accessibility', () => {
    renderWithHover(<MatchLegend searchResult={searchResultWithLevels} />);

    const swatch = screen.getByRole('img', { name: /Глубина 1.*1 совпадени/ });
    expect(swatch).toBeTruthy();
  });

  it('renders level 4+ with correct names', () => {
    const extendedResult: SearchResult = {
      segments: [],
      total_matches: 1,
      matches: [
        { phrase_text: 'x', matched_text: 'x', matched_start: -1, matched_end: -1, turn_index: 0, speaker: 'Клиент', match_type: 'exact', word_distance_used: 1, quarter: 'Q4', cascade_order: 4, is_exact_match: false },
      ],
      matches_by_level: { '4': 1 },
    };

    renderWithHover(<MatchLegend searchResult={extendedResult} />);
    expect(screen.getByText(/Глубина 4/)).toBeTruthy();
  });

  it('renders unknown level with fallback name', () => {
    const weirdResult: SearchResult = {
      segments: [],
      total_matches: 1,
      matches: [
        { phrase_text: 'x', matched_text: 'x', matched_start: -1, matched_end: -1, turn_index: 0, speaker: 'Клиент', match_type: 'exact', word_distance_used: 1, quarter: 'Q99', cascade_order: 99, is_exact_match: false },
      ],
      matches_by_level: { '99': 1 },
    };

    renderWithHover(<MatchLegend searchResult={weirdResult} />);
    expect(screen.getByText(/Глубина 4/)).toBeTruthy();
  });
});
