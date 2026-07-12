import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { DictionaryTreePanel } from './DictionaryTreePanel';
import type { DictionaryNode } from '../../types/api';

const tree: DictionaryNode[] = [
  {
    id: 'root1',
    name: 'Словарь 1',
    parent_name: null,
    conditions: [],
    children: [
      {
        id: 'child1',
        name: 'Дочерний',
        parent_name: 'Словарь 1',
        conditions: [],
        children: [],
        condition_count: 0,
        has_children: false,
        children_count: 0,
      },
    ],
    condition_count: 0,
    has_children: true,
    children_count: 1,
    is_remainder: false,
  },
  {
    id: 'root2',
    name: 'Остаток',
    parent_name: null,
    conditions: [],
    children: [],
    condition_count: 0,
    has_children: false,
    children_count: 0,
    is_remainder: true,
  },
];

const noop = vi.fn();

describe('DictionaryTreePanel', () => {
  it('renders loading skeleton when status is loading', () => {
    const { container } = render(
      <DictionaryTreePanel
        tree={[]}
        selectedNodeId={null}
        treeNodeStates={{}}
        status="loading"
        onSelect={noop}
        onAddNode={noop}
        onRenameNode={noop}
        onRemoveNode={noop}
      />,
    );
    // Skeleton renders placeholder text rows.
    expect(container.querySelectorAll('[class*="skeleton"], [class*="Skeleton"]').length).toBeGreaterThan(0);
  });

  it('renders error state with message', () => {
    render(
      <DictionaryTreePanel
        tree={[]}
        selectedNodeId={null}
        treeNodeStates={{}}
        status="error"
        error="Сеть недоступна"
        onSelect={noop}
        onAddNode={noop}
        onRenameNode={noop}
        onRemoveNode={noop}
      />,
    );
    expect(screen.getByText('Сеть недоступна')).toBeInTheDocument();
  });

  it('renders empty state prompt when status is empty', () => {
    render(
      <DictionaryTreePanel
        tree={[]}
        selectedNodeId={null}
        treeNodeStates={{}}
        status="empty"
        onSelect={noop}
        onAddNode={noop}
        onRenameNode={noop}
        onRemoveNode={noop}
      />,
    );
    expect(screen.getByText(/Нет словарей/i)).toBeInTheDocument();
    expect(screen.getByText('Создать словарь')).toBeInTheDocument();
  });

  it('renders tree nodes when ready', () => {
    render(
      <DictionaryTreePanel
        tree={tree}
        selectedNodeId="root1"
        treeNodeStates={{}}
        status="ready"
        onSelect={noop}
        onAddNode={noop}
        onRenameNode={noop}
        onRemoveNode={noop}
      />,
    );
    expect(screen.getByText('Словарь 1')).toBeInTheDocument();
    expect(screen.getByText('Дочерний')).toBeInTheDocument();
    // "Остаток" is both a node name and a Badge — expect multiple matches.
    expect(screen.getAllByText('Остаток').length).toBeGreaterThanOrEqual(1);
  });

  it('renders "Остаток" badge for is_remainder nodes', () => {
    render(
      <DictionaryTreePanel
        tree={tree}
        selectedNodeId="root2"
        treeNodeStates={{}}
        status="ready"
        onSelect={noop}
        onAddNode={noop}
        onRenameNode={noop}
        onRemoveNode={noop}
      />,
    );
    // "Остаток" appears both as node name and as badge text — expect ≥ 2.
    const matches = screen.getAllByText('Остаток');
    expect(matches.length).toBeGreaterThanOrEqual(2);
  });
});
