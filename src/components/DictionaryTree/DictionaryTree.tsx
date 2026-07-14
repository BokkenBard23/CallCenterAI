/**
 * DictionaryTree — hierarchical sidebar with dictionary tree navigation,
 * match counts, search filtering, and cross-highlighting.
 *
 * P0-1 Rework: Replaces Q1/Q2/Q3 ButtonSet with hierarchical tree
 * using DS Tree + TreeNode components.
 *
 * Features:
 * - Hierarchical tree rendering (recursive DictionaryNode children)
 * - Node selection → selectedTreeNodeId + activePhrases in HoverContext
 * - Search filtering with debounce
 * - Hide unmatched toggle (default: ON)
 * - Cross-highlighting: hover on node → highlight phrases in text
 * - Match counts per node (Counter badge)
 * - Icons: Folder for parent, Book for leaf, WarningCircled for remainder
 */

import React, { useMemo, useCallback, useState, useRef, useEffect, memo } from 'react';
import {
  Box,
  Counter,
  Divider,
  Icon,
  Stack,
  Switch,
  TextField,
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

/** Recursively collect all phrase texts from a DictionaryNode and its descendants */
function collectPhrases(node: DictionaryNode): string[] {
  const phrases: string[] = [];
  for (const cond of node.conditions) {
    phrases.push(cond.text);
  }
  for (const child of node.children) {
    phrases.push(...collectPhrases(child));
  }
  return phrases;
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

/** Get match counts per dictionary node ID (sum of all descendant matches) */
function getNodeMatchCounts(
  dictionaries: DictionaryNode[],
  searchResult: SearchResult | null,
): Map<string, number> {
  const phraseMatches = getMatchCounts(searchResult);
  const nodeCounts = new Map<string, number>();

  function countForNode(node: DictionaryNode): number {
    let count = 0;
    for (const cond of node.conditions) {
      count += phraseMatches.get(cond.text) ?? 0;
    }
    for (const child of node.children) {
      count += countForNode(child);
    }
    nodeCounts.set(node.id, count);
    return count;
  }

  for (const dict of dictionaries) {
    countForNode(dict);
  }
  return nodeCounts;
}

/** Format OR group phrase */
function formatOrGroup(group: PhraseGroupVisual): string {
  return `[${group.words.join(', ')}]`;
}

/** Get channel CSS variable for a condition */
function getChannelCssVar(channel: string): string {
  switch (channel.toUpperCase()) {
    case 'OPERATOR': return 'var(--dict-channel-operator)';
    case 'CLIENT': return 'var(--dict-channel-client)';
    case 'ANY': return 'var(--dict-channel-any)';
    default: return 'var(--color-status-neutral, #9e9e9e)';
  }
}

/** Filter tree nodes by search query, keeping parents of matching children */
function filterTreeNodes(nodes: DictionaryNode[], query: string): DictionaryNode[] {
  if (!query) return nodes;
  const q = query.toLowerCase();

  function nodeMatches(node: DictionaryNode): boolean {
    // Check node name
    if (node.name.toLowerCase().includes(q)) return true;
    // Check conditions text
    if (node.conditions.some((c) => c.text.toLowerCase().includes(q))) return true;
    // Check children recursively
    return node.children.some((child) => nodeMatches(child));
  }

  return nodes
    .filter((node) => nodeMatches(node))
    .map((node) => ({
      ...node,
      children: filterTreeNodes(node.children, query),
    }));
}

// ═══════════════════════════════════════════════════════════
// DictionaryConditionItem (same as before — phrase row)
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

  const displayText = condition.is_exact
    ? `"${condition.text}"`
    : condition.text;

  const fontWeight = condition.word_distance === 0 ? 600 : 400;
  const channelColor = getChannelCssVar(condition.channel_constraint);

  const orGroups = condition.phrase_groups?.filter((g) => g.is_or_group) ?? [];
  const isException = condition.is_exception === true;

  const isStandaloneNot = (phrase: string): boolean => {
    return phrase.toUpperCase().startsWith('НЕ ');
  };

  const relevantExceptions = condition.exception_phrases?.filter((phrase) =>
    isStandaloneNot(phrase)
  ) ?? [];

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
            {isException && (
              <Icon
                iconName={Icons.WarningCircled}
                size="small"
                style={{ color: 'var(--color-status-warning, #e08600)' }}
              />
            )}
            <Typography
              variant="body2"
              style={{ fontWeight }}
              inactive={matchCount === 0}
            >
              {displayText}
            </Typography>
          </Stack>
          {matchCount > 0 ? (
            <Counter count={matchCount} size="small" />
          ) : (
            <Typography variant="caption" inactive>
              0 совп.
            </Typography>
          )}
        </Stack>

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

        {(isException || relevantExceptions.length > 0) && (
          <Box className="dict-tree-nested">
            <Typography variant="caption" inactive style={{ fontSize: '0.65em', fontStyle: 'italic' }}>
              Исключения (не искать):
            </Typography>
            <Stack direction="vertical" spacing="none">
              {relevantExceptions.map((phrase, idx) => (
                <Typography
                  key={`exc-${idx}`}
                  variant="caption"
                  className="dict-tree-exception"
                >
                  {phrase}
                </Typography>
              ))}
            </Stack>
          </Box>
        )}
      </Stack>
    </Box>
  );
});

