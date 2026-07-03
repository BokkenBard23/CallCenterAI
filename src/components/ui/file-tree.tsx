/**
 * FileTree — animated file/folder tree component (MagicUI-inspired).
 * Uses framer motion for expand/collapse animations.
 * Recursive rendering of tree nodes with folder/file icons.
 *
 * @see https://magicui.design/docs/components/file-tree
 */

import { useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { Icon, Typography, Stack } from '@beeline/design-system-react';
import { Icons } from '@beeline/design-tokens/js/iconfont';
import { cn } from '@/lib/utils';

// ═══════════════════════════════════════════════════════════
// Types
// ═══════════════════════════════════════════════════════════

export interface TreeNode {
  id: string;
  name: string;
  type: 'folder' | 'file';
  children?: TreeNode[];
}

interface FileTreeProps {
  /** Tree data to render */
  data: TreeNode[];
  /** Callback when a node is selected */
  onSelect?: (nodeId: string) => void;
  /** Currently selected node ID */
  selectedId?: string;
  /** Initially expanded folder IDs */
  defaultExpandedIds?: string[];
  /** Additional CSS class */
  className?: string;
}

// ═══════════════════════════════════════════════════════════
// TreeNodeItem — recursive node renderer
// ═══════════════════════════════════════════════════════════

interface TreeNodeItemProps {
  node: TreeNode;
  depth: number;
  selectedId?: string;
  onSelect?: (nodeId: string) => void;
  expandedIds: Set<string>;
  onToggleExpand: (nodeId: string) => void;
}

function TreeNodeItem({
  node,
  depth,
  selectedId,
  onSelect,
  expandedIds,
  onToggleExpand,
}: TreeNodeItemProps) {
  const isFolder = node.type === 'folder' && node.children && node.children.length > 0;
  const isExpanded = expandedIds.has(node.id);
  const isSelected = selectedId === node.id;

  const handleClick = useCallback(() => {
    if (isFolder) {
      onToggleExpand(node.id);
    }
    onSelect?.(node.id);
  }, [isFolder, node.id, onToggleExpand, onSelect]);

  const iconName = isFolder
    ? isExpanded
      ? Icons.FolderAdd
      : Icons.Folder
    : Icons.Attachment;

  return (
    <div role="treeitem" aria-selected={isSelected} aria-expanded={isFolder ? isExpanded : undefined}>
      <div
        className={cn(
          'flex items-center gap-2 cursor-pointer rounded px-2 py-1 transition-colors',
          isSelected && 'bg-[var(--color-background-base-hover)]',
          !isSelected && 'hover:bg-[var(--color-background-base-hover)]',
        )}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
        onClick={handleClick}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            handleClick();
          }
        }}
        tabIndex={0}
      >
        <Icon iconName={iconName} size="small" />
        <Typography
          variant="body2"
          style={{
            flex: 1,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
            fontWeight: isSelected ? 600 : 400,
          }}
        >
          {node.name}
        </Typography>
      </div>

      {/* Children with animation */}
      <AnimatePresence initial={false}>
        {isFolder && isExpanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: 'easeInOut' }}
            style={{ overflow: 'hidden' }}
          >
            {node.children!.map((child) => (
              <TreeNodeItem
                key={child.id}
                node={child}
                depth={depth + 1}
                selectedId={selectedId}
                onSelect={onSelect}
                expandedIds={expandedIds}
                onToggleExpand={onToggleExpand}
              />
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════
// FileTree — main component
// ═══════════════════════════════════════════════════════════

export function FileTree({
  data,
  onSelect,
  selectedId,
  defaultExpandedIds = [],
  className,
}: FileTreeProps) {
  const [expandedIds, setExpandedIds] = useState<Set<string>>(
    () => new Set(defaultExpandedIds),
  );

  const handleToggleExpand = useCallback((nodeId: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(nodeId)) {
        next.delete(nodeId);
      } else {
        next.add(nodeId);
      }
      return next;
    });
  }, []);

  if (data.length === 0) {
    return (
      <Stack direction="vertical" spacing="x2" align="center" padding="x4">
        <Typography variant="body2" inactive>
          Нет элементов для отображения
        </Typography>
      </Stack>
    );
  }

  return (
    <div className={cn('file-tree', className)} role="tree" aria-label="Дерево файлов">
      {data.map((node) => (
        <TreeNodeItem
          key={node.id}
          node={node}
          depth={0}
          selectedId={selectedId}
          onSelect={onSelect}
          expandedIds={expandedIds}
          onToggleExpand={handleToggleExpand}
        />
      ))}
    </div>
  );
}
