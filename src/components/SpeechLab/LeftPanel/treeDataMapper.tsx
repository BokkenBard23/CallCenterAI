/**
 * treeDataMapper — converts SpeechLabTreeNode[] to DS TreeData[] format.
 *
 * Wave UI-2: Replace ExpansionPanel tree with DS Tree component.
 *
 * Mapping:
 *   SpeechLabTreeNode.id          → TreeData.id
 *   SpeechLabTreeNode.name        → TreeData.title
 *   SpeechLabTreeNode.children    → TreeData.children (recursive)
 *   SpeechLabTreeNode.is_remainder → icon: WarningCircled
 *   SpeechLabTreeNode.has_children → icon: Folder (parent) / Book (leaf)
 *   SpeechLabTreeNode.children_count → amount prop (if > 0)
 *   SpeechLabTreeNode.saved_state.is_actual → custom Badge node
 *   SpeechLabTreeNode.saved_state.is_cancelled → custom Badge node
 *
 * Custom render: badges (Актуален/Отменён) are passed via `custom` prop
 * as React nodes, since DS Tree has no Badge slot natively.
 */

import type { TreeData } from '@beeline/design-system-react';
import { Icons } from '@beeline/design-tokens/js/iconfont';
import type { IconsType } from '@beeline/design-tokens/js/iconfont/icons';

import type { SpeechLabTreeNode } from '../../types/speechlab';

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
  return nodes.map((node) => mapNode(node, expandedNodes));
}

function mapNode(
  node: SpeechLabTreeNode,
  expandedNodes?: Record<string, boolean>,
): TreeData {
  const hasChildren = node.children.length > 0;
  const isExpanded = expandedNodes?.[node.id] ?? false;

  // Icon: WarningCircled for remainder, Folder for parent, Book for leaf
  const iconName: IconsType = node.is_remainder
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
      ? node.children.map((child) => mapNode(child, expandedNodes))
      : undefined,
  };
}

/**
 * Build custom React content for TreeData.custom slot.
 * Renders badges: "Актуален" (green) / "Отменён" (red) from saved_state.
 */
function buildCustomContent(node: SpeechLabTreeNode): React.ReactNode | undefined {
  if (!node.saved_state) return undefined;

  const badges: React.ReactNode[] = [];

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
    .filter((node) => nodeMatchesSearch(node, q))
    .map((node) => ({
      ...node,
      children: filterTreeNodes(node.children, query),
    }));
}

/** Check if a node or any descendant matches the search query */
function nodeMatchesSearch(node: SpeechLabTreeNode, lowerQuery: string): boolean {
  if (node.name.toLowerCase().includes(lowerQuery)) return true;
  if (node.display_tokens?.some((t) => t.text.toLowerCase().includes(lowerQuery))) return true;
  return node.children.some((child) => nodeMatchesSearch(child, lowerQuery));
}
