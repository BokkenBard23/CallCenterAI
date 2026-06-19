/**
 * DictionaryTree — hierarchical sidebar with Q1/Q2/Q3 levels,
 * match counts, expand/collapse, and multi-dict filtering.
 *
 * Replaces the flat DictionaryPhraseList with a Tree-based view.
 *
 * Features:
 * - 3 levels: Q1 (cascade_order=1), Q2 (2), Q3 (3) + Remainder
 * - ButtonSet for level selection (selectedDictLevel)
 * - Each level expandable → list of phrases with match counts
 * - Dim/bright: selectedDictLevel → bright highlights, others dim
 * - Hide unmatched toggle (default: ON)
 */

import React, { useMemo, useCallback, useState } from 'react';
import {
  Box,
  ButtonSet,
  Counter,
  Divider,
  ExpansionPanel,
  Icon,
  Stack,
  Switch,
  Typography,
} from '@beeline/design-system-react';
import { Icons } from '@beeline/design-tokens/js/iconfont';

import type {
  DictionaryNode,
  DictionaryCondition,
  SearchResult,
  PhraseGroupVisual,
} from '../../types/api';
import { useHoverContext } from '../../context/HoverContext';

// ═══════════════════════════════════════════════════════════
// Dictionary tree traversal
// ═══════════════════════════════════════════════════════════

/** Recursively collect all conditions from a DictionaryNode tree */
function flattenConditions(node: DictionaryNode): DictionaryCondition[] {
  return [
    ...node.conditions,
    ...node.children.flatMap(flattenConditions),
  ];
}

/** Get conditions grouped by cascade_order */
function groupConditionsByLevel(
  dictionaries: DictionaryNode[],
  searchResult: SearchResult | null,
): Map<number, DictionaryCondition[]> {
  const allConditions: DictionaryCondition[] = [];
  const seen = new Set<string>();

  for (const dict of dictionaries) {
    for (const cond of flattenConditions(dict)) {
      if (!seen.has(cond.text)) {
        seen.add(cond.text);
        allConditions.push(cond);
      }
    }
  }

  const levelMap = new Map<number, DictionaryCondition[]>();

  if (searchResult?.matches) {
    const phraseToLevel = new Map<string, number>();
    for (const match of searchResult.matches) {
      if (!phraseToLevel.has(match.phrase_text)) {
        phraseToLevel.set(match.phrase_text, match.cascade_order);
      }
    }

    for (const cond of allConditions) {
      const level = phraseToLevel.get(cond.text) ?? 1;
      const existing = levelMap.get(level) ?? [];
      if (!existing.some((c) => c.text === cond.text)) {
        existing.push(cond);
      }
      levelMap.set(level, existing);
    }
  }

  if (levelMap.size === 0) {
    levelMap.set(1, allConditions);
  }

  return levelMap;
}

/** Get match counts per phrase */
function getMatchCounts(searchResult: SearchResult | null): Map<string, number> {
  const map = new Map<string, number>();
  if (searchResult?.matches) {
    for (const match of searchResult.matches) {
      map.set(match.phrase_text, (map.get(match.phrase_text) ?? 0) + 1);
    }
  }
  return map;
}

/** Get total match count per level */
function getLevelMatchCounts(searchResult: SearchResult | null): Map<number, number> {
  const map = new Map<number, number>();
  if (searchResult?.matches) {
    for (const match of searchResult.matches) {
      map.set(match.cascade_order, (map.get(match.cascade_order) ?? 0) + 1);
    }
  }
  return map;
}

/** Get unique dialogues without Q3 matches (remainder count) */
function getRemainderCount(searchResult: SearchResult | null): number {
  if (!searchResult?.matches) return 0;
  const q3Dialogues = new Set<number>();
  const allDialogues = new Set<number>();
  for (const match of searchResult.matches) {
    allDialogues.add(match.turn_index);
    if (match.cascade_order === 3) {
      q3Dialogues.add(match.turn_index);
    }
  }
  return allDialogues.size - q3Dialogues.size;
}

/** Format OR group phrase: [word1, word2] */
function formatOrGroup(group: PhraseGroupVisual): string {
  return `[${group.words.join(', ')}]`;
}

/** Get channel CSS variable for a condition */
function getChannelCssVar(channel: string): string {
  switch (channel.toUpperCase()) {
    case 'OPERATOR':
      return 'var(--dict-channel-operator)';
    case 'CLIENT':
      return 'var(--dict-channel-client)';
    case 'ANY':
      return 'var(--dict-channel-any)';
    default:
      return 'var(--color-status-neutral, #9e9e9e)';
  }
}

/** Level display names */
const LEVEL_NAMES: Record<number, string> = {
  1: 'Q1',
  2: 'Q2',
  3: 'Q3',
};

const LEVEL_DESCRIPTIONS: Record<number, string> = {
  1: 'Риск расторжения',
  2: 'Жалоба',
  3: 'Эскалация',
};

