/**
 * treeDataMapper — converts SpeechLabTreeNode[] to DS Tree data format.
 *
 * Wave UI-2: Replace ExpansionPanel tree with DS Tree component.
 *
 * Mapping:
 *   SpeechLabTreeNode.id          → TreeNodeData.id
 *   SpeechLabTreeNode.name        → TreeNodeData.title
 *   SpeechLabTreeNode.children    → TreeNodeData.children (recursive)
 *   SpeechLabTreeNode.is_remainder → icon: WarningCircled
 *   SpeechLabTreeNode.has_children → icon: Folder (parent) / Book (leaf)
 *   SpeechLabTreeNode.children_count → amount prop (if > 0)
 *   SpeechLabTreeNode.saved_state.is_actual → custom Badge node
 *   SpeechLabTreeNode.saved_state.is_cancelled → custom Badge node
 *
 * Custom render: badges (Актуален/Отменён) are passed via `custom` prop
 * as React nodes, since DS Tree has no Badge slot natively.
 *
 * NOTE: DS does not export a TreeData type. We define a local contract
 * matching the props consumed by the DS Tree `data` prop (id/title/icon/
 * expanded/custom/children). This shape is intentionally permissive.
 */

import type { ReactNode } from 'react';
import { Icons } from '@beeline/design-tokens/js/iconfont';

import type { SpeechLabTreeNode } from '../../../types/speechlab';

/**
 * Local TreeData contract for DS Tree `data` prop.
 * Mirrors the subset of TreeNode props that Tree renders when given `data`.
 */
export interface TreeData {
  id: string;
  title: string;
  icon?: { iconName: Icons };
  expanded?: boolean;
  custom?: ReactNode;
  children?: TreeData[];
}

/**
 * Convert SpeechLabTreeNode[] to DS TreeData[] for the Tree component.
 *
 * @param nodes SpeechLabTreeNode array from store/parser
 * @param expandedNodes Optional map of nodeId → expanded state
 * @returns TreeData[] compatible with DS Tree `data` prop
 */
export function mapToTreeData(
  nodes: SpeechLabTreeNode[],
  expandedNodes?: Record<string, boolean>,
): TreeData[] {
  return nodes.map((node: SpeechLabTreeNode) => mapNode(node, expandedNodes));
}

function mapNode(
  node: SpeechLabTreeNode,
  expandedNodes?: Record<string, boolean>,
): TreeData {
  const hasChildren = node.children.length > 0;
  const isExpanded = expandedNodes?.[node.id] ?? false;

  // Icon: WarningCircled for remainder, Folder for parent, Book for leaf
  const iconName: Icons = node.is_remainder
    ? Icons.WarningCircled
    : hasChildren
      ? Icons.Folder
      : Icons.Book;

  // Custom content: badges for saved_state
  const customContent = buildCustomContent(node);

  return {
    id: node.id,
    title: node.is_remainder ? 'Остаточный' : node.name,
    icon: { iconName },
    expanded: isExpanded,
    // DS Tree amount prop shows child count; we also pass custom badges
    custom: customContent,
    children: hasChildren
      ? node.children.map((child: SpeechLabTreeNode) => mapNode(child, expandedNodes))
      : undefined,
  };
}

/**
 * Build custom React content for TreeData.custom slot.
 * Renders badges: "Актуален" (green) / "Отменён" (red) from saved_state.
 */
function buildCustomContent(node: SpeechLabTreeNode): ReactNode | undefined {
  if (!node.saved_state) return undefined;

  const badges: ReactNode[] = [];

  if (node.saved_state.is_actual) {
    badges.push(
      <span
        key="actual"
        className="tree-node-badge tree-node-badge--actual"
        style={{
          display: 'inline-block',
          padding: '2px 8px',
          borderRadius: '4px',
          fontSize: '11px',
          fontWeight: 500,
          backgroundColor: 'var(--color-status-success-background, rgba(106, 214, 130, 0.15))',
          color: 'var(--color-status-success, #6ad682)',
          marginLeft: '4px',
        }}
      >
        Актуален
      </span>,
    );
  }

  if (node.saved_state.is_cancelled) {
    badges.push(
      <span
        key="cancelled"
        className="tree-node-badge tree-node-badge--cancelled"
        style={{
          display: 'inline-block',
          padding: '2px 8px',
          borderRadius: '4px',
          fontSize: '11px',
          fontWeight: 500,
          backgroundColor: 'var(--color-status-error-background, rgba(255, 100, 100, 0.15))',
          color: 'var(--color-status-error, #ff6464)',
          marginLeft: '4px',
        }}
      >
        Отменён
      </span>,
    );
  }

  return badges.length > 0 ? <>{badges}</> : undefined;
}

/**
 * Filter tree nodes by search query, keeping parents of matching children.
 * Reused from legacy SpeechLabTree — same logic, different output type.
 */
export function filterTreeNodes(
  nodes: SpeechLabTreeNode[],
  query: string,
): SpeechLabTreeNode[] {
  if (!query) return nodes;
  const q = query.toLowerCase();
  return nodes
    .filter((node: SpeechLabTreeNode) => nodeMatchesSearch(node, q))
    .map((node: SpeechLabTreeNode) => ({
      ...node,
      children: filterTreeNodes(node.children, query),
    }));
}

/** Check if a node or any descendant matches the search query */
function nodeMatchesSearch(node: SpeechLabTreeNode, lowerQuery: string): boolean {
  if (node.name.toLowerCase().includes(lowerQuery)) return true;
  if (node.display_tokens?.some((t: { text: string }) => t.text.toLowerCase().includes(lowerQuery))) return true;
  return node.children.some((child: SpeechLabTreeNode) => nodeMatchesSearch(child, lowerQuery));
}
