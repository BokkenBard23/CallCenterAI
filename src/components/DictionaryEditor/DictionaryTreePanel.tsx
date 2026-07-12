/**
 * DictionaryTreePanel — left sidebar with DS Tree navigation.
 *
 * Renders the dictionary hierarchy (root dictionaries + children).
 * Supports: select node, add child (Dialog), rename (InlineEdit/Dialog),
 * delete (confirm Dialog), is_remainder Badge marker, saving spinner.
 *
 * Mobile: rendered inside a Drawer (controlled by parent).
 */

import { memo, useMemo, useRef, useState } from 'react';
import {
  Badge,
  Box,
  Button,
  Dialog,
  Icon,
  IconButton,
  InlineAlert,
  Menu,
  MenuItem,
  Progress,
  Skeleton,
  Stack,
  TextField,
  Tree,
  TreeNode,
  Typography,
} from '@beeline/design-system-react';
import { Icons } from '@beeline/design-tokens/js/iconfont';
import type { DictionaryNode } from '../../types/api';

export interface DictionaryTreePanelProps {
  tree: DictionaryNode[];
  /** Currently selected node id (for external highlighting/scroll). */
  selectedNodeId: string | null;
  treeNodeStates: Record<string, { status: 'idle' | 'saving' | 'error'; error?: string }>;
  status: 'loading' | 'ready' | 'error' | 'empty';
  error?: string | null;
  onSelect: (nodeId: string) => void;
  onAddNode: (name: string, parentName: string | null) => void;
  onRenameNode: (nodeId: string, newName: string) => void;
  onRemoveNode: (nodeId: string) => void;
}

interface NodeRuntime {
  id: string;
  name: string;
  isRemainder: boolean;
  children: NodeRuntime[];
}

function toRuntime(nodes: DictionaryNode[]): NodeRuntime[] {
  return nodes.map((n) => ({
    id: n.id || n.name,
    name: n.name,
    isRemainder: Boolean(n.is_remainder),
    children: toRuntime(n.children ?? []),
  }));
}

function TreeNodeWithMenu({
  node,
  treeNodeStates,
  onAddChild,
  onRename,
  onDelete,
  children,
}: {
  node: NodeRuntime;
  treeNodeStates: Record<string, { status: 'idle' | 'saving' | 'error'; error?: string }>;
  onAddChild: (parentId: string) => void;
  onRename: (nodeId: string, currentName: string) => void;
  onDelete: (nodeId: string, name: string) => void;
  children: React.ReactNode;
}) {
  const triggerRef = useRef<HTMLButtonElement>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const rs = treeNodeStates[node.id];
  return (
    <TreeNode
      id={node.id}
      title={node.name}
      expanded={node.children.length > 0}
      custom={
        <Stack direction="horizontal" gap="x1" align="center">
          {node.isRemainder && (
            <Badge type="tertiary" semantic="warning" dot>
              Остаток
            </Badge>
          )}
          {rs?.status === 'saving' && <Progress shape="circle" size="mini" cycled />}
          <IconButton
            ref={triggerRef as never}
            iconName={Icons.MoreVert}
            variant="plain"
            aria-label={`Действия с узлом ${node.name}`}
            onClick={(e: React.MouseEvent) => {
              e.stopPropagation();
              setMenuOpen((v) => !v);
            }}
          />
          <Menu
            parent={triggerRef as never}
            isOpen={menuOpen}
            onOutsideClick={() => setMenuOpen(false)}
            onEscape={() => setMenuOpen(false)}
          >
            <MenuItem
              title="Добавить дочерний"
              iconName={Icons.FolderAdd}
              onClick={() => {
                setMenuOpen(false);
                onAddChild(node.id);
              }}
            />
            <MenuItem
              title="Переименовать"
              iconName={Icons.Edit}
              onClick={() => {
                setMenuOpen(false);
                onRename(node.id, node.name);
              }}
            />
            <MenuItem
              title="Удалить"
              iconName={Icons.Delete}
              onClick={() => {
                setMenuOpen(false);
                onDelete(node.id, node.name);
              }}
            />
          </Menu>
        </Stack>
      }
    >
      {children}
    </TreeNode>
  );
}