// ═══════════════════════════════════════════════════════════
// DictionaryNodeItem — recursive tree node (P0-1 rework)
// ═══════════════════════════════════════════════════════════

interface DictionaryNodeItemProps {
  node: DictionaryNode;
  depth: number;
  selectedTreeNodeId: string | null;
  onSelectNode: (node: DictionaryNode) => void;
  matchCounts: Map<string, number>;
  nodeMatchCounts: Map<string, number>;
  hideUnmatched: boolean;
}

const DictionaryNodeItem = React.memo(function DictionaryNodeItem({
  node,
  depth,
  selectedTreeNodeId,
  onSelectNode,
  matchCounts,
  nodeMatchCounts,
  hideUnmatched,
}: DictionaryNodeItemProps) {
  const { setHoveredTreeNodeId } = useHoverContext();

  const isSelected = selectedTreeNodeId === node.id;
  const hasChildren = node.children.length > 0 || node.conditions.length > 0;
  const totalMatches = nodeMatchCounts.get(node.id) ?? 0;

  // H2 FIX (vision-audit): the previous implementation bound DS
  // ExpansionPanel's `open` prop to `isSelected` and relied on the
  // panel's internal CSS to reveal children. The vision audit showed
  // that even when the chevron indicated "expanded" state, child phrases
  // were present in the a11y tree but not visually rendered (likely due
  // to ExpansionPanel body overflow/transition behavior). We now use an
  // explicit local `expanded` state and render the content in a plain
  // Box that is always visible when expanded — bypassing any DS
  // ExpansionPanel rendering quirks.
  const [expanded, setExpanded] = useState<boolean>(false);

  // Icon: Folder for parent, Book for leaf
  const iconName = hasChildren ? Icons.Folder : Icons.Book;

  // Filter conditions based on hideUnmatched
  const visibleConditions = hideUnmatched
    ? node.conditions.filter((c) => (matchCounts.get(c.text) ?? 0) > 0)
    : node.conditions;

  const handleClick = useCallback(() => {
    onSelectNode(node);
  }, [onSelectNode, node]);

  const handleToggleExpand = useCallback(() => {
    setExpanded((prev) => !prev);
  }, []);

  const handleMouseEnter = useCallback(() => {
    setHoveredTreeNodeId(node.id);
  }, [setHoveredTreeNodeId, node.id]);

  const handleMouseLeave = useCallback(() => {
    setHoveredTreeNodeId(null);
  }, [setHoveredTreeNodeId]);

  // Leaf node (no children or conditions to show): clickable row
  if (!hasChildren) {
    return (
      <Box
        className={`dict-tree-node ${isSelected ? 'dict-tree-node--selected' : ''}`}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
        onClick={handleClick}
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
        role="treeitem"
        aria-selected={isSelected}
        aria-label={node.name}
      >
        <Stack direction="horizontal" spacing="x2" align="center" style={{ width: '100%' }}>
          <Icon iconName={iconName} size="small" />
          <Typography
            variant="body2"
            style={{
              fontWeight: isSelected ? 600 : 400,
              flex: 1,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {node.name}
          </Typography>
          {totalMatches > 0 && <Counter count={totalMatches} size="small" />}
        </Stack>
      </Box>
    );
  }

  // Parent node: custom collapsible (H2 FIX — replaces DS ExpansionPanel)
  return (
    <Box
      style={{ paddingLeft: `${depth * 16}px` }}
      role="treeitem"
      aria-expanded={expanded}
      aria-selected={isSelected}
    >
      {/* Header row — clickable to toggle expand AND select node */}
      <Box
        className={`dict-tree-node dict-tree-node--parent ${isSelected ? 'dict-tree-node--selected' : ''}`}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          padding: '8px 12px',
          cursor: 'pointer',
          minHeight: '44px',
          borderRadius: '4px',
        }}
        onClick={() => {
          // Click on the header toggles expand + selects the node.
          handleToggleExpand();
          handleClick();
        }}
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
        aria-label={node.name}
      >
        <Icon
          iconName={expanded ? Icons.NavArrowDown : Icons.NavArrowRight}
          size="small"
          aria-hidden="true"
        />
        <Icon iconName={iconName} size="small" />
        <Typography
          variant="body2"
          style={{
            fontWeight: isSelected ? 600 : 400,
            flex: 1,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {node.name}
        </Typography>
        {/* H3 FIX: subtitle now explicit about scope — "in subtree" — so the
            number no longer looks like a data/aggregation bug when compared
            with the header's overall total. */}
        {totalMatches > 0 && (
          <Counter
            count={totalMatches}
            size="small"
            title={`${totalMatches} совпадений в поддереве (включая дочерние узлы)`}
          />
        )}
      </Box>

      {/* Content — always rendered visibly when expanded (H2 FIX). */}
      {expanded && (
        <Box className="dict-tree-node__body">
          {/* Show conditions under this node */}
          {visibleConditions.length > 0 && (
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

          {/* Show child nodes */}
          {node.children.map((child) => (
            <DictionaryNodeItem
              key={child.id}
              node={child}
              depth={depth + 1}
              selectedTreeNodeId={selectedTreeNodeId}
              onSelectNode={onSelectNode}
              matchCounts={matchCounts}
              nodeMatchCounts={nodeMatchCounts}
              hideUnmatched={hideUnmatched}
            />
          ))}

          {visibleConditions.length === 0 && node.children.length === 0 && (
            <Box padding="x3">
              <Typography variant="caption" inactive>
                Нет фраз{hideUnmatched ? ' с совпадениями' : ''}
              </Typography>
            </Box>
          )}
        </Box>
      )}
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

export default memo(function DictionaryTree({
  dictionaries,
  searchResult,
}: DictionaryTreeProps) {
  const {
    selectedTreeNodeId,
    setSelectedTreeNodeId,
    // activePhrases is read by HighlightRenderer — not consumed here
    setActivePhrases,
    hideUnmatched,
    setHideUnmatched,
    setLevelNames,
    setSelectedDictLevel, // DEPRECATED: keep for backward compat
  } = useHoverContext();

  // P1-3: Search with debounce
  const [searchQuery, setSearchQuery] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (debounceRef.current !== null) {
      clearTimeout(debounceRef.current);
    }
    debounceRef.current = setTimeout(() => {
      setDebouncedQuery(searchQuery);
    }, 300);
    return () => {
      if (debounceRef.current !== null) {
        clearTimeout(debounceRef.current);
      }
    };
  }, [searchQuery]);

  const matchCounts = useMemo(() => getMatchCounts(searchResult), [searchResult]);
  const nodeMatchCounts = useMemo(
    () => getNodeMatchCounts(dictionaries, searchResult),
    [dictionaries, searchResult],
  );

  // Build level name map from actual dictionary data
  const computedLevelNames = useMemo(() => {
    const nameMap = new Map<number, string>();
    if (searchResult?.matches) {
      for (const match of searchResult.matches) {
        if (!nameMap.has(match.cascade_order) && match.quarter) {
          nameMap.set(match.cascade_order, match.quarter);
        }
      }
    }
    dictionaries.forEach((dict, idx) => {
      const level = idx + 1;
      if (!nameMap.has(level) && dict.name) {
        nameMap.set(level, dict.name);
      }
    });
    return nameMap;
  }, [dictionaries, searchResult]);

  // Sync level names to HoverContext for shared access
  React.useEffect(() => {
    setLevelNames(computedLevelNames);
  }, [computedLevelNames, setLevelNames]);

  // Filtered tree nodes by search query
  const filteredDictionaries = useMemo(
    () => filterTreeNodes(dictionaries, debouncedQuery),
    [dictionaries, debouncedQuery],
  );

  const totalMatches = searchResult?.total_matches ?? 0;
  const totalPhrases = useMemo(() => {
    let count = 0;
    for (const dict of dictionaries) {
      count += flattenConditions(dict).length;
    }
    return count;
  }, [dictionaries]);

  // P0-1: Handle tree node selection → update selectedTreeNodeId + activePhrases
  const handleSelectNode = useCallback(
    (node: DictionaryNode) => {
      if (selectedTreeNodeId === node.id) {
        // Deselect: clear selection and show all phrases
        setSelectedTreeNodeId(null);
        setActivePhrases(new Set());
        setSelectedDictLevel(null); // DEPRECATED
      } else {
        // Select: compute activePhrases from selected node + descendants
        setSelectedTreeNodeId(node.id);
        const phrases = collectPhrases(node);
        setActivePhrases(new Set(phrases));
        setSelectedDictLevel(null); // DEPRECATED: no longer using Q-level
      }
    },
    [selectedTreeNodeId, setSelectedTreeNodeId, setActivePhrases, setSelectedDictLevel],
  );

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

  return (
    <Box className="dict-tree" role="complementary" aria-label="Словарь фраз">
      {/* ── Sidebar header ── */}
      <Box className="dict-tree-header">
        <Typography variant="h6">Словарь</Typography>
        <Typography variant="caption" inactive>
          Фраз: {totalPhrases} · Совпадений: {totalMatches}
        </Typography>

        {/* Hide unmatched toggle */}
        <Box style={{ marginTop: '8px' }}>
          <Switch
            label="Показать все фразы"
            checked={!hideUnmatched}
            onChange={() => setHideUnmatched(!hideUnmatched)}
          />
        </Box>
      </Box>

      <Divider />

      {/* P1-3: Search field for filtering tree nodes */}
      <Box padding="x2">
        <TextField
          placeholder="Поиск по словарю"
          value={searchQuery}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
            setSearchQuery(e.target.value)
          }
          style={{ width: '100%' }}
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
        {filteredDictionaries.length === 0 && debouncedQuery ? (
          <Box padding="x3">
            <Typography variant="body2" inactive>
              Ничего не найдено
            </Typography>
          </Box>
        ) : (
          <Stack direction="vertical" spacing="none" role="tree">
            {filteredDictionaries.map((dict) => (
              <DictionaryNodeItem
                key={dict.id}
                node={dict}
                depth={0}
                selectedTreeNodeId={selectedTreeNodeId}
                onSelectNode={handleSelectNode}
                matchCounts={matchCounts}
                nodeMatchCounts={nodeMatchCounts}
                hideUnmatched={hideUnmatched}
              />
            ))}
          </Stack>
        )}
      </Box>
    </Box>
  );
});
