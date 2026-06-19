/**
 * MatchLegend — color legend for highlight levels with match counts.
 * Reads matches_by_level from SearchResult and renders swatches with counts.
 */

import { useMemo } from 'react';
import { Stack, Typography } from '@beeline/design-system-react';

import type { SearchResult } from '../types/api';

interface MatchLegendProps {
  searchResult: SearchResult | null;
}

/** Level display names */
const LEVEL_NAMES: Record<string, string> = {
  '1': 'Уровень 1',
  '2': 'Уровень 2',
  '3': 'Уровень 3',
  '4': 'Уровень 4',
  '5': 'Уровень 5',
  '6': 'Уровень 6',
};

export default function MatchLegend({ searchResult }: MatchLegendProps) {
  const levels = useMemo(() => {
    if (!searchResult?.matches_by_level) return [];
    return Object.entries(searchResult.matches_by_level)
      .sort(([a], [b]) => Number(a) - Number(b))
      .map(([level, count]) => ({
        level,
        count,
        label: LEVEL_NAMES[level] ?? `Уровень ${level}`,
      }));
  }, [searchResult]);

  if (levels.length === 0) return null;

  return (
    <Stack direction="horizontal" spacing="x3" wrap="wrap" align="center">
      <Typography variant="caption" inactive>
        Легенда:
      </Typography>
      {levels.map(({ level, count, label }) => (
        <span key={level} className="match-legend-item">
          <span
            className={`match-legend-swatch highlight-level-${level}`}
            role="img"
            aria-label={`${label}: ${count} совпадений`}
          />
          <Typography variant="caption">
            {label} ({count})
          </Typography>
        </span>
      ))}
    </Stack>
  );
}
