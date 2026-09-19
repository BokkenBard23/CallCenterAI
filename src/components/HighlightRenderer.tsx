/**
 * HighlightRenderer — core highlight rendering with nested color-coded spans.
 * Algorithm: "Segment Split with Innermost Color"
 *   - Innermost match = background color
 *   - Outer matches = border pattern (color-blindness-friendly)
 *   - Uses matched_text + matched_start/matched_end from backend for
 *     reliable positioning (no indexOf guesswork)
 *
 * Display Rules (DR-1/DR-2/DR-3):
 *   DR-1: is_exact_match → guillemet quotes «» around matched text
 *   DR-2: word_distance === 0 → bold (fontWeight 600)
 *   DR-3: channel_constraint → CLIENT=blue, OPERATOR=light blue, ANY=default
 *
 * P0-2 Rework: Depth-based colors (5 levels) instead of Q1/Q2/Q3 levels.
 * P0-1 Rework: Dim/bright filtering uses activePhrases Set instead of selectedDictLevel.
 * P0-3 Rework: Hover → DS Tooltip with brief info; Click → PhrasePopover.
 */

import { useMemo, useCallback, useState, useRef } from 'react';
import { Tooltip } from '@beeline/design-system-react';

import type { DictMatch } from '../types/api';
import { useHoverContext } from '../context/HoverContext';

import './highlight.scss';

interface HighlightRendererProps {
  text: string;
  matches: DictMatch[];
}

/** A range within the text that should be highlighted */
interface HighlightRange {
  start: number;
  end: number;
  /** depth level (1-5) — maps to highlight-depth-N CSS classes */
  depth: number;
  match: DictMatch;
}

/** A chunk of text to render — either plain or highlighted */
interface TextChunk {
  type: 'plain' | 'highlighted';
  text: string;
  depth: number;
  isInnermost: boolean;
  match: DictMatch | null;
}

/** Map cascade_order to depth (1-5, cycling if > 5) */
function cascadeToDepth(cascadeOrder: number): number {
  if (cascadeOrder <= 5) return cascadeOrder;
  return ((cascadeOrder - 1) % 5) + 1;
}

/**
 * Build sorted, non-overlapping highlight ranges from matches.
 * Uses depth-based classification instead of flat Q-levels.
 */
function buildRanges(
  text: string,
  matches: DictMatch[],
): HighlightRange[] {
  const ranges: HighlightRange[] = [];

  for (const match of matches) {
    let start = -1;
    let end = -1;

    if (match.matched_start >= 0 && match.matched_end >= 0) {
      start = match.matched_start;
      end = match.matched_end;
    } else if (match.matched_text) {
      start = text.indexOf(match.matched_text);
      if (start >= 0) {
        end = start + match.matched_text.length;
      }
    } else {
      start = text.indexOf(match.phrase_text);
      if (start >= 0) {
        end = start + match.phrase_text.length;
      }
    }

    if (start < 0 || end < 0 || start >= text.length || end > text.length) {
      continue;
    }

    ranges.push({
      start,
      end,
      depth: cascadeToDepth(match.cascade_order),
      match,
    });
  }

  ranges.sort((a, b) => {
    if (a.start !== b.start) return a.start - b.start;
    return a.end - b.end;
  });

  return ranges;
}

/**
 * Split text into chunks based on highlight ranges.
 */
function splitIntoChunks(
  text: string,
  ranges: HighlightRange[],
): TextChunk[] {
  if (ranges.length === 0) {
    return [{ type: 'plain', text, depth: 0, isInnermost: false, match: null }];
  }

  const chunks: TextChunk[] = [];
  const points = new Set<number>();
  points.add(0);
  points.add(text.length);
  for (const r of ranges) {
    points.add(r.start);
    points.add(r.end);
  }
  const sortedPoints = Array.from(points).sort((a, b) => a - b);

  for (let i = 0; i < sortedPoints.length - 1; i++) {
    const start = sortedPoints[i];
    const end = sortedPoints[i + 1];
    const chunkText = text.slice(start, end);

    if (!chunkText) continue;

    const coveringRanges = ranges.filter(
      (r) => r.start <= start && r.end >= end,
    );

    if (coveringRanges.length === 0) {
      chunks.push({
        type: 'plain',
        text: chunkText,
        depth: 0,
        isInnermost: false,
        match: null,
      });
    } else {
      // IP-1.5 e2e fix (2026-09-19): when several matches cover the same chunk
      // (e.g. an exact_match and a morphological match of the same phrase with
      // identical spans), the previous `coveringRanges[last]` pick silently
      // dropped the DR-1 `highlight-exact` indicator whenever the morphological
      // match came later in the matches array. Among the innermost ranges
      // (same end), prefer an exact match so the DR-1 class is preserved.
      // Nested/non-overlapping behavior is unchanged.
      const innermostCandidate = coveringRanges[coveringRanges.length - 1];
      const innermostSet = coveringRanges.filter(
        (r) => r.end === innermostCandidate.end,
      );
      const exactRange = innermostSet.find((r) => r.match.is_exact_match);
      const innermost = exactRange ?? innermostCandidate;
      chunks.push({
        type: 'highlighted',
        text: chunkText,
        depth: innermost.depth,
        isInnermost: true,
        match: innermost.match,
      });
    }
  }

  return chunks;
}