function DictionaryTreePanelBase({
  tree,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  selectedNodeId: _selectedNodeId,
  treeNodeStates,
  status,
  error,
  onSelect,
  onAddNode,
  onRenameNode,
  onRemoveNode,
}: DictionaryTreePanelProps) {
  const runtime = useMemo(() => toRuntime(tree), [tree]);
  const [addDialog, setAddDialog] = useState<{ open: boolean; parent: string | null }>({
    open: false,
    parent: null,
  });
  const [newName, setNewName] = useState('');
  const [renameDialog, setRenameDialog] = useState<{ open: boolean; nodeId: string; current: string } | null>(null);
  const [renameValue, setRenameValue] = useState('');
  const [deleteDialog, setDeleteDialog] = useState<{ open: boolean; nodeId: string; name: string } | null>(null);

  const renderNodes = (nodes: NodeRuntime[]): React.ReactNode =>
    nodes.map((n) => (
      <TreeNodeWithMenu
        key={n.id}
        node={n}
        treeNodeStates={treeNodeStates}
        onAddChild={(parentId) => {
          setAddDialog({ open: true, parent: parentId });
          setNewName('');
        }}
        onRename={(nodeId, current) => {
          setRenameDialog({ open: true, nodeId, current });
          setRenameValue(current);
        }}
        onDelete={(nodeId, name) => {
          setDeleteDialog({ open: true, nodeId, name });
        }}
      >
        {n.children.length > 0 ? renderNodes(n.children) : null}
      </TreeNodeWithMenu>
    ));

  if (status === 'loading') {
    return (
      <Box padding="x3">
        <Stack direction="vertical" gap="x2">
          {[1, 2, 3, 4, 5].map((i) => (
            <Skeleton key={i} variant="text" width="100%" height={28} />
          ))}
        </Stack>
      </Box>
    );
  }

  if (status === 'error') {
    return (
      <Box padding="x3">
        <Stack direction="vertical" gap="x2">
          <InlineAlert type="error">{error ?? 'Не удалось загрузить дерево словарей'}</InlineAlert>
          {/* Retry is handled by parent via key remount or reload button. */}
        </Stack>
      </Box>
    );
  }

  if (status === 'empty' || runtime.length === 0) {
    return (
      <Box padding="x3">
        <Stack direction="vertical" gap="x3" align="center">
          <Typography variant="body1" color="colorTextInactive">
            Нет словарей. Создайте корневой словарь.
          </Typography>
          <Button
            variant="contained"
            startIcon={<Icon iconName={Icons.FolderAdd} />}
            onClick={() => {
              setAddDialog({ open: true, parent: null });
              setNewName('');
            }}
          >
            Создать словарь
          </Button>
        </Stack>
      </Box>
    );
  }

  return (
    <Box padding="x3">
      <Stack direction="vertical" gap="x2">
        <Stack direction="horizontal" gap="x2" align="center" justify="space-between">
          <Typography variant="body2" color="colorTextInactive">
            Дерево словарей
          </Typography>
          <IconButton
            iconName={Icons.FolderAdd}
            variant="plain"
            aria-label="Добавить корневой словарь"
            onClick={() => {
              setAddDialog({ open: true, parent: null });
              setNewName('');
            }}
          />
        </Stack>
        <Tree
          data={undefined}
          onChange={(selected: string[]) => {
            if (selected.length > 0) onSelect(selected[0]);
          }}
          selectOnRowClick
        >
          {renderNodes(runtime)}
        </Tree>
      </Stack>

      {/* Add child / root dialog */}
      <Dialog open={addDialog.open} onClose={() => setAddDialog({ open: false, parent: null })}>
        <Box padding="x4">
          <Stack direction="vertical" gap="x3">
            <Typography variant="h6">
              {addDialog.parent ? 'Добавить дочерний узел' : 'Создать корневой словарь'}
            </Typography>
            <TextField
              label="Название"
              placeholder="Например: Риск расторжения"
              value={newName}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                setNewName(e.target.value)
              }
            />
            <Stack direction="horizontal" gap="x2" align="center">
              <Button
                variant="outlined"
                onClick={() => setAddDialog({ open: false, parent: null })}
              >
                Отмена
              </Button>
              <Button
                variant="contained"
                disabled={newName.trim().length === 0}
                onClick={() => {
                  onAddNode(newName.trim(), addDialog.parent);
                  setAddDialog({ open: false, parent: null });
                  setNewName('');
                }}
              >
                Создать
              </Button>
            </Stack>
          </Stack>
        </Box>
      </Dialog>

      {/* Rename dialog */}
      <Dialog
        open={renameDialog?.open ?? false}
        onClose={() => setRenameDialog(null)}
      >
        <Box padding="x4">
          <Stack direction="vertical" gap="x3">
            <Typography variant="h6">Переименовать узел</Typography>
            <TextField
              label="Новое название"
              value={renameValue}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                setRenameValue(e.target.value)
              }
            />
            <Stack direction="horizontal" gap="x2" align="center">
              <Button variant="outlined" onClick={() => setRenameDialog(null)}>
                Отмена
              </Button>
              <Button
                variant="contained"
                disabled={renameValue.trim().length === 0}
                onClick={() => {
                  if (renameDialog) {
                    onRenameNode(renameDialog.nodeId, renameValue.trim());
                  }
                  setRenameDialog(null);
                }}
              >
                Сохранить
              </Button>
            </Stack>
          </Stack>
        </Box>
      </Dialog>

      {/* Delete confirm dialog */}
      <Dialog
        open={deleteDialog?.open ?? false}
        onClose={() => setDeleteDialog(null)}
      >
        <Box padding="x4">
          <Stack direction="vertical" gap="x3">
            <Typography variant="h6">Удалить узел?</Typography>
            <Typography variant="body1">
              Узел «{deleteDialog?.name}» и все его дочерние узлы будут удалены.
            </Typography>
            <Stack direction="horizontal" gap="x2" align="center">
              <Button variant="outlined" onClick={() => setDeleteDialog(null)}>
                Отмена
              </Button>
              <Button
                variant="contained"
                onClick={() => {
                  if (deleteDialog) onRemoveNode(deleteDialog.nodeId);
                  setDeleteDialog(null);
                }}
              >
                Удалить
              </Button>
            </Stack>
          </Stack>
        </Box>
      </Dialog>
    </Box>
  );
}

export const DictionaryTreePanel = memo(DictionaryTreePanelBase);
