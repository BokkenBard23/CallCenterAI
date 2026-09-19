/**
 * StructureTab — third ResultsPage tab ("Структура").
 *
 * W2 (N.MAJ.3): renders a tree of matched sections/dictionaries from the
 * analysis response. For every dictionary node (DictionaryNode tree from the
 * upload response) it counts the matches (DictMatch) whose phrase_text
 * belongs to that node's conditions and displays the hierarchy with per-node
 * match-count Badges.
 *
 * DS-only components: Card, Box, Stack, Typography, Badge, Icon, InlineAlert.
 */

import { memo, useMemo } from 'react';
import {
  Badge,
  Box,
  Card,
  Icon,
  InlineAlert,
  Stack,
  Typography,
} from '@beeline/design-system-react';
import { Icons } from '@beeline/design-tokens/js/iconfont';

import type {
  DictMatch,
  DictionaryNode,
  SearchResult,
} from '../../types/api';

// ═══════════════════════════════════════════════════════════
// Match counting
// ═══════════════════════════════════════════════════════════

/**
 * Count matches per dictionary node id.
 * A match belongs to a node when its phrase_text equals one of the node's
 * condition texts (DictMatch.phrase_text ↔ DictionaryCondition.text).
 */
function countMatchesPerNode(
  dictionaries: DictionaryNode[],
  matches: DictMatch[],
): Map<string, number> {
  const counts = new Map<string, number>();
  if (matches.length === 0) return counts;

  // phrase_text -> number of matches (a phrase can match several times)
  const phraseCounts = new Map<string, number>();
  for (const m of matches) {
    phraseCounts.set(m.phrase_text, (phraseCounts.get(m.phrase_text) ?? 0) + 1);
  }

  const walk = (node: DictionaryNode): void => {
    let nodeCount = 0;
    for (const condition of node.conditions) {
      nodeCount += phraseCounts.get(condition.text) ?? 0;
    }
    if (nodeCount > 0) {
      counts.set(node.id, nodeCount);
    }
    node.children.forEach(walk);
  };

  dictionaries.forEach(walk);
  return counts;
}

// ═══════════════════════════════════════════════════════════
// Node row (recursive)
// ═══════════════════════════════════════════════════════════

interface NodeRowProps {
  node: DictionaryNode;
  depth: number;
  matchCounts: Map<string, number>;
}

function NodeRow({ node, depth, matchCounts }: NodeRowProps) {
  const matchCount = matchCounts.get(node.id) ?? 0;
  const hasChildren = node.children.length > 0;

  return (
    <Stack direction="vertical" spacing="x1" style={{ width: '100%' }}>
      <Stack
        direction="horizontal"
        spacing="x2"
        align="center"
        style={{ paddingLeft: `${depth * 20}px`, width: '100%' }}
      >
        <Icon
          iconName={hasChildren ? Icons.Folder : Icons.Attachment}
          size="small"
          style={{ color: 'var(--color-text-inactive)' }}
        />
        <Typography
          variant="body2"
          style={{ flex: '1 1 0', minWidth: 0, wordBreak: 'break-word' }}
        >
          {node.name}
        </Typography>
        <Typography variant="caption" inactive>
          {node.condition_count} усл.
        </Typography>
        <Badge
          type="tertiary"
          semantic={matchCount > 0 ? 'success' : 'info'}
          dot={matchCount > 0}
        >
          {matchCount > 0 ? `${matchCount} совп.` : 'нет'}
        </Badge>
      </Stack>
      {node.children.map((child) => (
        <NodeRow
          key={child.id}
          node={child}
          depth={depth + 1}
          matchCounts={matchCounts}
        />
      ))}
    </Stack>
  );
}

// ═══════════════════════════════════════════════════════════
// Props
// ═══════════════════════════════════════════════════════════

export interface StructureTabProps {
  /** Loaded dictionary trees (from AnalysisContext state.dictionaries). */
  dictionaries: DictionaryNode[];
  /** Search result from the analysis (matches + totals). */
  searchResult: SearchResult | null;
}

// ═══════════════════════════════════════════════════════════
// Component
// ═══════════════════════════════════════════════════════════

function StructureTabBase({
  dictionaries,
  searchResult,
}: StructureTabProps) {
  const matchCounts = useMemo(
    () => countMatchesPerNode(dictionaries, searchResult?.matches ?? []),
    [dictionaries, searchResult],
  );

  const totalMatchedNodes = useMemo(
    () =>
      dictionaries.reduce(
        (acc, root) => acc + (matchCounts.get(root.id) ?? 0),
        0,
      ),
    [dictionaries, matchCounts],
  );

  // ── Empty state: no dictionaries ──
  if (dictionaries.length === 0) {
    return (
      <Box padding="x4">
        <Stack direction="vertical" spacing="x3" align="center">
          <Icon iconName={Icons.Book} size="large" />
          <Typography variant="body1" inactive>
            Словари не загружены
          </Typography>
          <Typography variant="body2" inactive>
            Загрузите XML-словарь, чтобы увидеть структуру совпадений.
          </Typography>
        </Stack>
      </Box>
    );
  }

  return (
    <Stack direction="vertical" spacing="x3" role="tree" aria-label="Структура совпадений по словарям">
      {/* Summary line */}
      <Stack direction="horizontal" spacing="x3" align="center">
        <Typography variant="body2" inactive>
          Совпадений по словарям:
        </Typography>
        <Badge
          type="secondary"
          semantic={totalMatchedNodes > 0 ? 'success' : 'warning'}
        >
          {searchResult?.total_matches ?? 0}
        </Badge>
      </Stack>

      {/* No matches at all */}
      {searchResult && searchResult.matches.length === 0 && (
        <InlineAlert type="info" iconName={Icons.Search}>
          Совпадений не найдено — отображается полная структура словарей.
        </InlineAlert>
      )}

      {/* Per-root-dictionary cards */}
      {dictionaries.map((root) => (
        <Card key={root.id}>
          <Box padding="x4">
            <Stack direction="vertical" spacing="x2">
              <NodeRow node={root} depth={0} matchCounts={matchCounts} />
            </Stack>
          </Box>
        </Card>
      ))}
    </Stack>
  );
}

export const StructureTab = memo(StructureTabBase);
