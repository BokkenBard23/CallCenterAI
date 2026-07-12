/**
 * LeftPanel — sidebar container with:
 *   - Title "Словарь"
 *   - Search TextField
 *   - "Импорт XML" Button
 *   - SpeechLabTree (scrollable)
 *   - XML Import Dialog
 *
 * From design-spec-chunk-2:
 *   - Flex column, height: 100%
 *   - Compact header + search + import button
 *   - Scrollable tree area (flex: 1)
 *   - Empty state: "Загрузите XML-словарь"
 */

import React, { useState, useCallback, useRef, useEffect } from 'react';
import {
  Box,
  Button,
  Dialog,
  Divider,
  FileUploader,
  Icon,
  InlineAlert,
  Skeleton,
  Stack,
  TextField,
  Typography,
} from '@beeline/design-system-react';
import { Icons } from '@beeline/design-tokens/js/iconfont';

import type { SpeechLabTreeNode, DisplayToken } from '../../../types/speechlab';
import type { DictionaryNode, UploadDictionaryResponse } from '../../../types/api';
import { parseFullXml } from '../../../utils/xmlParser';
import { uploadDictionary } from '../../../api/client';
import SpeechLabTree from './SpeechLabTree';

import './LeftPanel.scss';

interface LeftPanelProps {
  /** Tree nodes from backend or preview parser */
  treeNodes: SpeechLabTreeNode[];
  /** Currently selected node ID */
  selectedNodeId: string | null;
  /** Callback when a node is selected */
  onSelectNode: (node: SpeechLabTreeNode) => void;
  /** Callback when a node is expanded/collapsed */
  onToggleExpand?: (nodeId: string, expanded: boolean) => void;
  /** Callback when dictionary is uploaded to backend */
  onDictionaryUploaded: (sessionId: string, nodes: SpeechLabTreeNode[], response: UploadDictionaryResponse) => void;
  /** Session ID for API calls */
  sessionId: string | null;
  /** Whether the tree is loading */
  isLoading?: boolean;
  /** Error message */
  error?: string | null;
  /** Currently expanded nodes */
  expandedNodes?: Record<string, boolean>;
}

