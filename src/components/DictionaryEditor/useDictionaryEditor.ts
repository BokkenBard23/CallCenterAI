/**
 * useDictionaryEditor — central state hook for DictionaryEditorPage.
 *
 * Responsibilities:
 *  - Fetch dictionary tree on mount (cancellable via AbortController).
 *  - Track selected node + its conditions.
 *  - Track per-row async status (saving / error / rollback snapshot).
 *  - Track tree-node runtime status (add/rename/delete in flight).
 *  - Track dirty state (unsaved inline edits) + beforeunload warn.
 *  - Expose CRUD operations that call the API client and update local state.
 *
 * Backend contract: PATCH /conditions/{idx} accepts logic_operator /
 * open_brackets / close_brackets but does NOT persist them per-row —
 * they are encoded into token_section on XML serialization. The FE
 * keeps them in EditorCondition local state and sends on PATCH.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  addDictionaryCondition,
  addDictionaryNode,
  deleteDictionaryCondition,
  deleteDictionaryNode,
  getDictionaryTree,
  reorderDictionaryConditions,
  updateDictionaryCondition,
  updateDictionaryNode,
  type ApiError,
} from '../../api/client';
import type {
  ConditionCreateRequest,
  ConditionUpdateRequest,
  DictionaryNode,
  NodeCreateRequest,
} from '../../types/api';
import {
  type EditorCondition,
  editorConditionFromCreate,
  toEditorCondition,
} from './types';
import { useDirtyState } from './useDirtyState';
import { DISTANCE_DEFAULT } from './constants';

export type EditorLoadStatus = 'loading' | 'ready' | 'error' | 'empty';

export interface UseDictionaryEditorResult {
  // Tree state
  tree: DictionaryNode[];
  treeStatus: EditorLoadStatus;
  treeError: string | null;
  reloadTree: () => void;

  // Selected node + conditions
  selectedNodeId: string | null;
  selectedNode: DictionaryNode | null;
  selectedPath: string[];
  selectNode: (nodeId: string) => void;

  conditions: EditorCondition[];
  conditionsStatus: EditorLoadStatus;
  conditionsError: string | null;

  // Per-row async state
  rowStates: Record<number, { status: 'idle' | 'saving' | 'error'; error?: string }>;
  // Tree-node async state
  treeNodeStates: Record<string, { status: 'idle' | 'saving' | 'error'; error?: string }>;

  // Dirty state
  dirty: boolean;
  markDirty: () => void;
  markClean: () => void;

  // Condition CRUD
  updateConditionField: <K extends keyof EditorCondition>(
    rowIdx: number,
    field: K,
    value: EditorCondition[K],
  ) => Promise<void>;
  addCondition: (afterIdx?: number) => Promise<void>;
  /**
   * Chunk 2: add a new condition pre-populated from an AI suggestion
   * (POST /nodes/{node_id}/conditions with suggestion fields).
   */
  addConditionFromSuggestion: (suggestion: {
    phrase: string;
    channel: string;
    distance: number;
  }) => Promise<void>;
  removeCondition: (rowIdx: number) => Promise<void>;
  duplicateCondition: (rowIdx: number) => Promise<void>;
  moveCondition: (rowIdx: number, direction: 'up' | 'down') => Promise<void>;

  // Node CRUD
  addNode: (name: string, parentName: string | null) => Promise<void>;
  renameNode: (nodeId: string, newName: string) => Promise<void>;
  removeNode: (nodeId: string) => Promise<void>;
}

function findNodeById(nodes: DictionaryNode[], nodeId: string): DictionaryNode | null {
  for (const n of nodes) {
    if ((n.id || n.name) === nodeId) return n;
    const child = findNodeById(n.children ?? [], nodeId);
    if (child) return child;
  }
  return null;
}

function findPath(nodes: DictionaryNode[], nodeId: string, prefix: string[] = []): string[] | null {
  for (const n of nodes) {
    const path = [...prefix, n.name];
    if ((n.id || n.name) === nodeId) return path;
    const child = findPath(n.children ?? [], nodeId, path);
    if (child) return child;
  }
  return null;
}

function errorMessage(err: unknown, fallback: string): string {
  if (err && typeof err === 'object' && 'status' in err) {
    const e = err as ApiError;
    return e.message || fallback;
  }
  return err instanceof Error ? err.message : fallback;
}