/** Get DR-3 channel CSS variable for a match */
function getMatchChannelColor(match: DictMatch | null): string {
  if (!match) return 'var(--color-status-neutral, #9e9e9e)';
  const channel = match.channel_constraint?.toUpperCase();
  if (channel === 'CLIENT') return 'var(--dict-channel-client, #1e88e5)';
  if (channel === 'OPERATOR') return 'var(--dict-channel-operator, #64b5f6)';
  if (channel === 'ANY' || channel) return 'var(--dict-channel-any)';
  const speaker = match.speaker?.toLowerCase() ?? '';
  if (speaker.includes('сотрудник') || speaker.includes('operator')) return 'var(--dict-channel-operator)';
  if (speaker.includes('клиент') || speaker.includes('client')) return 'var(--dict-channel-client)';
  return 'var(--dict-channel-any)';
}

/** Depth name for Tooltip display */
const DEPTH_NAMES: Record<number, string> = {
  1: 'Критический',
  2: 'Важный',
  3: 'Умеренный',
  4: 'Информационный',
  5: 'Справочный',
};

/** Channel label for Tooltip */
function getChannelLabel(channel: string | undefined): string {
  switch (channel?.toUpperCase()) {
    case 'CLIENT': return 'Клиент';
    case 'OPERATOR': return 'Сотрудник';
    case 'ANY': return 'Любой';
    default: return channel ?? '—';
  }
}

/** Distance label for Tooltip */
function getDistanceLabel(distance: number | undefined): string {
  if (distance === undefined) return '—';
  if (distance === 0) return 'смежные';
  return `${distance} ${distance === 1 ? 'пропуск' : distance < 5 ? 'пропуска' : 'пропусков'}`;
}

/** Build tooltip text for a match (P0-3) */
function buildTooltipText(match: DictMatch): string {
  const depthName = DEPTH_NAMES[cascadeToDepth(match.cascade_order)] ?? `Глубина ${match.cascade_order}`;
  const channelLabel = getChannelLabel(match.channel_constraint);
  const distanceLabel = getDistanceLabel(match.word_distance);
  return `\u00AB${match.phrase_text}\u00BB · ${depthName} · Канал: ${channelLabel} · ${distanceLabel}`;
}

