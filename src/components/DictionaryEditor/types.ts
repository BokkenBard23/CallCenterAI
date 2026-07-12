/**
 * Editor-local types for DictionaryEditor.
 *
 * Backend `DictionaryCondition` (api.ts) does NOT persist
 * `logic_operator` / `open_brackets` / `close_brackets` per-row —
 * they are validated on PATCH but encoded into the token_section
 * during XML serialization. The editor tracks them in FE state so
 * the analyst can author the visual logic tree, then exports XML.
 */

import type { DictionaryCondition, DictionaryNode } from '../../types/api';

/**
 * Per-row editor state. Extends the persisted condition with the
 * three visual-only fields that the BE accepts but does not return.
 */
export interface EditorCondition extends DictionaryCondition {
  /** Visual logic operator preceding this row. Validated by BE on PATCH. */
  logic_operator: string;
  /** Visual open brackets count (0..5). FE convention. */
  open_brackets: number;
  /** Visual close brackets count (0..5). FE convention. */
  close_brackets: number;
}

/** Convert a raw backend DictionaryCondition to editor state (defaults for visual fields). */
export function toEditorCondition(c: DictionaryCondition, defaults?: Partial<EditorCondition>): EditorCondition {
  return {
    ...c,
    logic_operator: defaults?.logic_operator ?? '',
    open_brackets: defaults?.open_brackets ?? 0,
    close_brackets: defaults?.close_brackets ?? 0,
  };
}

/** Build an EditorCondition from a create-request body response (POST /conditions). */
export function editorConditionFromCreate(
  base: DictionaryCondition,
  logic_operator = '',
  open_brackets = 0,
  close_brackets = 0,
): EditorCondition {
  return { ...base, logic_operator, open_brackets, close_brackets };
}

/** Per-row async status (saving / error / rollback). */
export type RowStatus = 'idle' | 'saving' | 'error';

export interface RowState {
  status: RowStatus;
  /** Error message shown in row-level InlineAlert. */
  error?: string;
  /** Snapshot for rollback when PATCH fails. */
  snapshot?: EditorCondition;
}

/** Tree node status (saving indicator on a tree node). */
export type TreeNodeStatus = 'idle' | 'saving' | 'error';

export interface TreeNodeRuntimeState {
  status: TreeNodeStatus;
  error?: string;
}

/** Flat node reference used by the tree panel. */
export interface FlatNode {
  id: string;
  name: string;
  parentName: string | null;
  isRemainder: boolean;
  conditionCount: number;
  hasChildren: boolean;
  depth: number;
  /** Path from root (names) for breadcrumbs. */
  path: string[];
}

/** Recursively flatten the dictionary tree into a list of FlatNode (DFS order). */
export function flattenTree(nodes: DictionaryNode[]): FlatNode[] {
  const out: FlatNode[] = [];
  const walk = (node: DictionaryNode, depth: number, pathPrefix: string[]): void => {
    const path = [...pathPrefix, node.name];
    out.push({
      id: node.id || node.name,
      name: node.name,
      parentName: node.parent_name,
      isRemainder: Boolean(node.is_remainder),
      conditionCount: node.condition_count,
      hasChildren: node.has_children,
      depth,
      path,
    });
    for (const child of node.children ?? []) {
      walk(child, depth + 1, path);
    }
  };
  for (const root of nodes) walk(root, 0, []);
  return out;
}

/** Build TreeData[] for the DS Tree component from DictionaryNode[]. */
export interface TreeDataLite {
  id: string;
  title: string;
  isRemainder: boolean;
  conditionCount: number;
  children: TreeDataLite[];
}
export function toTreeDataLite(nodes: DictionaryNode[]): TreeDataLite[] {
  return nodes.map((n) => ({
    id: n.id || n.name,
    title: n.name,
    isRemainder: Boolean(n.is_remainder),
    conditionCount: n.condition_count,
    children: toTreeDataLite(n.children ?? []),
  }));
}
