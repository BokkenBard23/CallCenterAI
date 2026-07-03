/**
 * useSpeechLabState — hook encapsulating SpeechLab page local state + callbacks.
 * Deduplicates state with AnalysisContext where possible.
 *
 * State kept local:
 *   - treeNodes (local preview, overrides context)
 *   - selectedNodeId (UI-only)
 *   - expandedNodes (UI-only)
 *   - rtfDialogOpen, rtfFileName, rtfUploading, rtfError (Dialog-only)
 *
 * Delegated to context:
 *   - isSearching → state.analysisStatus === 'analyzing'
 *   - searchError → state.analysisError
 */

import { useState, useCallback, useMemo } from 'react';
import { useAnalysisContext } from '../context/AnalysisContext';
import { uploadRtf, analyze } from '../api/client';
import type { SpeechLabTreeNode } from '../types/speechlab';
import type { DictionaryNode, UploadDictionaryResponse } from '../types/api';

// ═══════════════════════════════════════════════════════════
// Types
// ═══════════════════════════════════════════════════════════

export interface SpeechLabState {
  treeNodes: SpeechLabTreeNode[];
  selectedNodeId: string | null;
  expandedNodes: Record<string, boolean>;
  rtfDialogOpen: boolean;
  rtfFileName: string | null;
  rtfUploading: boolean;
  rtfError: string | null;
}

export interface SpeechLabDerived {
  hasSession: boolean;
  selectedNode: SpeechLabTreeNode | null;
  effectiveTreeNodes: SpeechLabTreeNode[];
  isSearching: boolean;
  searchError: string | null;
}

export interface SpeechLabActions {
  handleDictionaryUploaded: (
    sessionId: string,
    nodes: SpeechLabTreeNode[],
    response: UploadDictionaryResponse,
  ) => void;
  handleSelectNode: (node: SpeechLabTreeNode) => void;
  handleToggleExpand: (nodeId: string, expanded: boolean) => void;
  handleRtfSelect: (file: File) => void;
  handleRtfUpload: () => Promise<void>;
  openRtfDialog: () => void;
  closeRtfDialog: () => void;
  handleRunAnalysis: () => Promise<void>;
}

// ═══════════════════════════════════════════════════════════
// Helpers
// ═══════════════════════════════════════════════════════════

/** Find a node in the tree by ID */
function findNodeById(nodes: SpeechLabTreeNode[], id: string): SpeechLabTreeNode | null {
  for (const node of nodes) {
    if (node.id === id) return node;
    const found = findNodeById(node.children, id);
    if (found) return found;
  }
  return null;
}

/** Convert DictionaryNode (from API) to SpeechLabTreeNode */
function dictNodeToSpeechLabNode(dict: DictionaryNode): SpeechLabTreeNode {
  return {
    id: dict.id,
    name: dict.name,
    has_children: dict.has_children,
    children_count: dict.children_count,
    is_remainder: false,
    display_tokens: [],
    children: dict.children.map(dictNodeToSpeechLabNode),
    attributes: [],
  };
}

// ═══════════════════════════════════════════════════════════
// Hook
// ═══════════════════════════════════════════════════════════