export default function HighlightRenderer({
  text,
  matches,
}: HighlightRendererProps) {
  const {
    hoveredPhrase,
    selectedTreeNodeId,
    activePhrases,
    hoveredTreeNodeId,
    setHoveredPhrase,
  } = useHoverContext();

  // P0-3: Tooltip hover state with 300ms delay
  const [hoveredMarkKey, setHoveredMarkKey] = useState<string | null>(null);
  const [tooltipVisible, setTooltipVisible] = useState(false);
  const hoverTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const chunks = useMemo(
    () => {
      const ranges = buildRanges(text, matches);
      return splitIntoChunks(text, ranges);
    },
    [text, matches],
  );

  // P0-3: 300ms delayed tooltip show
  const handleMarkMouseEnter = useCallback((markKey: string) => {
    setHoveredMarkKey(markKey);
    if (hoverTimerRef.current !== null) {
      clearTimeout(hoverTimerRef.current);
    }
    hoverTimerRef.current = setTimeout(() => {
      setTooltipVisible(true);
      hoverTimerRef.current = null;
    }, 300);
  }, []);

  const handleMarkMouseLeave = useCallback(() => {
    if (hoverTimerRef.current !== null) {
      clearTimeout(hoverTimerRef.current);
      hoverTimerRef.current = null;
    }
    setTooltipVisible(false);
    setHoveredMarkKey(null);
  }, []);

  return (
    <span className="segment-text">
      {chunks.map((chunk, idx) => {
        if (chunk.type === 'plain') {
          return <span key={idx}>{chunk.text}</span>;
        }

        // P0-2: Use depth-based CSS classes
        const depthClass = chunk.isInnermost
          ? `highlight-match highlight-depth-${chunk.depth}`
          : `highlight-match highlight-depth-${chunk.depth}-outer`;

        // Cross-highlighting: add 'highlight-hovered' class when phrase matches
        const isHovered = chunk.match
          ? hoveredPhrase === chunk.match.phrase_text
          : false;

        // P0-1: Dim/bright based on activePhrases (tree node selection)
        const isInActivePhrases = chunk.match
          ? activePhrases.size === 0 || activePhrases.has(chunk.match.phrase_text)
          : true;
        const isDimmed = selectedTreeNodeId !== null
          && chunk.match !== null
          && !isInActivePhrases;

        // When a tree node is selected, matching highlights get glow
        const isSelectedNode = selectedTreeNodeId !== null
          && chunk.match !== null
          && isInActivePhrases;

        // Cross-highlighting: tree node hover → outline on matching phrases
        const isTreeHovered = hoveredTreeNodeId !== null
          && chunk.match !== null
          && isInActivePhrases;

        const displayText = chunk.text;

        // DR-2: word_distance === 0 → bold
        const isAdjacent = chunk.match?.word_distance === 0;

        // DR-3: channel_constraint → text color
        const channelColor = getMatchChannelColor(chunk.match);

        // Build class names
        const drClasses: string[] = [];
        if (chunk.match?.is_exact_match) drClasses.push('highlight-exact');
        if (isAdjacent) drClasses.push('highlight-adjacent');
        if (chunk.match?.channel_constraint === 'CLIENT') drClasses.push('highlight-channel-client');
        else if (chunk.match?.channel_constraint === 'OPERATOR') drClasses.push('highlight-channel-operator');
        if (isDimmed) drClasses.push('highlight-dim');
        if (isSelectedNode) drClasses.push('highlight-selected-node');
        if (isTreeHovered) drClasses.push('highlight-tree-hovered');

        const fullClassName = `${depthClass}${isHovered ? ' highlight-hovered' : ''}${drClasses.length > 0 ? ` ${drClasses.join(' ')}` : ''}`;

        // Build inline styles
        const markStyle: React.CSSProperties = {};
        if (isAdjacent) {
          markStyle.fontWeight = 600;
        }
        if (chunk.match?.channel_constraint && chunk.match.channel_constraint !== 'ANY') {
          markStyle.color = channelColor;
        }
        if (isHovered) {
          markStyle.outlineColor = channelColor;
        }

        // Unique key for tooltip management
        const markKey = chunk.match ? `${chunk.match.phrase_text}-${chunk.match.turn_index}-${idx}` : `plain-${idx}`;
        const isTooltipTarget = hoveredMarkKey === markKey && tooltipVisible;

        const mark = (
          <mark
            key={idx}
            className={fullClassName}
            data-phrase={chunk.match?.phrase_text}
            data-dict={chunk.match?.quarter}
            data-depth={chunk.depth}
            data-cascade-order={chunk.match?.cascade_order}
            tabIndex={0}
            aria-label={
              chunk.match
                ? `${chunk.match.phrase_text}, глубина ${chunk.depth}`
                : undefined
            }
            onClick={(e: React.MouseEvent) => {
              e.stopPropagation();
              // Dispatch custom event for ResultsPage PhrasePopover
              const event = new CustomEvent('highlight-click', {
                detail: {
                  phrase: chunk.match?.phrase_text,
                  cascadeOrder: chunk.match?.cascade_order,
                  element: e.currentTarget,
                },
                bubbles: true,
                composed: true,
              });
              e.currentTarget.dispatchEvent(event);
            }}
            onMouseEnter={() => {
              handleMarkMouseEnter(markKey);
              // Cross-highlighting: set hovered phrase
              if (chunk.match) {
                setHoveredPhrase(chunk.match.phrase_text);
              }
            }}
            onMouseLeave={() => {
              handleMarkMouseLeave();
              // Clear cross-highlighting
              setHoveredPhrase(null);
            }}
            style={Object.keys(markStyle).length > 0 ? markStyle : undefined}
          >
            {displayText}
          </mark>
        );

        // P0-3: Wrap in Tooltip for hover preview
        // Wrap <mark> in <span> so Tooltip can attach ref to a stable host element
        if (chunk.match) {
          return (
            <Tooltip
              key={idx}
              title={buildTooltipText(chunk.match)}
              open={isTooltipTarget}
              triggerMode="hover"
              closeMode="outside-click"
              placement="top"
              disableHover
              transitionDuration={{ enter: 100, exit: 50 }}
            >
              <span>{mark}</span>
            </Tooltip>
          );
        }

        return mark;
      })}
    </span>
  );
}