// ═══════════════════════════════════════════════════════════
// DictionaryConditionItem (Chunk 5)
// ═══════════════════════════════════════════════════════════

interface DictionaryConditionItemProps {
  condition: DictionaryCondition;
  matchCount: number;
}

const DictionaryConditionItem = React.memo(function DictionaryConditionItem({
  condition,
  matchCount,
}: DictionaryConditionItemProps) {
  const { hoveredPhrase, setHoveredPhrase } = useHoverContext();

  const isHovered = hoveredPhrase === condition.text;

  // DR-1: Quotes for exact match
  const displayText = condition.is_exact
    ? `\u00AB${condition.text}\u00BB`
    : condition.text;

  // DR-2: Bold for word_distance === 0
  const fontWeight = condition.word_distance === 0 ? 600 : 400;

  // DR-3: Channel color
  const channelColor = getChannelCssVar(condition.channel_constraint);

  // OR-groups (Chunk 5)
  const orGroups = condition.phrase_groups?.filter((g) => g.is_or_group) ?? [];

  // Exceptions (Chunk 5)
  const isException = condition.is_exception === true;

  // Nested phrases (Chunk 5)
  const hasNestedPhrases = condition.nested_phrases && condition.nested_phrases.length > 0;

  const handleMouseEnter = useCallback(() => {
    setHoveredPhrase(condition.text);
  }, [setHoveredPhrase, condition.text]);

  const handleMouseLeave = useCallback(() => {
    setHoveredPhrase(null);
  }, [setHoveredPhrase]);

  return (
    <Box
      className="dict-tree-phrase-row"
      data-hovered={isHovered ? 'true' : undefined}
      style={{
        borderLeft: isHovered
          ? `3px solid ${channelColor}`
          : '3px solid transparent',
        backgroundColor: isHovered
          ? 'var(--color-background-base-hover, rgba(0,0,0,0.04))'
          : 'transparent',
        transition: 'background-color 150ms ease, border-left-color 150ms ease',
        cursor: 'pointer',
        minHeight: '44px',
      }}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      role="treeitem"
      aria-label={`${condition.text}, ${condition.channel_constraint}, ${matchCount} совп.`}
    >
      <Stack direction="vertical" spacing="none" style={{ width: '100%' }}>
        <Stack direction="horizontal" spacing="x2" align="center" justify="space-between">
          <Stack direction="horizontal" spacing="x2" align="center">
            {/* DR-3: Channel color dot */}
            <span
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

            {/* Exception: ⚠ НЕ prefix (Chunk 5) */}
            {isException && (
              <Icon
                iconName={Icons.WarningCircled}
                size="small"
                style={{ color: 'var(--color-status-warning, #e08600)' }}
              />
            )}

            {/* Phrase text with DR-1 (quotes) + DR-2 (bold) */}
            <Typography
              variant="body2"
              style={{ fontWeight }}
              inactive={matchCount === 0}
            >
              {displayText}
            </Typography>
          </Stack>

          {/* Match count */}
          {matchCount > 0 ? (
            <Counter count={matchCount} size="small" />
          ) : (
            <Typography variant="caption" inactive>
              0 совп.
            </Typography>
          )}
        </Stack>

        {/* OR-groups (Chunk 5) */}
        {orGroups.map((group, idx) => (
          <Box key={`or-${idx}`} className="dict-tree-nested">
            <Typography variant="caption" inactive>
              ↳ {formatOrGroup(group)}
            </Typography>
            <Typography variant="caption" inactive style={{ fontSize: '0.7em' }}>
              {' '}альтернативы
            </Typography>
          </Box>
        ))}

        {/* Exception phrases (Chunk 5) */}
        {(isException || (condition.exception_phrases && condition.exception_phrases.length > 0)) && (
          <Box className="dict-tree-nested">
            <Stack direction="vertical" spacing="none">
              {condition.exception_phrases?.map((phrase, idx) => (
                <Typography
                  key={`exc-${idx}`}
                  variant="caption"
                  className="dict-tree-exception"
                >
                  ↳ НЕ {phrase}
                </Typography>
              ))}
            </Stack>
          </Box>
        )}

        {/* Nested phrases (Chunk 5) */}
        {hasNestedPhrases && condition.nested_phrases!.map((phrase, idx) => (
          <Box key={`nested-${idx}`} className="dict-tree-nested">
            <Typography variant="caption" inactive>
              ↳ {phrase}
            </Typography>
          </Box>
        ))}
      </Stack>
    </Box>
  );
});

// ═══════════════════════════════════════════════════════════
// Props
// ═══════════════════════════════════════════════════════════

interface DictionaryTreeProps {
  dictionaries: DictionaryNode[];
  searchResult: SearchResult | null;
}

// ═══════════════════════════════════════════════════════════
// Main Component
// ═══════════════════════════════════════════════════════════