export function useDictionaryEditor(sessionId: string): UseDictionaryEditorResult {
  const [tree, setTree] = useState<DictionaryNode[]>([]);
  const [treeStatus, setTreeStatus] = useState<EditorLoadStatus>('loading');
  const [treeError, setTreeError] = useState<string | null>(null);

  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [conditions, setConditions] = useState<EditorCondition[]>([]);
  const [conditionsStatus, setConditionsStatus] = useState<EditorLoadStatus>('loading');
  const [conditionsError, setConditionsError] = useState<string | null>(null);

  const [rowStates, setRowStates] = useState<Record<number, { status: 'idle' | 'saving' | 'error'; error?: string }>>({});
  const [treeNodeStates, setTreeNodeStates] = useState<Record<string, { status: 'idle' | 'saving' | 'error'; error?: string }>>({});

  const abortRef = useRef<AbortController | null>(null);
  const { dirty, markDirty, markClean } = useDirtyState();

  const fetchTree = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setTreeStatus('loading');
    setTreeError(null);
    try {
      const data = await getDictionaryTree(sessionId, controller.signal);
      setTree(data);
      if (data.length === 0) {
        setTreeStatus('empty');
      } else {
        setTreeStatus('ready');
        // Auto-select first root if nothing selected.
        setSelectedNodeId((prev) => prev ?? (data[0].id || data[0].name));
      }
    } catch (err) {
      if (controller.signal.aborted) return;
      setTreeStatus('error');
      setTreeError(errorMessage(err, 'Не удалось загрузить дерево словарей'));
    }
  }, [sessionId]);

  useEffect(() => {
    void fetchTree();
    return () => abortRef.current?.abort();
  }, [fetchTree]);

  // When selectedNodeId changes, mirror the node's conditions into editor state.
  useEffect(() => {
    if (!selectedNodeId || treeStatus !== 'ready') {
      setConditions([]);
      setConditionsStatus('loading');
      return;
    }
    const node = findNodeById(tree, selectedNodeId);
    if (!node) {
      setConditions([]);
      setConditionsStatus('empty');
      return;
    }
    // NOTE: backend DictionaryCondition does not return logic_operator /
    // open_brackets / close_brackets — they are visual-only and encoded
    // in token_section on XML serialization. Editor defaults them to
    // empty/0 and lets the analyst author them, then exports XML.
    setConditions(node.conditions.map((c) => toEditorCondition(c)));
    setConditionsStatus(node.conditions.length === 0 ? 'empty' : 'ready');
    setConditionsError(null);
    setRowStates({});
  }, [selectedNodeId, tree, treeStatus]);

  const selectedNode = selectedNodeId ? findNodeById(tree, selectedNodeId) : null;
  const selectedPath = selectedNodeId ? findPath(tree, selectedNodeId) ?? [] : [];

  const reloadTree = useCallback(() => {
    void fetchTree();
  }, [fetchTree]);

  const selectNode = useCallback((nodeId: string) => {
    setSelectedNodeId(nodeId);
  }, []);

  // ── Condition CRUD ──────────────────────────────────────

  const updateConditionField = useCallback(
    async <K extends keyof EditorCondition>(
      rowIdx: number,
      field: K,
      value: EditorCondition[K],
    ) => {
      if (!selectedNodeId) return;
      const node = findNodeById(tree, selectedNodeId);
      if (!node) return;
      const dictName = tree.length > 0 ? tree[0].name : undefined;

      // Snapshot for rollback.
      const snapshot = conditions[rowIdx];
      if (!snapshot) return;

      // Optimistic update.
      setConditions((prev) =>
        prev.map((c, i) => (i === rowIdx ? { ...c, [field]: value } : c)),
      );
      setRowStates((prev) => ({ ...prev, [rowIdx]: { status: 'saving' } }));
      markDirty();

      const body: ConditionUpdateRequest = { [field]: value } as ConditionUpdateRequest;
      try {
        // JK2 FIX: backend `_find_node_recursive` (dictionary.py:253) matches
        // nodes by `node.name`, NOT by `node.id`. Sending `node.id` (e.g.
        // "test-dict-ui") returns 404. Always send `node.name` (e.g.
        // "Тестовый словарь UI"); client.ts already URL-encodes it.
        await updateDictionaryCondition(sessionId, node.name, rowIdx, body, dictName);
        setRowStates((prev) => ({ ...prev, [rowIdx]: { status: 'idle' } }));
        // Note: response does not include logic_operator/open_brackets/close_brackets,
        // so we keep our optimistic local state for those fields.
      } catch (err) {
        // Rollback.
        setConditions((prev) =>
          prev.map((c, i) => (i === rowIdx ? snapshot : c)),
        );
        setRowStates((prev) => ({
          ...prev,
          [rowIdx]: { status: 'error', error: errorMessage(err, 'Ошибка сохранения') },
        }));
      }
    },
    [conditions, sessionId, selectedNodeId, tree, markDirty],
  );

  const addCondition = useCallback(
    async (afterIdx?: number) => {
      if (!selectedNodeId) return;
      const node = findNodeById(tree, selectedNodeId);
      if (!node) return;
      const dictName = tree.length > 0 ? tree[0].name : undefined;

      const body: ConditionCreateRequest = {
        text: 'новая фраза',
        word_distance: DISTANCE_DEFAULT,
        channel_constraint: 'ANY',
        is_exact: false,
        logic_operator: '',
        open_brackets: 0,
        close_brackets: 0,
      };
      try {
        const res = await addDictionaryCondition(sessionId, node.name, body, dictName);
        const newCond = editorConditionFromCreate(res.condition);
        setConditions((prev) => {
          const next = [...prev];
          if (afterIdx === undefined || afterIdx < 0 || afterIdx >= next.length) {
            next.push(newCond);
          } else {
            next.splice(afterIdx + 1, 0, newCond);
          }
          return next;
        });
        setConditionsStatus('ready');
        markDirty();
      } catch (err) {
        // JK3 FIX: also set conditionsStatus='error' so DictionaryEditorPage's
        // InlineAlert renders the error message. Previously only
        // setConditionsError() was called, leaving InlineAlert hidden.
        setConditionsError(errorMessage(err, 'Не удалось добавить условие'));
        setConditionsStatus('error');
      }
    },
    [sessionId, selectedNodeId, tree, markDirty],
  );

  const removeCondition = useCallback(
    async (rowIdx: number) => {
      if (!selectedNodeId) return;
      const node = findNodeById(tree, selectedNodeId);
      if (!node) return;
      const dictName = tree.length > 0 ? tree[0].name : undefined;
      try {
        await deleteDictionaryCondition(sessionId, node.name, rowIdx, dictName);
        setConditions((prev) => prev.filter((_, i) => i !== rowIdx));
        setRowStates((prev) => {
          const next = { ...prev };
          delete next[rowIdx];
          return next;
        });
        markDirty();
      } catch (err) {
        setRowStates((prev) => ({
          ...prev,
          [rowIdx]: { status: 'error', error: errorMessage(err, 'Не удалось удалить') },
        }));
      }
    },
    [sessionId, selectedNodeId, tree, markDirty],
  );

  const addConditionFromSuggestion = useCallback(
    async (suggestion: { phrase: string; channel: string; distance: number }) => {
      if (!selectedNodeId) return;
      const node = findNodeById(tree, selectedNodeId);
      if (!node) return;
      const dictName = tree.length > 0 ? tree[0].name : undefined;
      const body: ConditionCreateRequest = {
        text: suggestion.phrase,
        word_distance: suggestion.distance,
        channel_constraint: suggestion.channel,
        is_exact: false,
        logic_operator: '',
        open_brackets: 0,
        close_brackets: 0,
      };
      try {
        const res = await addDictionaryCondition(sessionId, node.name, body, dictName);
        const newCond = editorConditionFromCreate(res.condition);
        setConditions((prev) => [...prev, newCond]);
        setConditionsStatus('ready');
        markDirty();
      } catch (err) {
        // JK3 FIX: mirror addCondition — also set status='error'.
        setConditionsError(errorMessage(err, 'Не удалось добавить фразу из подсказки'));
        setConditionsStatus('error');
      }
    },
    [sessionId, selectedNodeId, tree, markDirty],
  );

  const duplicateCondition = useCallback(
    async (rowIdx: number) => {
      if (!selectedNodeId) return;
      const node = findNodeById(tree, selectedNodeId);
      if (!node) return;
      const dictName = tree.length > 0 ? tree[0].name : undefined;
      const src = conditions[rowIdx];
      if (!src) return;
      const body: ConditionCreateRequest = {
        text: src.text,
        word_distance: src.word_distance,
        channel_constraint: src.channel_constraint,
        is_exact: src.is_exact,
        is_exception: src.is_exception,
        phrase_groups: src.phrase_groups,
        logic_operator: src.logic_operator,
        open_brackets: src.open_brackets,
        close_brackets: src.close_brackets,
      };
      try {
        const res = await addDictionaryCondition(sessionId, node.name, body, dictName);
        const newCond = editorConditionFromCreate(
          res.condition,
          src.logic_operator,
          src.open_brackets,
          src.close_brackets,
        );
        setConditions((prev) => {
          const next = [...prev];
          next.splice(rowIdx + 1, 0, newCond);
          return next;
        });
        markDirty();
      } catch (err) {
        // JK3 FIX: mirror addCondition — also set status='error'.
        setConditionsError(errorMessage(err, 'Не удалось дублировать'));
        setConditionsStatus('error');
      }
    },
    [conditions, sessionId, selectedNodeId, tree, markDirty],
  );

  const moveCondition = useCallback(
    async (rowIdx: number, direction: 'up' | 'down') => {
      if (!selectedNodeId) return;
      const node = findNodeById(tree, selectedNodeId);
      if (!node) return;
      const dictName = tree.length > 0 ? tree[0].name : undefined;
      const targetIdx = direction === 'up' ? rowIdx - 1 : rowIdx + 1;
      if (targetIdx < 0 || targetIdx >= conditions.length) return;

      // Optimistic swap.
      setConditions((prev) => {
        const next = [...prev];
        [next[rowIdx], next[targetIdx]] = [next[targetIdx], next[rowIdx]];
        return next;
      });
      markDirty();

      // Build new_order = current indices with the swap applied.
      const order = conditions.map((_, i) => i);
      [order[rowIdx], order[targetIdx]] = [order[targetIdx], order[rowIdx]];
      try {
        await reorderDictionaryConditions(sessionId, node.name, { new_order: order }, dictName);
      } catch (err) {
        // Rollback swap.
        setConditions((prev) => {
          const next = [...prev];
          [next[rowIdx], next[targetIdx]] = [next[targetIdx], next[rowIdx]];
          return next;
        });
        // JK3 FIX: mirror addCondition — also set status='error'.
        setConditionsError(errorMessage(err, 'Не удалось переместить'));
        setConditionsStatus('error');
      }
    },
    [conditions, sessionId, selectedNodeId, tree, markDirty],
  );

  // ── Node CRUD ───────────────────────────────────────────

  const addNode = useCallback(
    async (name: string, parentName: string | null) => {
      const body: NodeCreateRequest = { name, parent_name: parentName };
      try {
        await addDictionaryNode(sessionId, body);
        await fetchTree();
      } catch (err) {
        setTreeError(errorMessage(err, 'Не удалось создать узел'));
      }
    },
    [sessionId, fetchTree],
  );

  const renameNode = useCallback(
    async (nodeId: string, newName: string) => {
      const node = findNodeById(tree, nodeId);
      if (!node) return;
      setTreeNodeStates((prev) => ({ ...prev, [nodeId]: { status: 'saving' } }));
      try {
        await updateDictionaryNode(sessionId, node.name, { name: newName });
        await fetchTree();
        setTreeNodeStates((prev) => ({ ...prev, [nodeId]: { status: 'idle' } }));
        markDirty();
      } catch (err) {
        setTreeNodeStates((prev) => ({
          ...prev,
          [nodeId]: { status: 'error', error: errorMessage(err, 'Не удалось переименовать') },
        }));
      }
    },
    [sessionId, tree, fetchTree, markDirty],
  );

  const removeNode = useCallback(
    async (nodeId: string) => {
      const node = findNodeById(tree, nodeId);
      if (!node) return;
      const dictName = tree.length > 0 ? tree[0].name : undefined;
      setTreeNodeStates((prev) => ({ ...prev, [nodeId]: { status: 'saving' } }));
      try {
        await deleteDictionaryNode(sessionId, node.name, dictName);
        if (selectedNodeId === nodeId) setSelectedNodeId(null);
        await fetchTree();
        setTreeNodeStates((prev) => ({ ...prev, [nodeId]: { status: 'idle' } }));
        markDirty();
      } catch (err) {
        setTreeNodeStates((prev) => ({
          ...prev,
          [nodeId]: { status: 'error', error: errorMessage(err, 'Не удалось удалить узел') },
        }));
      }
    },
    [sessionId, tree, selectedNodeId, fetchTree, markDirty],
  );

  return {
    tree,
    treeStatus,
    treeError,
    reloadTree,
    selectedNodeId,
    selectedNode,
    selectedPath,
    selectNode,
    conditions,
    conditionsStatus,
    conditionsError,
    rowStates,
    treeNodeStates,
    dirty,
    markDirty,
    markClean,
    updateConditionField,
    addCondition,
    addConditionFromSuggestion,
    removeCondition,
    duplicateCondition,
    moveCondition,
    addNode,
    renameNode,
    removeNode,
  };
}
