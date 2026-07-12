/**
 * FalseNegativesTab — Tab 2: false-negative candidates with LLM confidence.
 *
 * Flow:
 *   1. "Найти пропущенные" Button → POST /mining/find_fn (returns job_id; poll).
 *   2. Partial state (LLM rate limited) → InlineAlert warning "LLM rate limited,
 *      показано N из M" + render available results.
 *   3. FNList: DS Table dense + TanStack Table headless (PhraseSuggestionsModal
 *      click-to-add pattern).
 *      Columns: dialogue_id, snippet, score, llm_label (ConfidenceBadge +
 *      Tooltip reason), proposed_phrase, action (click-to-add Button ghost).
 *
 * Click-to-add: reuses parent `onAddSuggestion` (DictionarySuggestion shape)
 * with channel='ANY', distance=2 (per spec handoff).
 *
 * RAC-2 (MultiSlider for confidence range filter) — optional, deferred to
 * Phase C polish. Badge + numeric score is sufficient for Quick Win.
 */

import { memo, useMemo, useState } from 'react';
import {
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from '@tanstack/react-table';
import {
  Box,
  Button,
  Counter,
  Icon,
  InlineAlert,
  Skeleton,
  Stack,
  Table,
  TableBody,
  TableData,
  TableHead,
  TableHeaderData,
  TablePagination,
  TableRow,
  Typography,
} from '@beeline/design-system-react';
import { Icons } from '@beeline/design-tokens/js/iconfont';
import { ConfidenceBadge } from './ConfidenceBadge';
import type { DictionarySuggestion, FNCandidate } from '../../../types/api';

const DEFAULT_PAGE_SIZE = 10;
const PAGE_SIZE_OPTIONS = [10, 20, 50];

export interface FalseNegativesTabProps {
  /** Completed indexing job_id (from useMiningState). */
  jobId: string | null;
  /** True while find_fn request is in-flight. */
  loading: boolean;
  /** Error message from find_fn failure (null when ok). */
  error: string | null;
  /** Last fetched FN candidates. */
  candidates: FNCandidate[];
  /** True when status=partial (LLM rate limited) — show warning. */
  partial: boolean;
  /** Optional total — when partial, expected total exceeds candidates.length. */
  expectedTotal?: number;
  /** Click-to-add handler — delegates to DictionaryEditorPage.handleAddSuggestion. */
  onAddSuggestion: (suggestion: DictionarySuggestion) => Promise<void> | void;
  /** Trigger find_fn API call (delegated to useMiningState). */
  onFindFN: () => void;
  /** True when a cancel request is in-flight. */
  cancelling?: boolean;
  /** Cancel the running find_fn job. */
  onCancel?: () => void;
}

function SimilarFNTabBase({
  jobId,
  loading,
  error,
  candidates,
  partial,
  expectedTotal,
  onAddSuggestion,
  onFindFN,
  cancelling = false,
  onCancel,
}: FalseNegativesTabProps) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [pagination, setPagination] = useState({
    pageIndex: 0,
    pageSize: DEFAULT_PAGE_SIZE,
  });
  const [added, setAdded] = useState<Set<string>>(new Set());

  const relevantCount = useMemo(
    () => candidates.filter((c) => c.llm_label === 'relevant').length,
    [candidates],
  );
  const uncertainCount = useMemo(
    () => candidates.filter((c) => c.llm_label === 'uncertain').length,
    [candidates],
  );

  const columns = useMemo<ColumnDef<FNCandidate>[]>(
    () => [
      {
        accessorKey: 'dialogue_id',
        header: 'ID',
        cell: (info) => info.getValue<string>(),
      },
      {
        accessorKey: 'snippet',
        header: 'Фрагмент',
        cell: (info) => {
          const v = info.getValue<string>();
          return v.length > 60 ? `${v.slice(0, 60)}…` : v;
        },
      },
      {
        accessorKey: 'score',
        header: 'Score',
        cell: (info) => info.getValue<number>().toFixed(3),
      },
      {
        accessorKey: 'llm_label',
        header: 'Confidence',
        cell: (info) => {
          const row = info.row.original;
          return (
            <ConfidenceBadge
              label={row.llm_label}
              score={row.llm_score}
              reason={row.llm_reason}
            />
          );
        },
      },
      {
        accessorKey: 'proposed_phrase',
        header: 'Предлагаемая фраза',
        cell: (info) => {
          const v = info.getValue<string | null>();
          return v ?? '—';
        },
      },
      {
        id: 'action',
        header: '',
        cell: (info) => {
          const row = info.row.original;
          const isAdded = added.has(row.dialogue_id);
          const disabled = !row.proposed_phrase || isAdded;
          return (
            <Button
              variant="ghost"
              size="small"
              startIcon={isAdded ? <Icon iconName={Icons.Check} /> : <Icon iconName={Icons.Add} />}
              disabled={disabled}
              onClick={() => {
                if (!row.proposed_phrase) return;
                void onAddSuggestion({
                  phrase: row.proposed_phrase,
                  channel: 'ANY',
                  distance: 2,
                });
                setAdded((prev) => new Set(prev).add(row.dialogue_id));
              }}
            >
              {isAdded ? 'Добавлено' : 'Добавить'}
            </Button>
          );
        },
      },
    ],
    [added, onAddSuggestion],
  );

  // eslint-disable-next-line react-hooks/incompatible-library -- TanStack Table v8 useReactTable returns non-memoizable API
  const table = useReactTable<FNCandidate>({
    data: candidates,
    columns,
    state: { sorting, pagination },
    onSortingChange: setSorting,
    onPaginationChange: setPagination,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
  });

  return (
    <Stack direction="vertical" gap="x3">
      <Stack direction="horizontal" gap="x2" align="center" wrap="wrap">
        <Button
          variant="primary"
          loading={loading}
          disabled={!jobId || loading}
          onClick={onFindFN}
        >
          Найти пропущенные
        </Button>
        {loading && onCancel && (
          <Button
            variant="ghost"
            size="small"
            disabled={cancelling}
            loading={cancelling}
            onClick={onCancel}
          >
            Отменить
          </Button>
        )}
      </Stack>

      {!jobId && (
        <Typography variant="body2" color="colorTextInactive">
          Сначала проиндексируйте корпус, чтобы искать false negatives.
        </Typography>
      )}

      {partial && (
        <InlineAlert type="warning">
          {expectedTotal !== undefined
            ? `LLM rate limited: показано ${candidates.length} из ${expectedTotal} результатов.`
            : `LLM rate limited: показаны частичные результаты (${candidates.length}).`}
        </InlineAlert>
      )}

      {error && <InlineAlert type="error">{error}</InlineAlert>}

      {loading && (
        <Stack direction="vertical" gap="x2">
          {[1, 2, 3, 4, 5].map((i) => (
            <Skeleton key={i} variant="text" width="100%" height={36} />
          ))}
        </Stack>
      )}

      {!loading && !error && candidates.length === 0 && jobId && (
        <Typography variant="body2" color="colorTextInactive">
          Нажмите «Найти пропущенные», чтобы получить FN-кандидатов.
        </Typography>
      )}

      {!loading && !error && candidates.length > 0 && (
        <Stack direction="vertical" gap="x2">
          {/* Pattern 1 inspiration: aggregate KPIs (ChannelTag semantic not needed). */}
          <Stack direction="horizontal" gap="x3" align="center">
            <Counter count={candidates.length} tooltipTitle="Total FN candidates" size="medium" />
            <Counter count={relevantCount} tooltipTitle="relevant" size="medium" />
            <Counter count={uncertainCount} tooltipTitle="uncertain" size="medium" />
          </Stack>

          <Box style={{ maxHeight: '420px', overflow: 'auto' }}>
            <Table dense hover>
              <TableHead>
                <TableRow>
                  {table.getHeaderGroups()[0]?.headers.map((h) => (
                    <TableHeaderData
                      key={h.id}
                      onClick={h.column.getToggleSortingHandler()}
                    >
                      {flexRender(h.column.columnDef.header, h.getContext())}
                    </TableHeaderData>
                  ))}
                </TableRow>
              </TableHead>
              <TableBody>
                {table.getRowModel().rows.map((row) => (
                  <TableRow key={row.id}>
                    {row.getVisibleCells().map((cell) => (
                      <TableData key={cell.id}>
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </TableData>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Box>
          <TablePagination
            rowsCount={candidates.length}
            rowsPerPage={pagination.pageSize}
            page={pagination.pageIndex}
            rowsPerPageOptions={PAGE_SIZE_OPTIONS}
            onUserActions={(event) => {
              if (event.rowsPerPage !== pagination.pageSize) {
                setPagination((p) => ({ ...p, pageSize: event.rowsPerPage, pageIndex: 0 }));
              } else if (event.page !== pagination.pageIndex) {
                setPagination((p) => ({ ...p, pageIndex: event.page }));
              }
            }}
          />
        </Stack>
      )}
    </Stack>
  );
}

// Helper alias to keep the public component name readable.
export const FalseNegativesTab = memo(SimilarFNTabBase);