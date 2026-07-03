/**
 * SpeechLab types — Display tokens, channel colors, tree navigation.
 *
 * Source of truth: backend/app/models.py (DisplayToken, DictionaryNode)
 * and docs/specs/spec-chunk-1.md.
 *
 * CRITICAL: DisplayToken field names match the backend API contract exactly.
 * Do NOT transform data from the API — pass as-is.
 */

// ═══════════════════════════════════════════════════════════
// Channel & Token Types
// ═══════════════════════════════════════════════════════════

/** Channel type for color rendering */
export type ChannelType = 'OPERATOR' | 'CLIENT' | 'ANY';

/** Display token type for UI rendering */
export type DisplayTokenType = 'WORD' | 'PHRASE' | 'LEXEME' | 'BRACKET';

/** Token ready for frontend rendering with channel color mapping */
export interface DisplayToken {
  text: string;
  type: DisplayTokenType;
  channel: ChannelType;
  word_distance: number;
  is_error: boolean;
  is_exact: boolean;
}

// ═══════════════════════════════════════════════════════════
// Channel Colors (consistent across all chunks)
// ═══════════════════════════════════════════════════════════

/** Channel color constants — CSS custom properties + fallback values */
export const CHANNEL_COLORS: Record<ChannelType, { border: string; bg: string; text: string }> = {
  OPERATOR: { border: '#81c784', bg: '#e8f5e9', text: '#2e7d32' },
  CLIENT:   { border: '#4fc3f7', bg: '#e1f5fe', text: '#0277bd' },
  ANY:      { border: '#ffb74d', bg: '#fff3e0', text: '#e65100' },
};

// ═══════════════════════════════════════════════════════════
// Tree Navigation Types
// ═══════════════════════════════════════════════════════════

/** Decoded attribute for "Атрибуты записи" section */
export interface DecodedAttribute {
  key: string;
  raw_value: string;
  human_readable: string;
  operator?: string;
}

/** SavedState metadata from <SavedState> */
export interface SavedState {
  total_found: number;
  last_update_time: string;
  execution_time: string;
  is_actual: boolean;
  is_cancelled: boolean;
}

/** Attribute logic tree node (AND/OR/NOT) */
export interface LogicTreeNode {
  node_type: 'AND' | 'OR' | 'NOT' | 'ATTRIBUTE' | 'PHRASE' | 'GROUP';
  children: LogicTreeNode[];
  payload: Record<string, unknown>;
}

/** Tree node for SpeechLab hierarchy navigation */
export interface SpeechLabTreeNode {
  id: string;
  name: string;
  has_children: boolean;
  children_count: number;
  is_remainder: boolean;
  saved_state?: SavedState;
  /** Display tokens for this node (from backend or preview parser) */
  display_tokens: DisplayToken[];
  /** Children from nested <Requests> */
  children: SpeechLabTreeNode[];
  /** Decoded attributes for "Атрибуты записи" section */
  attributes?: DecodedAttribute[];
  /** Attribute logic tree (AND/OR/NOT) for QueryTab rendering */
  attribute_tree?: LogicTreeNode;
}

// ═══════════════════════════════════════════════════════════
// API Response Types (SpeechLab-specific)
// ═══════════════════════════════════════════════════════════


