/**
 * Tests for MatchLegend — color legend for highlight levels.
 * Covers: no search result, levels sorted, level names, counts, aria-labels.
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import MatchLegend from './MatchLegend';
import type { SearchResult } from '../types/api';

// ─── Fixtures ─────────────────────────────────────────────

const searchResultWithLevels: SearchResult = {
  segments: [],
  total_matches: 5,
  matches: [],
  matches_by_level: { '1': 2, '2': 3 },
};

const searchResultEmpty: SearchResult = {
  segments: [],
  total_matches: 0,
  matches: [],
  matches_by_level: {},
};

// ─── Tests ────────────────────────────────────────────────

describe('MatchLegend', () => {
  it('renders nothing when searchResult is null', () => {
    const { container } = render(<MatchLegend searchResult={null} />);
    expect(container.innerHTML).toBe('');
  });

  it('renders nothing when matches_by_level is empty', () => {
    const { container } = render(<MatchLegend searchResult={searchResultEmpty} />);
    expect(container.innerHTML).toBe('');
  });

  it('renders level swatches with correct counts', () => {
    render(<MatchLegend searchResult={searchResultWithLevels} />);

    expect(screen.getByText(/Уровень 1/)).toBeTruthy();
    expect(screen.getByText(/Уровень 2/)).toBeTruthy();
    expect(screen.getByText(/\(2\)/)).toBeTruthy(); // level 1 count
    expect(screen.getByText(/\(3\)/)).toBeTruthy(); // level 2 count
  });

  it('renders "Легенда:" label', () => {
    render(<MatchLegend searchResult={searchResultWithLevels} />);
    expect(screen.getByText('Легенда:')).toBeTruthy();
  });

  it('sorts levels numerically', () => {
    const unsortedResult: SearchResult = {
      segments: [],
      total_matches: 6,
      matches: [],
      matches_by_level: { '3': 1, '1': 3, '2': 2 },
    };

    const { container } = render(<MatchLegend searchResult={unsortedResult} />);
    const labels = container.querySelectorAll('.match-legend-item');

    // Should be sorted: 1, 2, 3
    expect(labels).toHaveLength(3);
    expect(labels[0].textContent).toContain('Уровень 1');
    expect(labels[1].textContent).toContain('Уровень 2');
    expect(labels[2].textContent).toContain('Уровень 3');
  });

  it('adds aria-label to swatches for accessibility', () => {
    render(<MatchLegend searchResult={searchResultWithLevels} />);

    const swatch = screen.getByRole('img', { name: /Уровень 1.*2 совпадений/ });
    expect(swatch).toBeTruthy();
  });

  it('renders level 4+ with correct names', () => {
    const extendedResult: SearchResult = {
      segments: [],
      total_matches: 1,
      matches: [],
      matches_by_level: { '4': 1 },
    };

    render(<MatchLegend searchResult={extendedResult} />);
    expect(screen.getByText(/Уровень 4/)).toBeTruthy();
  });

  it('renders unknown level with fallback name', () => {
    const weirdResult: SearchResult = {
      segments: [],
      total_matches: 1,
      matches: [],
      matches_by_level: { '99': 1 },
    };

    render(<MatchLegend searchResult={weirdResult} />);
    expect(screen.getByText(/Уровень 99/)).toBeTruthy();
  });
});
