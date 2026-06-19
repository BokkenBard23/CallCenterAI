/**
 * DictionaryPhraseItem — one phrase row in the Dictionary sidebar.
 *
 * STRICT Display Rules (INV-D1 — do NOT modify):
 *   DR-1: is_exact === true  → phrase in guillemet quotes: «phrase»
 *   DR-2: word_distance === 0 → bold font (fontWeight: 600)
 *   DR-3: channel_constraint → color dot/text (OPERATOR=green, CLIENT=blue, ANY=orange)
 *   DR-4: matchCount         → "— N совп." right-aligned; muted at 0
 *
 * DR-1 + DR-2 combine: is_exact=true && word_distance=0 → **«phrase»** (bold + quotes)
 */

import React, { useCallback } from 'react';
import { Box, Counter, Stack, Typography } from '@beeline/design-system-react';

import type { DictionaryCondition } from '../types/api';
import { useHoverContext } from '../context/HoverContext';

// ═══════════════════════════════════════════════════════════
// Channel color mapping (DR-3)
// ═══════════════════════════════════════════════════════════

type ChannelConstraint = 'OPERATOR' | 'CLIENT' | 'ANY';

function getChannelCssVar(channel: string): string {
  switch (channel as ChannelConstraint) {
    case 'OPERATOR':
      return 'var(--dict-channel-operator)';
    case 'CLIENT':
      return 'var(--dict-channel-client)';
    case 'ANY':
      return 'var(--dict-channel-any)';
    default:
      // Unknown channel fallback → neutral
      return 'var(--color-status-neutral, #9e9e9e)';
  }
}

/** Russian plural form for "совпадение" */
function pluralMatchCount(count: number): string {
  const abs = Math.abs(count) % 100;
  const lastDigit = abs % 10;
  if (abs > 10 && abs < 20) return 'совп.';
  if (lastDigit > 1 && lastDigit < 5) return 'совп.';
  if (lastDigit === 1) return 'совп.';
  return 'совп.';
}

// ═══════════════════════════════════════════════════════════
// Props
// ═══════════════════════════════════════════════════════════

interface DictionaryPhraseItemProps {
  condition: DictionaryCondition;
  matchCount: number;
}

// ═══════════════════════════════════════════════════════════
// Component
// ═══════════════════════════════════════════════════════════

const DictionaryPhraseItem = React.memo(function DictionaryPhraseItem({
  condition,
  matchCount,
}: DictionaryPhraseItemProps) {
  const { hoveredPhrase, setHoveredPhrase } = useHoverContext();

  const isHovered = hoveredPhrase === condition.text;

  // DR-1: Quotes for exact match
  const displayText = condition.is_exact
    ? `\u00AB${condition.text}\u00BB`  // «phrase»
    : condition.text;

  // DR-2: Bold for word_distance === 0
  const fontWeight = condition.word_distance === 0 ? 600 : 400;

  // DR-3: Channel color
  const channelColor = getChannelCssVar(condition.channel_constraint);

  // Hover handlers
  const handleMouseEnter = useCallback(() => {
    setHoveredPhrase(condition.text);
  }, [setHoveredPhrase, condition.text]);

  const handleMouseLeave = useCallback(() => {
    setHoveredPhrase(null);
  }, [setHoveredPhrase]);

  return (
    <Box
      className="dict-phrase-item"
      data-hovered={isHovered ? 'true' : undefined}
      padding="x2"
      style={{
        borderLeft: isHovered
          ? `3px solid ${channelColor}`
          : '3px solid transparent',
        backgroundColor: isHovered
          ? 'var(--color-background-base-hover, rgba(0,0,0,0.04))'
          : 'transparent',
        transition: 'background-color 150ms ease, border-left-color 150ms ease',
        cursor: 'pointer',
        minHeight: '44px', // Touch target ≥ 44px
      }}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      role="listitem"
      aria-label={`${condition.text}, ${condition.channel_constraint}, ${matchCount} ${pluralMatchCount(matchCount)}`}
    >
      <Stack direction="horizontal" spacing="x2" align="center" justify="space-between">
        <Stack direction="horizontal" spacing="x2" align="center">
          {/* DR-3: Channel color dot */}
          <span
            className="dict-channel-dot"
            style={{
              display: 'inline-block',
              width: '8px',
              height: '8px',
              borderRadius: '50%',
              backgroundColor: channelColor,
              flexShrink: 0,
            }}
            aria-hidden="true"
          />

          {/* Phrase text with DR-1 (quotes) + DR-2 (bold) */}
          <Typography
            variant="body2"
            style={{ fontWeight }}
            inactive={matchCount === 0}
          >
            {displayText}
          </Typography>
        </Stack>

        {/* DR-4: Match count */}
        {matchCount > 0 ? (
          <Counter count={matchCount} size="small" />
        ) : (
          <Typography variant="caption" inactive>
            0 {pluralMatchCount(0)}
          </Typography>
        )}
      </Stack>
    </Box>
  );
});

export default DictionaryPhraseItem;
