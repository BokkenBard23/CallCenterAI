/**
 * DictionaryEditorPage — page shell for the LexiCore Port Phase 2
 * FE Dictionary Editor.
 *
 * Route: /dictionary/:sessionId
 *
 * Layout: Box (full viewport) + Stack header (sticky, 56px) +
 * responsive 2-column composition (Tree sidebar | ConditionsTable main).
 *   - desktop (≥1024px): sidebar 280px, main flex-grow.
 *   - tablet  (768–1023px): sidebar 240px.
 *   - mobile  (<768px): sidebar hidden, opened via Drawer (☰ button).
 *
 * Header: Typography (title) + Breadcrumbs (path) + Badge (dirty) +
 * 6 placeholder action buttons for Chunk 2 (AI/Suggestions/Duplicates/
 * Validation/Statistics/Export) + collapse toggle IconButton.
 *
 * States: loading (Skeleton), ready, error (InlineAlert + retry),
 * empty (prompt → /upload), dirty (Badge).
 */

import { useCallback, useMemo, useState, type ReactNode } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Badge,
  Box,
  Breadcrumbs,
  Button,
  Icon,
  IconButton,
  InlineAlert,
  Sidesheet,
  Skeleton,
  Stack,
  Typography,
} from '@beeline/design-system-react';
import { Icons } from '@beeline/design-tokens/js/iconfont';

import { AIAnalysisPanel } from '../components/DictionaryEditor/AIAnalysisPanel';
import { ConditionsTable } from '../components/DictionaryEditor/ConditionsTable';
import { DictionaryTreePanel } from '../components/DictionaryEditor/DictionaryTreePanel';
import { DuplicatesModal } from '../components/DictionaryEditor/DuplicatesModal';
import { PhraseSuggestionsModal } from '../components/DictionaryEditor/PhraseSuggestionsModal';
import { SearchFilterBar, type SearchFilterValue } from '../components/DictionaryEditor/SearchFilterBar';
import { StatisticsPanel } from '../components/DictionaryEditor/StatisticsPanel';
import { ValidationIssuesPanel } from '../components/DictionaryEditor/ValidationIssuesPanel';
import { XmlExportDialog } from '../components/DictionaryEditor/XmlExportDialog';
import { MiningPanel } from '../components/DictionaryEditor/MiningPanel';
import { useDictionaryEditor } from '../components/DictionaryEditor/useDictionaryEditor';
import type { DictionarySuggestion } from '../types/api';
import './DictionaryEditorPage.scss';
import './DictionaryEditorPage.css';

/** Chunk 2 overlay visibility state. */
interface Chunk2Overlays {
  ai: boolean;
  suggest: boolean;
  dup: boolean;
  val: boolean;
  stat: boolean;
  xml: boolean;
  mining: boolean;
}

const INITIAL_OVERLAYS: Chunk2Overlays = {
  ai: false,
  suggest: false,
  dup: false,
  val: false,
  stat: false,
  xml: false,
  mining: false,
};

/** Header action buttons (Chunk 2) — wired to overlay visibility. */
const CHUNK2_ACTIONS: {
  key: keyof Chunk2Overlays;
  label: string;
  icon: Icons;
}[] = [
  { key: 'ai', label: 'AI анализ', icon: Icons.CpuWarning },
  { key: 'suggest', label: 'Подсказать фразы', icon: Icons.Magic },
  { key: 'dup', label: 'Дубликаты', icon: Icons.Copy },
  { key: 'val', label: 'Валидация', icon: Icons.Check },
  { key: 'stat', label: 'Статистика', icon: Icons.DataTransferCheck },
  { key: 'xml', label: 'Экспорт XML', icon: Icons.Download },
  { key: 'mining', label: 'Mining', icon: Icons.Search },
];

