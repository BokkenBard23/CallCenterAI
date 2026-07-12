/**
 * ConfidenceBadge — reusable semantic badge for LLM confidence labels.
 *
 * Mapping (ChannelTag.tsx pattern, anti-clone: DS semantic tokens, NOT CSS):
 *   relevant   → Badge semantic="success"
 *   irrelevant → Badge semantic="danger"
 *   uncertain  → Badge semantic="warning"
 *
 * When `reason` is supplied, wraps Badge in a DS Tooltip (hover, top placement)
 * to expose the one-sentence LLM justification on the FN list rows.
 *
 * Pattern source: ChannelTag.tsx (channel→semantic color).
 * DS component: Badge (semantic, dot). Tooltip (triggerMode="hover", placement="top").
 */

import { memo } from 'react';
import { Badge, Tooltip, type BadgeSemantic } from '@beeline/design-system-react';
import type { ConfidenceLabel } from '../../../types/api';

const SEMANTIC_BY_LABEL: Record<ConfidenceLabel, BadgeSemantic> = {
  relevant: 'success',
  irrelevant: 'danger',
  uncertain: 'warning',
};

const LABEL_TEXT: Record<ConfidenceLabel, string> = {
  relevant: 'relevant',
  irrelevant: 'irrelevant',
  uncertain: 'uncertain',
};

export interface ConfidenceBadgeProps {
  /** LLM confidence label (relevant | irrelevant | uncertain). */
  label: ConfidenceLabel;
  /** Vector similarity score 0–1 (rendered as numeric prefix when provided). */
  score?: number;
  /** One-sentence LLM justification — shown as Tooltip title. */
  reason?: string | null;
  /** Render a small dot indicator instead of the full label text. */
  dot?: boolean;
}

function ConfidenceBadgeBase({ label, score, reason, dot = false }: ConfidenceBadgeProps) {
  const semantic = SEMANTIC_BY_LABEL[label];
  const text = LABEL_TEXT[label];
  const badge = (
    <Badge type="tertiary" semantic={semantic} dot={dot}>
      {dot ? null : score !== undefined && score !== null
        ? `${text} ${score.toFixed(2)}`
        : text}
    </Badge>
  );
  if (!reason) return badge;
  return (
    <Tooltip title={reason} triggerMode="hover" placement="top">
      {badge}
    </Tooltip>
  );
}

export const ConfidenceBadge = memo(ConfidenceBadgeBase);
