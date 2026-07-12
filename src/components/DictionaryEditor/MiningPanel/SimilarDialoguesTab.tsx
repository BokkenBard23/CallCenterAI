/**
 * SimilarDialoguesTab — Tab 1: find similar dialogues to a PhraseGroup.
 *
 * Flow:
 *   1. PhraseGroupSelect (SimpleSelect pattern reuses DS Select) — picks a
 *      root/branch node from editor.tree to search against.
 *   2. "Найти похожие" Button → POST /mining/find_similar (synchronous).
 *   3. SimilarDialoguesList: DS Table dense + TanStack Table headless
 *      (ConditionsTable pattern). Columns: dialogue_id, snippet, score
 *      (numeric), channel (Tag/Badge), turn_count.
 *
 * Anti-clone: Pattern 2 (Data-Dense Dashboard) — composition inspiration only.
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
import { ChannelTag } from '../ChannelTag';
import { SimpleSelect, type SimpleOption } from '../SimpleSelect';
import type { DictionaryNode, SimilarDialogue } from '../../../types/api';

const DEFAULT_PAGE_SIZE = 10;
const PAGE_SIZE_OPTIONS = [10, 20, 50];

export interface SimilarDialoguesTabProps {
  /** Session id (route param). */
  sessionId: string;
  /** Completed indexing job_id (from useMiningState). */
  jobId: string | null;
  /** Editor tree — used to populate PhraseGroupSelect options. */
  tree: DictionaryNode[];
  /** True while find_similar request is in-flight. */
  loading: boolean;
  /** Error message from find_similar failure (null when ok). */
  error: string | null;
  /** Last fetched similar dialogue results. */
  results: SimilarDialogue[];
  /** Trigger find_similar API call (delegated to useMiningState). */
  onFindSimilar: (phraseGroupId: string, topK?: number) => void;
}

/** Flatten tree to phrase-group-like options (root/branch nodes). */
function flattenPhraseGroups(nodes: DictionaryNode[], prefix = ''): SimpleOption[] {
  const out: SimpleOption[] = [];
  for (const n of nodes) {
    const label = prefix ? `${prefix} / ${n.name}` : n.name;
    out.push({ value: n.id || n.name, label });
    if (n.children && n.children.length > 0) {
      out.push(...flattenPhraseGroups(n.children, label));
    }
  }
  return out;
}

const columns: ColumnDef<SimilarDialogue>[] = [
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
      return v.length > 80 ? `${v.slice(0, 80)}…` : v;
    },
  },
  {
    accessorKey: 'score',
    header: 'Score',
    cell: (info) => info.getValue<number>().toFixed(3),
  },
  {
    accessorKey: 'channel',
    header: 'Канал',
    cell: (info) => <ChannelTag channel={info.getValue<string>()} />,
  },
  {
    accessorKey: 'turn_count',
    header: 'Реплик',
    cell: (info) => info.getValue<number>(),
  },
];

function SimilarDialoguesTabBase({
  sessionId,
  jobId,
  tree,
  loading,
  error,
  results,
  onFindSimilar,
}: SimilarDialoguesTabProps) {
  const [selectedGroupId, setSelectedGroupId] = useState<string>('');
  const [sorting, setSorting] = useState<SortingState>([]);
  const [pagination, setPagination] = useState({
    pageIndex: 0,
    pageSize: DEFAULT_PAGE_SIZE,
  });

  const options = useMemo(() => flattenPhraseGroups(tree), [tree]);

  // eslint-disable-next-line react-hooks/incompatible-library -- TanStack Table v8 useReactTable returns non-memoizable API
  const table = useReactTable<SimilarDialogue>({
    data: results,
    columns,
    state: { sorting, pagination },
    onSortingChange: setSorting,
    onPaginationChange: setPagination,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
  });

  const handleFind = () => {
    if (!selectedGroupId || !jobId) return;
    onFindSimilar(selectedGroupId, 20);
  };

  const canSearch = Boolean(selectedGroupId && jobId && !loading);

  return (
    <Stack direction="vertical" gap="x3">
      <Stack direction="horizontal" gap="x2" align="center" wrap="wrap">
        <div style={{ minWidth: 220, flex: 1 }}>
          <SimpleSelect
            options={options}
            value={selectedGroupId}
            onChange={setSelectedGroupId}
            placeholder="Выберите PhraseGroup"
          />
        </div>
        <Button variant="primary" loading={loading} disabled={!canSearch} onClick={handleFind}>
          Найти похожие
        </Button>
      </Stack>

      {!jobId && (
        <Typography variant="body2" color="colorTextInactive">
          Сначала проиндексируйте корпус, чтобы искать похожие диалоги.
        </Typography>
      )}

      {error && (
        <InlineAlert type="error">{error}</InlineAlert>
      )}

      {loading && (
        <Stack direction="vertical" gap="x2">
          {[1, 2, 3, 4, 5].map((i) => (
            <Skeleton key={i} variant="text" width="100%" height={36} />
          ))}
        </Stack>
      )}

      {!loading && !error && results.length === 0 && jobId && (
        <Typography variant="body2" color="colorTextInactive">
          {selectedGroupId
            ? 'Нажмите «Найти похожие», чтобы получить top-k диалогов.'
            : 'Выберите PhraseGroup и нажмите «Найти похожие».'}
        </Typography>
      )}

      {!loading && !error && results.length > 0 && (
        <Stack direction="vertical" gap="x2">
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
            rowsCount={results.length}
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
      {/* sessionId is part of the public contract; consumption is delegated to
          useMiningState.findSimilar. Keep the prop validated by TS even though
          we don't call endpoints directly here. */}
      <span hidden aria-hidden data-testid="similar-tab-session" data-session={sessionId} />
    </Stack>
  );
}

export const SimilarDialoguesTab = memo(SimilarDialoguesTabBase);