export function useSpeechLabState(): {
  state: SpeechLabState;
  actions: SpeechLabActions;
  derived: SpeechLabDerived;
} {
  const { state: ctxState, dispatch } = useAnalysisContext();

  // ─── Local state ─────────────────────────────────────────
  const [treeNodes, setTreeNodes] = useState<SpeechLabTreeNode[]>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [expandedNodes, setExpandedNodes] = useState<Record<string, boolean>>({});
  const [rtfDialogOpen, setRtfDialogOpen] = useState(false);
  const [rtfFileName, setRtfFileName] = useState<string | null>(null);
  const [rtfFile, setRtfFile] = useState<File | null>(null);
  const [rtfUploading, setRtfUploading] = useState(false);
  const [rtfError, setRtfError] = useState<string | null>(null);

  // ─── Derived state ────────────────────────────────────────

  // Context tree nodes (from uploaded dictionaries)
  const contextTreeNodes = useMemo<SpeechLabTreeNode[]>(() => {
    if (ctxState.dictionaries.length === 0) return [];
    return ctxState.dictionaries
      .filter((d) => d.response?.dictionary)
      .map((d) => dictNodeToSpeechLabNode(d.response!.dictionary!));
  }, [ctxState.dictionaries]);

  // Effective: local preview overrides context
  const effectiveTreeNodes = treeNodes.length > 0 ? treeNodes : contextTreeNodes;

  // Has RTF session?
  const hasSession = !!ctxState.sessionId;

  // Selected node
  const selectedNode = useMemo(() => {
    if (!selectedNodeId || effectiveTreeNodes.length === 0) return null;
    return findNodeById(effectiveTreeNodes, selectedNodeId);
  }, [selectedNodeId, effectiveTreeNodes]);

  // Delegated to context
  const isSearching = ctxState.analysisStatus === 'analyzing';
  const searchError = ctxState.analysisError;

  // ─── Actions ──────────────────────────────────────────────

  const handleDictionaryUploaded = useCallback(
    (sessionId: string, nodes: SpeechLabTreeNode[], response: UploadDictionaryResponse) => {
      setTreeNodes(nodes);
      // Reset selected node when tree changes to avoid stale references
      setSelectedNodeId(null);

      const targetSessionId = ctxState.sessionId ?? sessionId;
      dispatch({ type: 'SET_SESSION_ID', payload: targetSessionId });

      if (targetSessionId === sessionId && response) {
        const exists = ctxState.dictionaries.some((d) => d.response?.session_id === sessionId);
        if (!exists) {
          dispatch({ type: 'ADD_DICTIONARY', payload: response });
        }
      }
    },
    [ctxState.sessionId, ctxState.dictionaries, dispatch],
  );

  const handleSelectNode = useCallback((node: SpeechLabTreeNode) => {
    setSelectedNodeId(node.id);
  }, []);

  const handleToggleExpand = useCallback((nodeId: string, expanded: boolean) => {
    setExpandedNodes((prev) => ({ ...prev, [nodeId]: expanded }));
  }, []);

  const handleRtfSelect = useCallback((file: File) => {
    setRtfFileName(file.name);
    setRtfFile(file);
  }, []);

  const handleRtfUpload = useCallback(async () => {
    if (!rtfFile) return;

    setRtfUploading(true);
    setRtfError(null);

    try {
      const result = await uploadRtf(rtfFile, ctxState.sessionId ?? undefined);
      const finalSessionId = ctxState.sessionId ?? result.session_id;
      dispatch({ type: 'SET_SESSION_ID', payload: finalSessionId });
      dispatch({ type: 'SET_DIALOGUE', payload: result.dialogue });

      setRtfDialogOpen(false);
      setRtfFileName(null);
      setRtfFile(null);
      setRtfUploading(false);
    } catch (err) {
      setRtfError(err instanceof Error ? err.message : 'Ошибка загрузки RTF');
      setRtfUploading(false);
    }
  }, [rtfFile, ctxState.sessionId, dispatch]);

  const openRtfDialog = useCallback(() => {
    setRtfDialogOpen(true);
    setRtfFileName(null);
    setRtfFile(null);
    setRtfError(null);
  }, []);

  const closeRtfDialog = useCallback(() => {
    setRtfDialogOpen(false);
    setRtfFileName(null);
    setRtfFile(null);
    setRtfError(null);
  }, []);

  const handleRunAnalysis = useCallback(async () => {
    if (!ctxState.sessionId) return;

    dispatch({ type: 'SET_ANALYSIS_STATUS', payload: 'analyzing' });
    dispatch({ type: 'SET_ANALYSIS_ERROR', payload: null });

    try {
      const result = await analyze({
        session_id: ctxState.sessionId,
        dictionary_ids: ctxState.dictionaries
          .filter((d) => d.response?.dictionary?.name)
          .map((d) => d.response!.dictionary!.name),
        llm_provider: ctxState.selectedProvider ?? 'openai',
        llm_model: ctxState.selectedModel ?? undefined,
        include_summary: true,
        include_restructured: false,
      });

      if (result) {
        dispatch({
          type: 'SET_ANALYSIS_RESULTS',
          payload: { searchResult: result.search_result, llmResult: result.llm_result },
        });
        dispatch({ type: 'SET_ANALYSIS_STATUS', payload: 'completed' });
      }
    } catch (err) {
      dispatch({
        type: 'SET_ANALYSIS_ERROR',
        payload: err instanceof Error ? err.message : 'Ошибка анализа',
      });
      dispatch({ type: 'SET_ANALYSIS_STATUS', payload: 'error' });
    }
  }, [ctxState.sessionId, ctxState.dictionaries, ctxState.selectedProvider, ctxState.selectedModel, dispatch]);

  return {
    state: {
      treeNodes,
      selectedNodeId,
      expandedNodes,
      rtfDialogOpen,
      rtfFileName,
      rtfUploading,
      rtfError,
    },
    actions: {
      handleDictionaryUploaded,
      handleSelectNode,
      handleToggleExpand,
      handleRtfSelect,
      handleRtfUpload,
      openRtfDialog,
      closeRtfDialog,
      handleRunAnalysis,
    },
    derived: {
      hasSession,
      selectedNode,
      effectiveTreeNodes,
      isSearching,
      searchError,
    },
  };
}


