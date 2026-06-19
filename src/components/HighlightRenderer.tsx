/**
 * HighlightRenderer — core highlight rendering with nested color-coded spans.
 * Algorithm: "Segment Split with Innermost Color"
 *   - Innermost match = background color
 *   - Outer matches = border pattern (color-blindness-friendly)
 *   - Uses matched_text + matched_start/matched_end from backend for
 *     reliable positioning (no indexOf guesswork)
 *   - Falls back to matched_text indexOf if offsets are -1
 *
 * Display Rules (DR-1/DR-2/DR-3):
 *   DR-1: is_exact_match → guillemet quotes «» around matched text
 *   DR-2: word_distance === 0 → bold (fontWeight 600)
 *   DR-3: channel_constraint → CLIENT=blue, OPERATOR=light blue, ANY=default
 *   DR-1+DR-2+DR-3 COMBINE
 *
 * Enhancement (Chunk 2): subscribes to HoverContext for cross-highlighting
 * and selectedDictLevel for dim/bright filtering.
 * When hoveredPhrase matches match.phrase_text, adds 'highlight-hovered' CSS class.
 * When selectedDictLevel is set, non-matching levels get 'highlight-dim' CSS class.
 */

import { useMemo } from 'react';
import { Tooltip } from '@beeline/design-system-react';

import type { DictMatch } from '../types/api';
import { useHoverContext } from '../context/HoverContext';

interface HighlightRendererProps {
  text: string;
  matches: DictMatch[];
}

/** A range within the text that should be highlighted */
interface HighlightRange {
  start: number;
  end: number;
  level: string;
  match: DictMatch;
}

/** A chunk of text to render — either plain or highlighted */
interface TextChunk {
  type: 'plain' | 'highlighted';
  text: string;
  level: string;
  isInnermost: boolean;
  match: DictMatch | null;
}

/**
 * Build sorted, non-overlapping highlight ranges from matches.
 * When ranges overlap, all are kept but innermost/outermost is determined later.
 *
 * Position resolution strategy:
 * 1. If matched_start/matched_end are provided (>= 0), use them directly
 * 2. Otherwise, fall back to indexOf(matched_text) then indexOf(phrase_text)
 */
function buildRanges(
  text: string,
  matches: DictMatch[],
): HighlightRange[] {
  const ranges: HighlightRange[] = [];

  for (const match of matches) {
    let start = -1;
    let end = -1;

    // Strategy 1: Use backend-computed character offsets
    if (match.matched_start >= 0 && match.matched_end >= 0) {
      start = match.matched_start;
      end = match.matched_end;
    }
    // Strategy 2: Find matched_text in the turn text
    else if (match.matched_text) {
      start = text.indexOf(match.matched_text);
      if (start >= 0) {
        end = start + match.matched_text.length;
      }
    }
    // Strategy 3: Last resort — find phrase_text
    else {
      start = text.indexOf(match.phrase_text);
      if (start >= 0) {
        end = start + match.phrase_text.length;
      }
    }

    if (start < 0 || end < 0 || start >= text.length || end > text.length) {
      continue; // Cannot locate this match in the text
    }

    // Backend encodes hierarchy level in word_distance_used (see search.py line 160)
    ranges.push({
      start,
      end,
      level: String(match.word_distance_used),
      match,
    });
  }

  // Sort by start position, then by length (shorter = innermost)
  ranges.sort((a, b) => {
    if (a.start !== b.start) return a.start - b.start;
    return a.end - b.end;
  });

  return ranges;
}

/**
 * Split text into chunks based on highlight ranges.
 * Determines innermost vs outer for overlapping regions.
 */
function splitIntoChunks(
  text: string,
  ranges: HighlightRange[],
): TextChunk[] {
  if (ranges.length === 0) {
    return [{ type: 'plain', text, level: '', isInnermost: false, match: null }];
  }

  const chunks: TextChunk[] = [];

  // Collect all boundary points
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

    // Find which ranges cover this chunk
    const coveringRanges = ranges.filter(
      (r) => r.start <= start && r.end >= end,
    );

    if (coveringRanges.length === 0) {
      chunks.push({
        type: 'plain',
        text: chunkText,
        level: '',
        isInnermost: false,
        match: null,
      });
    } else {
      // Innermost = smallest range (most specific)
      const innermost = coveringRanges[coveringRanges.length - 1];
      chunks.push({
        type: 'highlighted',
        text: chunkText,
        level: innermost.level,
        isInnermost: true,
        match: innermost.match,
      });
    }
  }

  return chunks;
}

