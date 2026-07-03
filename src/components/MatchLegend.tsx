/**
 * MatchLegend — color legend for highlight depth levels with match counts.
 * Reads matches_by_level from SearchResult and renders swatches with counts.
 * When a tree node is selected (via HoverContext), dims non-matching levels
 * for visual consistency with the text highlights.
 * Level names come from HoverContext.levelNames (derived from dictionary data).
 */

import { useMemo } from 'react';
import { Stack, Typography } from '@beeline/design-system-react';

import type { SearchResult } from '../types/api';
import { useHoverContext } from '../context/HoverContext';

interface MatchLegendProps {
  searchResult: SearchResult | null;
}

/** Fallback depth names when dictionary data is unavailable */
const FALLBACK_DEPTH_NAMES: Record<string, string> = {
  '1': 'Глубина 1 — Критический',
  '2': 'Глубина 2 — Важный',
  '3': 'Глубина 3 — Умеренный',
  '4': 'Глубина 4 — Информационный',
  '5': 'Глубина 5 — Справочный',
  '6': 'Глубина 6',
};

export default function MatchLegend({ searchResult }: MatchLegendProps) {
  const { selectedTreeNodeId, levelNames } = useHoverContext();

  const levels = useMemo(() => {
    if (!searchResult?.matches) return [];

    // Count matches by cascade_order (mapped to depth)
    const countMap = new Map<number, number>();
    for (const match of searchResult.matches) {
      const depth = match.cascade_order <= 5 ? match.cascade_order : ((match.cascade_order - 1) % 5) + 1;
      countMap.set(depth, (countMap.get(depth) ?? 0) + 1);
    }

    return Array.from(countMap.entries())
      .sort(([a], [b]) => a - b)
      .map(([depth, count]) => ({
        depth,
        count,
        label: levelNames.has(depth)
          ? `Глубина ${depth} — ${levelNames.get(depth)}`
          : (FALLBACK_DEPTH_NAMES[String(depth)] ?? `Глубина ${depth}`),
      }));
  }, [searchResult, levelNames]);

  if (levels.length === 0) return null;

  return (
    <Stack direction="horizontal" spacing="x3" wrap="wrap" align="center">
      <Typography variant="caption" inactive>
        Легенда:
      </Typography>
      {levels.map(({ depth, count, label }) => {
        // Dim if a tree node is selected and this depth has no active phrases
        const isDimmed = selectedTreeNodeId !== null && !levels.some(l => l.depth === depth);

        return (
          <span
            key={depth}
            className="match-legend-item"
            style={{
              opacity: isDimmed ? 0.3 : 1,
              transition: 'opacity 0.2s ease',
            }}
          >
            <span
              className={`match-legend-swatch highlight-depth-${depth}`}
              role="img"
              aria-label={`${label}: ${count} совпадений`}
            />
            <Typography variant="caption">
              {label} ({count})
            </Typography>
          </span>
        );
      })}
    </Stack>
  );
}
