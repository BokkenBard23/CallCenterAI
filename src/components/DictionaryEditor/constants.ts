/**
 * Constants for DictionaryEditor — channel mapping, logic operators, brackets.
 * Mirrors backend `_VALID_CHANNELS` and `_VALID_LOGIC_OPERATORS` (dictionary.py).
 */

import type { BadgeSemantic, BadgeType } from '@beeline/design-system-react';
import type { ChannelType } from '../../types/speechlab';

// ═══════════════════════════════════════════════════════════
// Channel mapping — Badge semantic colors (per lock-in brief)
// ═══════════════════════════════════════════════════════════

/** Channel value as stored in `channel_constraint`. */
export type EditableChannel = Extract<ChannelType, 'ANY' | 'CLIENT' | 'OPERATOR'>;

export const EDITABLE_CHANNELS: EditableChannel[] = ['ANY', 'CLIENT', 'OPERATOR'];

/** Badge semantic mapping per lock-in brief. SYSTEM hidden (BE gap). */
export const CHANNEL_BADGE: Record<
  EditableChannel,
  { semantic: BadgeSemantic; type: BadgeType; label: string }
> = {
  ANY: { semantic: 'neutral', type: 'secondary', label: 'ANY' },
  OPERATOR: { semantic: 'violet', type: 'secondary', label: 'OP' },
  CLIENT: { semantic: 'success', type: 'secondary', label: 'CL' },
};

/** Short label for Select dropdown rendering. */
export const CHANNEL_LABELS: Record<EditableChannel, string> = {
  ANY: 'Любой (ANY)',
  CLIENT: 'Клиент (CLIENT)',
  OPERATOR: 'Сотрудник (OPERATOR)',
};

// ═══════════════════════════════════════════════════════════
// Logic operators — mirrors backend _VALID_LOGIC_OPERATORS
// ═══════════════════════════════════════════════════════════

export const LOGIC_OPERATORS: readonly { value: string; label: string }[] = [
  { value: '', label: '—' },
  { value: 'И', label: 'И' },
  { value: 'ИЛИ', label: 'ИЛИ' },
  { value: 'НЕ', label: 'НЕ' },
  { value: 'И НЕ', label: 'И НЕ' },
  { value: 'ИЛИ НЕ', label: 'ИЛИ НЕ' },
] as const;

// ═══════════════════════════════════════════════════════════
// Brackets — 0..5 (FE convention)
// ═══════════════════════════════════════════════════════════

export const BRACKET_OPTIONS: readonly number[] = [0, 1, 2, 3, 4, 5] as const;

// ═══════════════════════════════════════════════════════════
// Distance slider bounds — mirrors backend Field(2, ge=0, le=10)
// ═══════════════════════════════════════════════════════════

export const DISTANCE_MIN = 0;
export const DISTANCE_MAX = 10;
export const DISTANCE_STEP = 1;
export const DISTANCE_DEFAULT = 2;

// ═══════════════════════════════════════════════════════════
// Default new condition — POST /conditions body template
// ═══════════════════════════════════════════════════════════

export const DEFAULT_NEW_CONDITION_TEXT = 'новая фраза';

// ═══════════════════════════════════════════════════════════
// Pagination defaults
// ═══════════════════════════════════════════════════════════

export const DEFAULT_PAGE_SIZE = 10;
export const PAGE_SIZE_OPTIONS = [10, 25, 50] as const;
