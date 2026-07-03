/**
 * Tests for FileTree component.
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { FileTree, type TreeNode } from './file-tree';

// Mock motion/react for animations
vi.mock('motion/react', () => ({
  motion: {
    div: ({ children, ...props }: React.PropsWithChildren<Record<string, unknown>>) => <div {...props}>{children}</div>,
  },
  AnimatePresence: ({ children }: React.PropsWithChildren) => <>{children}</>,
}));

const SAMPLE_TREE: TreeNode[] = [
  {
    id: 'folder-1',
    name: 'Словарь переговоров',
    type: 'folder',
    children: [
      { id: 'file-1', name: 'Приветствие', type: 'file' },
      { id: 'file-2', name: 'Проблема', type: 'file' },
    ],
  },
  {
    id: 'file-3',
    name: 'Отдельный запрос',
    type: 'file',
  },
];

describe('FileTree', () => {
  it('renders tree nodes', () => {
    render(<FileTree data={SAMPLE_TREE} />);

    expect(screen.getByText('Словарь переговоров')).toBeInTheDocument();
    expect(screen.getByText('Отдельный запрос')).toBeInTheDocument();
  });

  it('renders empty state when no data', () => {
    render(<FileTree data={[]} />);

    expect(screen.getByText('Нет элементов для отображения')).toBeInTheDocument();
  });

  it('calls onSelect when node is clicked', () => {
    const onSelect = vi.fn();
    render(<FileTree data={SAMPLE_TREE} onSelect={onSelect} />);

    fireEvent.click(screen.getByText('Отдельный запрос'));
    expect(onSelect).toHaveBeenCalledWith('file-3');
  });

  it('expands folder on click and shows children', () => {
    const onSelect = vi.fn();
    render(<FileTree data={SAMPLE_TREE} onSelect={onSelect} />);

    // Click folder to expand
    fireEvent.click(screen.getByText('Словарь переговоров'));

    // Children should now be visible
    expect(screen.getByText('Приветствие')).toBeInTheDocument();
    expect(screen.getByText('Проблема')).toBeInTheDocument();
  });

  it('supports defaultExpandedIds', () => {
    render(<FileTree data={SAMPLE_TREE} defaultExpandedIds={['folder-1']} />);

    // Children should be visible without clicking
    expect(screen.getByText('Приветствие')).toBeInTheDocument();
    expect(screen.getByText('Проблема')).toBeInTheDocument();
  });

  it('highlights selected node', () => {
    const { container } = render(
      <FileTree data={SAMPLE_TREE} selectedId="file-3" />,
    );

    // The selected item should have the bg class
    const selectedItems = container.querySelectorAll('[aria-selected="true"]');
    expect(selectedItems.length).toBeGreaterThan(0);
  });

  it('calls onSelect for folder node as well', () => {
    const onSelect = vi.fn();
    render(<FileTree data={SAMPLE_TREE} onSelect={onSelect} />);

    fireEvent.click(screen.getByText('Словарь переговоров'));
    expect(onSelect).toHaveBeenCalledWith('folder-1');
  });
});