export default function DictionaryTree({
  dictionaries,
  searchResult,
}: DictionaryTreeProps) {
  const { selectedDictLevel, setSelectedDictLevel, hideUnmatched, setHideUnmatched } = useHoverContext();

  // Expanded levels
  const [expandedLevels, setExpandedLevels] = useState<Set<number>>(new Set());

  const matchCounts = useMemo(() => getMatchCounts(searchResult), [searchResult]);
  const levelMatchCounts = useMemo(() => getLevelMatchCounts(searchResult), [searchResult]);
  const conditionsByLevel = useMemo(() => groupConditionsByLevel(dictionaries, searchResult), [dictionaries, searchResult]);
  const remainderCount = useMemo(() => getRemainderCount(searchResult), [searchResult]);

  const totalMatches = searchResult?.total_matches ?? 0;
  const totalPhrases = useMemo(() => {
    let count = 0;
    for (const conditions of conditionsByLevel.values()) {
      count += conditions.length;
    }
    return count;
  }, [conditionsByLevel]);

  // Toggle level expansion
  const toggleExpand = useCallback((level: number) => {
    setExpandedLevels((prev) => {
      const next = new Set(prev);
      if (next.has(level)) {
        next.delete(level);
      } else {
        next.add(level);
      }
      return next;
    });
  }, []);

  // Level selection: click active tab → deselect (null)
  const handleLevelSelect = useCallback((level: number) => {
    setSelectedDictLevel(selectedDictLevel === level ? null : level);
  }, [selectedDictLevel, setSelectedDictLevel]);

  // ─── Empty state: no dictionaries ───────────────────
  if (dictionaries.length === 0) {
    return (
      <Box padding="x4">
        <Stack direction="vertical" spacing="x3" align="center">
          <Icon iconName={Icons.Search} size="large" />
          <Typography variant="body2" inactive>
            Словари не загружены
          </Typography>
        </Stack>
      </Box>
    );
  }

  // ButtonSet items for Q1/Q2/Q3
  const levelButtons = [1, 2, 3].map((level) => ({
    id: String(level),
    variant: selectedDictLevel === level ? 'contained' as const : 'outlined' as const,
    children: LEVEL_NAMES[level],
    onClick: () => handleLevelSelect(level),
  }));

  return (
    <Box className="dict-tree" role="complementary" aria-label="Словарь фраз">
      {/* ── Sidebar header ── */}
      <Box className="dict-tree-header">
        <Typography variant="h6">Словарь</Typography>
        <Typography variant="caption" inactive>
          Фраз: {totalPhrases} · Совпадений: {totalMatches}
        </Typography>

        {/* Hide unmatched toggle (Chunk 3) */}
        <Box style={{ marginTop: '8px' }}>
          <Switch
            label="Показать все фразы"
            checked={!hideUnmatched}
            onChange={() => setHideUnmatched(!hideUnmatched)}
          />
        </Box>
      </Box>

      <Divider />

      {/* ── Level selection tabs ── */}
      <Box padding="x2">
        <ButtonSet
          buttons={levelButtons}
          size="small"
          direction="horizontal"
        />
      </Box>

      <Divider />

      {/* ── Scrollable tree ── */}
      <Box
        style={{
          overflowY: 'auto',
          flex: '1 1 0',
          minHeight: 0,
        }}
      >
        <Stack direction="vertical" spacing="none" role="tree">
          {/* Q1, Q2, Q3 levels */}
          {[1, 2, 3].map((level) => {
            const conditions = conditionsByLevel.get(level) ?? [];
            const levelCount = levelMatchCounts.get(level) ?? 0;
            const isExpanded = expandedLevels.has(level);

            // Filter conditions based on hideUnmatched
            const visibleConditions = hideUnmatched
              ? conditions.filter((c) => (matchCounts.get(c.text) ?? 0) > 0)
              : conditions;

            return (
              <ExpansionPanel
                key={level}
                title={`${LEVEL_NAMES[level]} — ${LEVEL_DESCRIPTIONS[level]}`}
                open={isExpanded}
                onOpen={() => toggleExpand(level)}
                onClose={() => toggleExpand(level)}
                subTitle={`${levelCount} совпадений`}
              >
                {visibleConditions.length === 0 ? (
                  <Box padding="x3">
                    <Typography variant="caption" inactive>
                      Нет фраз{hideUnmatched ? ' с совпадениями' : ''}
                    </Typography>
                  </Box>
                ) : (
                  <Stack direction="vertical" spacing="none" role="group">
                    {visibleConditions.map((condition) => (
                      <DictionaryConditionItem
                        key={condition.text}
                        condition={condition}
                        matchCount={matchCounts.get(condition.text) ?? 0}
                      />
                    ))}
                  </Stack>
                )}
              </ExpansionPanel>
            );
          })}

          {/* Remainder section */}
          {remainderCount > 0 && (
            <Box padding="x3">
              <Typography variant="body2" inactive>
                Остаток: {remainderCount} диалогов без Q3 совпадений
              </Typography>
            </Box>
          )}
        </Stack>
      </Box>
    </Box>
  );
}
