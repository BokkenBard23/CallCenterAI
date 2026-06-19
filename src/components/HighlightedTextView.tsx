/**
 * HighlightedTextView — container that renders text segments with highlights.
 * Groups segments by turn, shows speaker labels, and hides segments
 * without matches when hideNoMatch is enabled.
 *
 * Enhancement (Chunk 2): subscribes to HoverContext.
 * When user hovers on a match <mark>, the parent segment detects the hover
 * and sets hoveredPhrase in HoverContext.
 */

import { useMemo, useState, useCallback } from 'react';
import {
  Box,
  Card,
  Collapse,
  Stack,
  Typography,
} from '@beeline/design-system-react';

import type { SearchResult, DictMatch } from '../types/api';
import { useHoverContext } from '../context/HoverContext';
import HighlightRenderer from './HighlightRenderer';
import MatchLegend from './MatchLegend';

interface HighlightedTextViewProps {
  searchResult: SearchResult | null;
  hideNoMatch: boolean;
}

/** Russian plural form for "совпадение" */
function pluralMatchCount(count: number): string {
  const abs = Math.abs(count) % 100;
  const lastDigit = abs % 10;
  if (abs > 10 && abs < 20) return 'совпадений';
  if (lastDigit > 1 && lastDigit < 5) return 'совпадения';
  if (lastDigit === 1) return 'совпадение';
  return 'совпадений';
}

export default function HighlightedTextView({
  searchResult,
  hideNoMatch,
}: HighlightedTextViewProps) {
  const { setHoveredPhrase } = useHoverContext();

  // Track expanded state for collapsed (no-match) segments
  const [expandedSegments, setExpandedSegments] = useState<Set<number>>(
    new Set(),
  );

  const toggleExpanded = useCallback((turnIndex: number) => {
    setExpandedSegments((prev) => {
      const next = new Set(prev);
      if (next.has(turnIndex)) {
        next.delete(turnIndex);
      } else {
        next.add(turnIndex);
      }
      return next;
    });
  }, []);

  // ─── Group matches by turn_index ──────────────────────
  const matchesByTurn = useMemo(() => {
    if (!searchResult) return new Map<number, DictMatch[]>();
    const map = new Map<number, DictMatch[]>();
    for (const match of searchResult.matches) {
      const existing = map.get(match.turn_index) ?? [];
      existing.push(match);
      map.set(match.turn_index, existing);
    }
    return map;
  }, [searchResult]);

  // ─── Hover handler for match marks ──────────────────
  // When user hovers over a <mark data-phrase="..."> element,
  // extract the phrase and set it in HoverContext.
  const handleSegmentMouseOver = useCallback(
    (e: React.MouseEvent) => {
      const target = e.target as HTMLElement;
      if (target.tagName === 'MARK' && target instanceof HTMLElement) {
        const phrase = target.getAttribute('data-phrase');
        if (phrase) {
          setHoveredPhrase(phrase);
        }
      }
    },
    [setHoveredPhrase],
  );

  const handleSegmentMouseOut = useCallback(
    (e: React.MouseEvent) => {
      const target = e.target as HTMLElement;
      if (target.tagName === 'MARK' && target instanceof HTMLElement) {
        // Only clear if we're actually leaving the mark
        const relatedTarget = e.relatedTarget as HTMLElement | null;
        if (!relatedTarget || !target.contains(relatedTarget)) {
          setHoveredPhrase(null);
        }
      }
    },
    [setHoveredPhrase],
  );

  // ─── No results state ─────────────────────────────────
  if (!searchResult || searchResult.segments.length === 0) {
    return (
      <Card>
        <Box padding="x6">
          <Typography variant="body1" inactive>
            Нет данных для отображения.
          </Typography>
        </Box>
      </Card>
    );
  }

  return (
    <Stack direction="vertical" spacing="x4">
      {/* ── Legend ── */}
      <MatchLegend searchResult={searchResult} />

      {/* ── Segments ── */}
      <Stack direction="vertical" spacing="x2">
        {searchResult.segments.map((segment) => {
          const turnMatches = matchesByTurn.get(segment.turn_index) ?? [];
          const hasMatches = turnMatches.length > 0;

          // If hiding no-match segments, collapse them
          if (hideNoMatch && !hasMatches) {
            const isExpanded = expandedSegments.has(segment.turn_index);
            return (
              <div key={segment.turn_index}>
                <Collapse
                  expanded={isExpanded}
                  onToggle={() => toggleExpanded(segment.turn_index)}
                  labelCollapsed={`Реплика ${segment.turn_index + 1} (${segment.speaker}) — показать`}
                  labelExpanded={`Реплика ${segment.turn_index + 1} (${segment.speaker}) — скрыть`}
                  size="small"
                >
                  <div
                    className="segment-card"
                    data-speaker={segment.speaker}
                    onMouseOver={handleSegmentMouseOver}
                    onMouseOut={handleSegmentMouseOut}
                  >
                    <div className="segment-speaker">
                      {segment.speaker}
                    </div>
                    <HighlightRenderer
                      text={segment.text}
                      matches={turnMatches}
                    />
                  </div>
                </Collapse>
              </div>
            );
          }

          return (
            <div
              key={segment.turn_index}
              className="segment-card"
              data-speaker={segment.speaker}
              onMouseOver={handleSegmentMouseOver}
              onMouseOut={handleSegmentMouseOut}
            >
              <div className="segment-speaker">{segment.speaker}</div>
              <HighlightRenderer
                text={segment.text}
                matches={turnMatches}
              />
              {hasMatches && (
                <Typography variant="caption" inactive>
                  {turnMatches.length}{' '}
                  {pluralMatchCount(turnMatches.length)}
                </Typography>
              )}
            </div>
          );
        })}
      </Stack>
    </Stack>
  );
}
