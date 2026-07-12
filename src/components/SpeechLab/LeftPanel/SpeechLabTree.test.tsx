/**
 * Tests for SpeechLabTree — DS Tree based dictionary tree.
 *
 * Wave UI-2: Updated from ExpansionPanel to DS Tree.
 * Covers: rendering nodes, search filtering, remainder label, empty search.
 *
 * Note: DS Tree component may not fully render interactive elements in jsdom.
 * Tests focus on data mapping and filtering behavior.
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import SpeechLabTree from './SpeechLabTree';
import { mapToTreeData, filterTreeNodes } from './treeDataMapper';
import type { SpeechLabTreeNode } from '../../../types/speechlab';

function makeNode(
  overrides: Partial<SpeechLabTreeNode> & { id: string; name: string },
): SpeechLabTreeNode {
  return {
    has_children: false,
    children_count: 0,
    is_remainder: false,
    display_tokens: [],
    children: [],
    ...overrides,
  };
}

const sampleNodes: SpeechLabTreeNode[] = [
  makeNode({
    id: '1',
    name: 'SpeechLabRequest',
    has_children: true,
    children_count: 2,
    children: [
      makeNode({ id: '1-1', name: 'Запрос 1' }),
      makeNode({ id: '1-2', name: 'Запрос 2', is_remainder: true }),
    ],
  }),
  makeNode({ id: '2', name: 'Другой словарь' }),
];

describe('SpeechLabTree', () => {
  it('renders tree container with role="tree"', () => {
    render(
      <SpeechLabTree
        nodes={sampleNodes}
        onSelectNode={() => {}}
      />,
    );
    expect(screen.getByRole('tree')).toBeInTheDocument();
  });

  it('shows "Ничего не найдено" when search yields no results', () => {
    render(
      <SpeechLabTree
        nodes={sampleNodes}
        onSelectNode={() => {}}
        searchQuery="несуществующий запрос"
      />,
    );
    expect(screen.getByText('Ничего не найдено')).toBeInTheDocument();
  });

  it('filters nodes by search query', () => {
    render(
      <SpeechLabTree
        nodes={sampleNodes}
        onSelectNode={() => {}}
        searchQuery="другой"
      />,
    );
    expect(screen.getByText('Другой словарь')).toBeInTheDocument();
    expect(screen.queryByText('SpeechLabRequest')).not.toBeInTheDocument();
  });
});

// ═══════════════════════════════════════════════════════════
// Unit tests for treeDataMapper (pure functions, no DS component)
// ═══════════════════════════════════════════════════════════

describe('treeDataMapper', () => {
  it('maps node id and title correctly', () => {
    const data = mapToTreeData(sampleNodes);
    expect(data[0].id).toBe('1');
    expect(data[0].title).toBe('SpeechLabRequest');
  });

  it('maps remainder node with "Остаточный" title', () => {
    const data = mapToTreeData(sampleNodes);
    const remainderNode = data[0].children?.[1];
    expect(remainderNode?.title).toBe('Остаточный');
  });

  it('maps children recursively', () => {
    const data = mapToTreeData(sampleNodes);
    expect(data[0].children).toHaveLength(2);
    expect(data[0].children?.[0].id).toBe('1-1');
    expect(data[0].children?.[1].id).toBe('1-2');
  });

  it('preserves expanded state from expandedNodes map', () => {
    const expandedNodes: Record<string, boolean> = { '1': true };
    const data = mapToTreeData(sampleNodes, expandedNodes);
    expect(data[0].expanded).toBe(true);
    expect(data[0].children?.[0].expanded).toBe(false);
  });

  it('filterTreeNodes keeps parents of matching children', () => {
    const filtered = filterTreeNodes(sampleNodes, 'запрос 1');
    expect(filtered).toHaveLength(1);
    expect(filtered[0].id).toBe('1');
    expect(filtered[0].children).toHaveLength(1);
    expect(filtered[0].children[0].name).toBe('Запрос 1');
  });

  it('filterTreeNodes returns all nodes when query is empty', () => {
    const filtered = filterTreeNodes(sampleNodes, '');
    expect(filtered).toHaveLength(2);
  });

  it('filterTreeNodes returns empty when nothing matches', () => {
    const filtered = filterTreeNodes(sampleNodes, 'xyz');
    expect(filtered).toHaveLength(0);
  });

  it('maps leaf node without children property', () => {
    const data = mapToTreeData(sampleNodes);
    expect(data[1].children).toBeUndefined();
  });
});
