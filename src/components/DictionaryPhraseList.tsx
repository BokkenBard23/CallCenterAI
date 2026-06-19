/**
 * DictionaryPhraseList — sidebar list of all dictionary phrases
 * with match counts and cross-highlighting support.
 *
 * - Recursively traverses DictionaryNode tree to collect all conditions
 * - Groups SearchResult.matches by phrase_text for match counts
 * - Renders DictionaryPhraseItem for each unique condition
 */

import { useMemo } from 'react';
import { Box, Divider, Icon, Stack, Typography } from '@beeline/design-system-react';
import { Icons } from '@beeline/design-tokens/js/iconfont';

import type { DictionaryNode, DictionaryCondition, SearchResult } from '../types/api';
import DictionaryPhraseItem from './DictionaryPhraseItem';

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

/** Collect all conditions from all dictionaries, deduplicating by text */
function getAllConditions(dictionaries: DictionaryNode[]): DictionaryCondition[] {
  const seen = new Set<string>();
  const result: DictionaryCondition[] = [];

  for (const dict of dictionaries) {
    for (const cond of flattenConditions(dict)) {
      if (!seen.has(cond.text)) {
        seen.add(cond.text);
        result.push(cond);
      }
    }
  }

  return result;
}

// ═══════════════════════════════════════════════════════════
// Props
// ═══════════════════════════════════════════════════════════

interface DictionaryPhraseListProps {
  dictionaries: DictionaryNode[];
  searchResult: SearchResult | null;
}

// ═══════════════════════════════════════════════════════════
// Component
// ═══════════════════════════════════════════════════════════

export default function DictionaryPhraseList({
  dictionaries,
  searchResult,
}: DictionaryPhraseListProps) {
  // Collect all unique conditions from all dictionaries
  const conditions = useMemo(
    () => getAllConditions(dictionaries),
    [dictionaries],
  );

  // Group matches by phrase_text for match counts (DR-4)
  const matchCounts = useMemo(() => {
    const map = new Map<string, number>();
    if (searchResult?.matches) {
      for (const match of searchResult.matches) {
        map.set(match.phrase_text, (map.get(match.phrase_text) ?? 0) + 1);
      }
    }
    return map;
  }, [searchResult]);

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

  // ─── Empty state: no phrases in dictionaries ────────
  if (conditions.length === 0) {
    return (
      <Box padding="x4">
        <Stack direction="vertical" spacing="x3" align="center">
          <Icon iconName={Icons.Search} size="large" />
          <Typography variant="body2" inactive>
            Нет фраз в словаре
          </Typography>
        </Stack>
      </Box>
    );
  }

  // Total match count
  const totalMatches = matchCounts.size > 0
    ? Array.from(matchCounts.values()).reduce((a, b) => a + b, 0)
    : 0;

  return (
    <Box
      className="dict-phrase-list"
      role="complementary"
      aria-label="Словарь фраз"
    >
      {/* ── Sidebar header ── */}
      <Box padding="x3">
        <Typography variant="h6">Словарь</Typography>
        <Typography variant="caption" inactive>
          Фраз: {conditions.length} · Совпадений: {totalMatches}
        </Typography>
      </Box>
      <Divider />

      {/* ── Scrollable phrase list ── */}
      <Box
        style={{
          overflowY: 'auto',
          flex: '1 1 0',
          minHeight: 0,
        }}
      >
        <Stack direction="vertical" spacing="none" role="list">
          {conditions.map((condition) => (
            <DictionaryPhraseItem
              key={condition.text}
              condition={condition}
              matchCount={matchCounts.get(condition.text) ?? 0}
            />
          ))}
        </Stack>
      </Box>
    </Box>
  );
}