export default function LeftPanel({
  treeNodes,
  onSelectNode,
  onToggleExpand,
  onDictionaryUploaded,
  sessionId,
  isLoading = false,
  error = null,
  expandedNodes,
}: LeftPanelProps) {
  const [searchQuery, setSearchQuery] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // P1-3: Debounce search by 300ms
  useEffect(() => {
    if (debounceRef.current !== null) {
      clearTimeout(debounceRef.current);
    }
    debounceRef.current = setTimeout(() => {
      setDebouncedQuery(searchQuery);
    }, 300);
    return () => {
      if (debounceRef.current !== null) {
        clearTimeout(debounceRef.current);
      }
    };
  }, [searchQuery]);

  const [importDialogOpen, setImportDialogOpen] = useState(false);
  const [previewNodes, setPreviewNodes] = useState<SpeechLabTreeNode[]>([]);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Handle file selection for preview (via DS FileUploader onChange)
  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setPreviewError(null);
    setUploadError(null);

    const reader = new FileReader();
    reader.onload = (ev) => {
      try {
        const xmlString = ev.target?.result as string;
        const nodes = parseFullXml(xmlString);
        setPreviewNodes(nodes);
      } catch (err) {
        setPreviewError(
          err instanceof Error ? err.message : 'Ошибка парсинга XML'
        );
        setPreviewNodes([]);
      }
    };
    reader.onerror = () => {
      setPreviewError('Ошибка чтения файла');
    };
    reader.readAsText(file);
  }, []);

  // Upload to backend (works with or without sessionId — backend creates session if needed)
  const handleUploadToServer = useCallback(async () => {
    const file = fileInputRef.current?.files?.[0];
    if (!file) return;

    setIsUploading(true);
    setUploadError(null);

    try {
      const response = await uploadDictionary(file, sessionId ?? undefined);
      
      // Build SpeechLabTreeNodes from backend response (richer than preview)
      let backendNodes: SpeechLabTreeNode[] = [];

      if (response.dictionary) {
        // Backend returned full parsed dictionary — use it
        const dictNode = response.dictionary;
        backendNodes = [dictNodeToSpeechLabNode(dictNode, response.display_tokens)];
      } else if (previewNodes.length > 0) {
        // Fall back to preview if backend didn't return dictionary
        backendNodes = previewNodes;
      }

      onDictionaryUploaded(response.session_id, backendNodes, response);
      setImportDialogOpen(false);
      setPreviewNodes([]);
      setPreviewError(null);
    } catch (err) {
      setUploadError(
        err instanceof Error ? err.message : 'Ошибка загрузки на сервер'
      );
    } finally {
      setIsUploading(false);
    }
  }, [sessionId, previewNodes, onDictionaryUploaded]);

  // Open import dialog
  const handleOpenImport = useCallback(() => {
    setImportDialogOpen(true);
    setPreviewNodes([]);
    setPreviewError(null);
    setUploadError(null);
  }, []);

  // Close import dialog
  const handleCloseImport = useCallback(() => {
    setImportDialogOpen(false);
    setPreviewNodes([]);
    setPreviewError(null);
    setUploadError(null);
  }, []);

  return (
    <Box className="left-panel">
      {/* Header */}
      <Box className="left-panel__header" padding="x3">
        <Typography variant="h6">Словарь</Typography>
      </Box>

      <Divider />

      {/* Search + Import */}
      <Box className="left-panel__controls" padding="x2">
        <TextField
          placeholder="Поиск по словарю"
          value={searchQuery}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
            setSearchQuery(e.target.value)
          }
          style={{ width: '100%' }}
        />
        <Button
          variant="secondary"
          size="small"
          onClick={handleOpenImport}
          style={{ marginTop: '8px', width: '100%' }}
        >
          <Icon iconName={Icons.Upload} size="small" />
          Импорт XML
        </Button>
      </Box>

      <Divider />

      {/* Tree area */}
      <Box className="left-panel__tree">
        {isLoading ? (
          <Box padding="x3">
            <Skeleton variant="text" width="100%" height={24} />
            <Skeleton variant="text" width="80%" height={24} />
            <Skeleton variant="text" width="60%" height={24} />
          </Box>
        ) : error ? (
          <Box padding="x3">
            <Typography variant="body2" style={{ color: 'var(--color-status-error, #d32f2f)' }}>
              {error}
            </Typography>
          </Box>
        ) : treeNodes.length === 0 ? (
          <Box className="left-panel__empty" padding="x4">
            <Icon iconName={Icons.Search} size="large" />
            <Typography variant="body2" inactive>
              Загрузите XML-словарь
            </Typography>
          </Box>
        ) : (
          <SpeechLabTree
            nodes={treeNodes}
            onSelectNode={onSelectNode}
            onToggleExpand={onToggleExpand}
            searchQuery={debouncedQuery}
            expandedNodes={expandedNodes}
          />
        )}
      </Box>

      {/* Import Dialog */}
      <Dialog open={importDialogOpen} onClose={handleCloseImport}>
        <Box className="left-panel__dialog" padding="x4">
          <Stack direction="vertical" spacing="x4">
            <Typography variant="h5">Импорт XML-словаря</Typography>

            {/* DS FileUploader — drag-drop zone + file picker */}
            <FileUploader
              ref={fileInputRef as React.Ref<HTMLInputElement>}
              title="Перетащите XML-файл или нажмите для выбора"
              subTitle="Поддерживается .xml формат"
              dragOverTitle="Отпустите для загрузки"
              accept=".xml"
              multiple={false}
              hideFileList={true}
              error={!!previewError}
              onChange={handleFileSelect}
            />

            {/* Preview error (custom ErrorList — CONFLICT C3 fix) */}
            {previewError && (
              <InlineAlert type="error">
                Ошибка предпросмотра: {previewError}
              </InlineAlert>
            )}

            {/* Upload error */}
            {uploadError && (
              <InlineAlert type="error">
                Ошибка загрузки: {uploadError}
              </InlineAlert>
            )}

            {/* Preview tree */}
            {previewNodes.length > 0 && (
              <Box className="left-panel__preview">
                <Typography variant="caption" inactive>
                  Предпросмотр:
                </Typography>
                <SpeechLabTree
                  nodes={previewNodes}
                  onSelectNode={() => {}}
                />
              </Box>
            )}

            {/* Actions */}
            <Stack direction="horizontal" spacing="x2" justify="end">
              <Button variant="secondary" onClick={handleCloseImport}>
                Отмена
              </Button>
              <Button
                variant="primary"
                onClick={handleUploadToServer}
                disabled={previewNodes.length === 0 || isUploading}
              >
                {isUploading ? 'Загрузка...' : 'Загрузить на сервер'}
              </Button>
            </Stack>
          </Stack>
        </Box>
      </Dialog>
    </Box>
  );
}

/** Convert DictionaryNode (from backend API) to SpeechLabTreeNode */
function dictNodeToSpeechLabNode(
  dict: DictionaryNode,
  rootDisplayTokens?: DisplayToken[] | null,
): SpeechLabTreeNode {
  return {
    id: dict.id,
    name: dict.name,
    has_children: dict.has_children,
    children_count: dict.children_count,
    is_remainder: false,
    // Root-level display tokens from backend (richer than preview)
    display_tokens: rootDisplayTokens ?? [],
    children: dict.children.map((child) => dictNodeToSpeechLabNode(child)),
    attributes: [],
  };
}
