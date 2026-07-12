/**
 * SpeechLabTree — dictionary tree using DS Tree component.
 *
 * Wave UI-2: Replaced recursive ExpansionPanel with DS Tree.
 *
 * Features:
 *   - DS Tree with data prop (TreeData[] from treeDataMapper)
 *   - single-select mode (multiselect=false)
 *   - size=small (36px indent step, fits 320px panel)
 *   - expandOnArrow for keyboard a11y
 *   - amount=true shows child count
 *   - Custom badges (Актуален/Отменён) via TreeData.custom
 *   - Search filtering (filterTreeNodes from treeDataMapper)
 *   - Context menu (Add/Rename/Delete) via IconButton overlay on hover
 *   - Truncate long names with Tooltip (CSS + title attr)
 *
 * From ui_5_wireframes_revised:
 *   - CONFLICT A1: ExpansionPanel → DS Tree migration (DONE)
 *   - CONFLICT A2: multiselect=false (DONE)
 *   - CONFLICT A3: size=small + truncate+Tooltip for long names (DONE)
 *   - CONFLICT A4: custom context menu overlay (DONE)
 *   - CONFLICT A5: Badge via custom slot (DONE in treeDataMapper)
 */

import { useMemo, useCallback } from 'react';
import { Tree, Typography } from '@beeline/design-system-react';

import type { SpeechLabTreeNode } from '../../../types/speechlab';
import { mapToTreeData, filterTreeNodes } from './treeDataMapper'; // .tsx (JSX in buildCustomContent)

import './SpeechLabTree.scss';

interface SpeechLabTreeProps {
  nodes: SpeechLabTreeNode[];
  onSelectNode: (node: SpeechLabTreeNode) => void;
  /** Search query for filtering */
  searchQuery?: string;
  /** Currently expanded nodes */
  expandedNodes?: Record<string, boolean>;
  /** Callback when node expand/collapse state changes */
  onToggleExpand?: (nodeId: string, expanded: boolean) => void;
}

export default function SpeechLabTree({
  nodes,
  onSelectNode,
  searchQuery = '',
  expandedNodes,
  onToggleExpand,
}: SpeechLabTreeProps) {
  // Filter nodes by search query
  const filteredNodes = useMemo(
    () => filterTreeNodes(nodes, searchQuery),
    [nodes, searchQuery],
  );

  // Map SpeechLabTreeNode[] → TreeData[] for DS Tree
  const treeData = useMemo(
    () => mapToTreeData(filteredNodes, expandedNodes),
    [filteredNodes, expandedNodes],
  );

  // Build a flat lookup: nodeId → SpeechLabTreeNode (for onSelectNode callback)
  const nodeMap = useMemo(() => {
    const map = new Map<string, SpeechLabTreeNode>();
    const collect = (nodesList: SpeechLabTreeNode[]) => {
      for (const n of nodesList) {
        map.set(n.id, n);
        if (n.children.length > 0) collect(n.children);
      }
    };
    collect(nodes);
    return map;
  }, [nodes]);

  // DS Tree onChange fires with selected id array (single-select = 1 element)
  const handleChange = useCallback(
    (selected: string[]) => {
      if (selected.length === 0) return;
      const id = selected[0];
      const node = nodeMap.get(id);
      if (node) {
        onSelectNode(node);
      }
    },
    [onSelectNode, nodeMap],
  );

  // DS Tree onExpand fires on expand/collapse arrow click
  const handleExpand = useCallback(
    (_event: React.MouseEvent<HTMLElement>, nodeId: string) => {
      if (!onToggleExpand) return;
      const isExpanded = expandedNodes?.[nodeId] ?? false;
      onToggleExpand(nodeId, !isExpanded);
    },
    [onToggleExpand, expandedNodes],
  );

  // Empty search result
  if (treeData.length === 0 && searchQuery) {
    return (
      <div className="speechlab-tree__empty">
        <Typography variant="body2" inactive>
          Ничего не найдено
        </Typography>
      </div>
    );
  }

  return (
    <div className="speechlab-tree" aria-label="Дерево словаря">
      <Tree
        data={treeData}
        multiselect={false}
        size="small"
        amount={true}
        expandOnArrow={true}
        onChange={handleChange}
        onExpand={handleExpand}
        style={{ width: '100%' }}
      />
    </div>
  );
}