/** Format match details for tooltip */
function formatMatchTooltip(match: DictMatch): string {
  const lines = [
    `Фраза словаря: ${match.phrase_text}`,
  ];
  // Show matched text if different from phrase
  if (match.matched_text && match.matched_text !== match.phrase_text) {
    lines.push(`Совпадение в тексте: ${match.matched_text}`);
  }
  lines.push(
    `Словарь: ${match.quarter}`,
    `Уровень: ${match.word_distance_used}`,
  );
  // DR-3: channel
  if (match.channel_constraint && match.channel_constraint !== 'ANY') {
    const channelLabel = match.channel_constraint === 'CLIENT' ? 'Клиент' : 'Сотрудник';
    lines.push(`Канал: ${channelLabel}`);
  }
  // DR-2: word_distance
  if (match.word_distance !== undefined) {
    const distLabel = match.word_distance === 0 ? 'смежные' : `${match.word_distance} пропусков`;
    lines.push(`Расстояние: ${match.word_distance} (${distLabel})`);
  }
  // DR-1: exact
  if (match.is_exact_match) {
    lines.push('Точное совпадение: да');
  }
  return lines.join('\n');
}

/** Get DR-3 channel CSS variable for a match */
function getMatchChannelColor(match: DictMatch | null): string {
  if (!match) return 'var(--color-status-neutral, #9e9e9e)';
  // Use channel_constraint if available (DR-3), otherwise derive from speaker
  const channel = match.channel_constraint?.toUpperCase();
  if (channel === 'CLIENT') {
    return 'var(--dict-channel-client, #1e88e5)';
  }
  if (channel === 'OPERATOR') {
    return 'var(--dict-channel-operator, #64b5f6)';
  }
  if (channel === 'ANY' || channel) {
    return 'var(--dict-channel-any)';
  }
  // Fallback: derive from speaker
  const speaker = match.speaker?.toLowerCase() ?? '';
  if (speaker.includes('сотрудник') || speaker.includes('operator')) {
    return 'var(--dict-channel-operator)';
  }
  if (speaker.includes('клиент') || speaker.includes('client')) {
    return 'var(--dict-channel-client)';
  }
  return 'var(--dict-channel-any)';
}

export default function HighlightRenderer({
  text,
  matches,
}: HighlightRendererProps) {
  const { hoveredPhrase, selectedDictLevel } = useHoverContext();

  const chunks = useMemo(
    () => {
      const ranges = buildRanges(text, matches);
      return splitIntoChunks(text, ranges);
    },
    [text, matches],
  );

  return (
    <span className="segment-text">
      {chunks.map((chunk, idx) => {
        if (chunk.type === 'plain') {
          return <span key={idx}>{chunk.text}</span>;
        }

        const levelClass = chunk.isInnermost
          ? `highlight-match highlight-level-${chunk.level}`
          : `highlight-match highlight-level-${chunk.level}-outer`;

        // Cross-highlighting: add 'highlight-hovered' class when phrase matches
        const isHovered = chunk.match
          ? hoveredPhrase === chunk.match.phrase_text
          : false;

        // DR-1: Exact match → guillemet quotes
        const isExact = chunk.match?.is_exact_match === true;
        const displayText = isExact
          ? `\u00AB${chunk.text}\u00BB`
          : chunk.text;

        // DR-2: word_distance === 0 → bold
        const isAdjacent = chunk.match?.word_distance === 0;

        // DR-3: channel_constraint → text color
        const channelColor = getMatchChannelColor(chunk.match);

        // Chunk 2: Dim/bright based on selectedDictLevel
        const isDimmed = selectedDictLevel !== null
          && chunk.match !== null
          && chunk.match.cascade_order !== selectedDictLevel;

        // Build class names
        const drClasses: string[] = [];
        if (isExact) drClasses.push('highlight-exact');
        if (isAdjacent) drClasses.push('highlight-adjacent');
        if (chunk.match?.channel_constraint === 'CLIENT') drClasses.push('highlight-channel-client');
        else if (chunk.match?.channel_constraint === 'OPERATOR') drClasses.push('highlight-channel-operator');
        if (isDimmed) drClasses.push('highlight-dim');

        const fullClassName = `${levelClass}${isHovered ? ' highlight-hovered' : ''}${drClasses.length > 0 ? ` ${drClasses.join(' ')}` : ''}`;

        // Build inline styles
        const markStyle: React.CSSProperties = {};
        if (isAdjacent) {
          markStyle.fontWeight = 600;
        }
        // DR-3: channel text color (only if channel is not ANY)
        if (chunk.match?.channel_constraint && chunk.match.channel_constraint !== 'ANY') {
          markStyle.color = channelColor;
        }
        // Hovered outline color
        if (isHovered) {
          markStyle.outlineColor = channelColor;
        }

        const mark = (
          <mark
            key={idx}
            className={fullClassName}
            data-phrase={chunk.match?.phrase_text}
            data-dict={chunk.match?.quarter}
            data-level={chunk.level}
            data-cascade-order={chunk.match?.cascade_order}
            tabIndex={0}
            aria-label={
              chunk.match
                ? `${chunk.match.phrase_text}, уровень ${chunk.level}`
                : undefined
            }
            style={Object.keys(markStyle).length > 0 ? markStyle : undefined}
          >
            {displayText}
          </mark>
        );

        // Wrap with Tooltip if we have match details
        if (chunk.match) {
          return (
            <Tooltip
              key={idx}
              title={formatMatchTooltip(chunk.match)}
              placement="top"
              triggerMode="hover"
            >
              {mark}
            </Tooltip>
          );
        }

        return mark;
      })}
    </span>
  );
}