export default function DictionaryEditorPage(): ReactNode {
  const { sessionId = '' } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const editor = useDictionaryEditor(sessionId);

  const [filter, setFilter] = useState<SearchFilterValue>({ text: '', channel: '' });
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileTreeOpen, setMobileTreeOpen] = useState(false);

  // Chunk 2 overlay visibility (Sidesheet / Modals / Dialog).
  const [overlays, setOverlays] = useState<Chunk2Overlays>(INITIAL_OVERLAYS);
  const openOverlay = useCallback((key: keyof Chunk2Overlays) => {
    setOverlays((prev) => ({ ...prev, [key]: true }));
  }, []);
  const closeOverlay = useCallback((key: keyof Chunk2Overlays) => {
    setOverlays((prev) => ({ ...prev, [key]: false }));
  }, []);

  // Chunk 2 jump-to-condition: highlight + scroll target row in ConditionsTable.
  const [highlightRowIdx, setHighlightRowIdx] = useState<number | null>(null);
  const handleJumpToCondition = useCallback((rowIdx: number) => {
    setHighlightRowIdx(rowIdx);
  }, []);

  // Derived: root dictionary names + current dict_name for Chunk 2 endpoints.
  const editorTree = editor.tree;
  const rootDictNames = useMemo(() => editorTree.map((n) => n.name), [editorTree]);
  const selectedDictName = useMemo(() => {
    if (!editor.selectedNode) return null;
    // Find root ancestor for the selected node — Chunk 2 endpoints scope by root dict_name.
    let cursor = editor.selectedNode;
    while (cursor.parent_name) {
      const parent = editorTree.find((n) => n.name === cursor.parent_name);
      if (!parent) break;
      cursor = parent;
    }
    return cursor.name;
  }, [editor.selectedNode, editorTree]);

  // Phrase suggestions → add to conditions (delegates to editor).
  const handleAddSuggestion = useCallback(
    (suggestion: DictionarySuggestion) => {
      return editor.addConditionFromSuggestion(suggestion);
    },
    [editor],
  );

  const handleAddCondition = useCallback(
    (afterIdx?: number) => {
      void editor.addCondition(afterIdx);
    },
    [editor],
  );

  const crumbs = useMemo(() => {
    const items = [{ label: 'Словари' }];
    for (const p of editor.selectedPath) items.push({ label: p });
    return items;
  }, [editor.selectedPath]);

  // ── Page-level states ────────────────────────────────────

  if (editor.treeStatus === 'loading') {
    return (
      <Box className="dict-editor dict-editor--loading" padding="x4">
        <Stack direction="vertical" gap="x3">
          <Skeleton variant="title" width="40%" />
          <Skeleton variant="text" width="100%" height={56} />
          <Stack direction="horizontal" gap="x3">
            <Skeleton variant="text" width="280px" height={400} />
            <Skeleton variant="text" width="100%" height={400} />
          </Stack>
        </Stack>
      </Box>
    );
  }

  if (editor.treeStatus === 'error') {
    return (
      <Box className="dict-editor dict-editor--error" padding="x4">
        <Stack direction="vertical" gap="x3" align="start">
          <InlineAlert type="error">
            {editor.treeError ?? 'Не удалось загрузить словарь'}
          </InlineAlert>
          <Button variant="contained" onClick={editor.reloadTree}>
            Повторить
          </Button>
        </Stack>
      </Box>
    );
  }

  if (editor.treeStatus === 'empty') {
    return (
      <Box className="dict-editor dict-editor--empty" padding="x6">
        <Stack direction="vertical" gap="x4" align="center">
          <Typography variant="h5">Нет словарей в сессии</Typography>
          <Typography variant="body1" color="colorTextInactive">
            Загрузите XML-файл словаря, чтобы начать редактирование.
          </Typography>
          <Button
            variant="contained"
            startIcon={<Icon iconName={Icons.Upload} />}
            onClick={() => navigate('/')}
          >
            Загрузить словарь
          </Button>
        </Stack>
      </Box>
    );
  }

  // ── Ready ────────────────────────────────────────────────

  return (
    <Box className="dict-editor">
      {/* Sticky header */}
      <header className="dict-editor__header">
        <Stack direction="horizontal" gap="x3" align="center" justify="space-between">
          <Stack direction="horizontal" gap="x2" align="center">
            <IconButton
              iconName={Icons.Menu}
              variant="plain"
              aria-label="Показать дерево словарей"
              className="dict-editor__mobile-tree-toggle"
              onClick={() => setMobileTreeOpen((v) => !v)}
            />
            <Typography variant="h6">Редактор словарей</Typography>
            {crumbs.length > 1 && (
              <Breadcrumbs value={crumbs.map((c, i) => ({
                label: c.label,
                currentPage: i === crumbs.length - 1,
              }))} />
            )}
            {editor.dirty && (
              <Badge type="tertiary" semantic="warning" dot>
                Несохранённые изменения
              </Badge>
            )}
          </Stack>
          <Stack direction="horizontal" gap="x2" align="center" wrap="wrap">
            {CHUNK2_ACTIONS.map((a) => (
              <Button
                key={a.key}
                variant="outlined"
                size="small"
                startIcon={<Icon iconName={a.icon} />}
                disabled={editor.conditionsStatus !== 'ready' && editor.conditionsStatus !== 'empty'}
                title={a.label}
                onClick={() => openOverlay(a.key)}
              >
                {a.label}
              </Button>
            ))}
            <IconButton
              iconName={sidebarCollapsed ? Icons.NavArrowRight : Icons.NavArrowLeft}
              variant="plain"
              aria-label={sidebarCollapsed ? 'Развернуть панель' : 'Свернуть панель'}
              onClick={() => setSidebarCollapsed((v) => !v)}
            />
          </Stack>
        </Stack>
      </header>

      {/* Two-column body */}
      <div className={`dict-editor__body ${sidebarCollapsed ? 'dict-editor__body--collapsed' : ''}`}>
        {!sidebarCollapsed && (
          <aside className={`dict-editor__sidebar ${mobileTreeOpen ? 'dict-editor__sidebar--mobile-open' : ''}`}>
            <DictionaryTreePanel
              tree={editor.tree}
              selectedNodeId={editor.selectedNodeId}
              treeNodeStates={editor.treeNodeStates}
              status={editor.treeStatus}
              error={editor.treeError}
              onSelect={(id) => {
                editor.selectNode(id);
                setMobileTreeOpen(false);
              }}
              onAddNode={(name, parent) => void editor.addNode(name, parent)}
              onRenameNode={(id, name) => void editor.renameNode(id, name)}
              onRemoveNode={(id) => void editor.removeNode(id)}
            />
          </aside>
        )}

        <main className="dict-editor__main">
          <Stack direction="vertical" gap="x3">
            <SearchFilterBar
              initialValue={filter}
              onChange={setFilter}
              matchedCount={(() => {
                const q = filter.text.trim().toLowerCase();
                const ch = filter.channel;
                if (!q && !ch) return editor.conditions.length;
                return editor.conditions.filter((c) => {
                  const textMatch = !q || c.text.toLowerCase().includes(q);
                  const channelMatch = !ch || c.channel_constraint === ch;
                  return textMatch && channelMatch;
                }).length;
              })()}
              hasRows={editor.conditions.length > 0}
            />
            {editor.conditionsStatus === 'loading' && (
              <Stack direction="vertical" gap="x2">
                {[1, 2, 3, 4, 5].map((i) => (
                  <Skeleton key={i} variant="text" width="100%" height={36} />
                ))}
              </Stack>
            )}
            {editor.conditionsStatus === 'error' && (
              <InlineAlert type="error">
                {editor.conditionsError ?? 'Ошибка загрузки условий'}
              </InlineAlert>
            )}
            {(editor.conditionsStatus === 'ready' || editor.conditionsStatus === 'empty') && (
              <ConditionsTable
                conditions={editor.conditions}
                rowStates={editor.rowStates}
                filter={filter}
                highlightRowIdx={highlightRowIdx}
                onHighlightConsumed={() => setHighlightRowIdx(null)}
                onUpdateField={(rowIdx, field, value) =>
                  void editor.updateConditionField(rowIdx, field, value)
                }
                onAddCondition={handleAddCondition}
                onRemoveCondition={(rowIdx) => void editor.removeCondition(rowIdx)}
                onDuplicateCondition={(rowIdx) => void editor.duplicateCondition(rowIdx)}
                onMoveCondition={(rowIdx, dir) => void editor.moveCondition(rowIdx, dir)}
              />
            )}

            {/* Chunk 2 collapsible panels (Validation + Statistics). */}
            <ValidationIssuesPanel
              open={overlays.val}
              sessionId={sessionId}
              dictName={selectedDictName}
              onJumpToCondition={handleJumpToCondition}
            />
            <StatisticsPanel
              open={overlays.stat}
              sessionId={sessionId}
              dictName={selectedDictName}
            />
          </Stack>
        </main>
      </div>

      {/* Mobile sidebar overlay backdrop */}
      {mobileTreeOpen && (
        <div
          className="dict-editor__backdrop"
          onClick={() => setMobileTreeOpen(false)}
          aria-hidden
        />
      )}

      {/* Chunk 2 overlays */}
      <AIAnalysisPanel
        open={overlays.ai}
        onClose={() => closeOverlay('ai')}
        sessionId={sessionId}
        dictName={selectedDictName}
      />
      <PhraseSuggestionsModal
        open={overlays.suggest}
        onClose={() => closeOverlay('suggest')}
        sessionId={sessionId}
        dictName={selectedDictName}
        onAddSuggestion={handleAddSuggestion}
      />
      <DuplicatesModal
        open={overlays.dup}
        onClose={() => closeOverlay('dup')}
        sessionId={sessionId}
        dictName={selectedDictName}
        onJumpToCondition={handleJumpToCondition}
      />
      <XmlExportDialog
        open={overlays.xml}
        onClose={() => closeOverlay('xml')}
        sessionId={sessionId}
        rootDictNames={rootDictNames}
        defaultDictName={selectedDictName}
      />

      {/* Track B — MiningPanel overlay (Variant C: Sidesheet) */}
      <Sidesheet
        isOpen={overlays.mining}
        onClose={() => closeOverlay('mining')}
        title="Mining"
        mode="modal"
        placement="right"
        size="large"
        hasOverlay
        className="dict-editor__mining-sidesheet"
        content={
          <MiningPanel
            sessionId={sessionId}
            dictionaryId={selectedDictName}
            tree={editorTree}
            onAddSuggestion={handleAddSuggestion}
          />
        }
      />
    </Box>
  );
}
