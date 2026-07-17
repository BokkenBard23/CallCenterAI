/**
 * ConditionsTable — main editing surface.
 *
 * TanStack Table v8 (headless) manages sorting/pagination state;
 * DS Table primitives (Table/TableRow/TableCell/TableHead/...) render rows.
 * Each editable cell delegates to a DS component:
 *   - Phrase    → InlineEdit
 *   - Channel   → SimpleSelect + ChannelTag display
 *   - Distance  → Slider
 *   - Logic     → SimpleSelect
 *   - Brackets  → SimpleSelect × 2 (open/close)
 *   - is_exact  → Checkbox
 *   - Actions   → ConditionRowActions
 *
 * Backend contract: PATCH /conditions/{idx} accepts logic_operator /
 * open_brackets / close_brackets but does NOT persist them per-row —
 * they are encoded in token_section on XML serialization. The FE keeps
 * them in EditorCondition local state.
 */

import { memo, useEffect, useMemo, useState } from 'react';
import {
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type PaginationState,
  type SortingState,
} from '@tanstack/react-table';
import {
  Box,
  Button,
  Checkbox,
  Icon,
  InlineAlert,
  InlineEdit,
  Progress,
  Slider,
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

import { ChannelTag } from './ChannelTag';
import { ConditionRowActions } from './ConditionRowActions';
import { SimpleSelect } from './SimpleSelect';
import type { SearchFilterValue } from './SearchFilterBar';
import type { EditorCondition } from './types';
import {
  BRACKET_OPTIONS,
  CHANNEL_LABELS,
  DEFAULT_PAGE_SIZE,
  DISTANCE_MAX,
  DISTANCE_MIN,
  DISTANCE_STEP,
  EDITABLE_CHANNELS,
  LOGIC_OPERATORS,
  PAGE_SIZE_OPTIONS,
} from './constants';

export interface ConditionsTableProps {
  conditions: EditorCondition[];
  rowStates: Record<number, { status: 'idle' | 'saving' | 'error'; error?: string }>;
  filter: SearchFilterValue;
  /**
   * Chunk 2 (jump-to-condition): when set, the table scrolls the row at this
   * index into view and briefly highlights it. Parent resets it via
   * `onHighlightConsumed` after the highlight is applied.
   */
  highlightRowIdx?: number | null;
  /** Called after the highlight animation has been triggered. */
  onHighlightConsumed?: () => void;
  onUpdateField: <K extends keyof EditorCondition>(
    rowIdx: number,
    field: K,
    value: EditorCondition[K],
  ) => void;
  onAddCondition: (afterIdx?: number) => void;
  onRemoveCondition: (rowIdx: number) => void;
  onDuplicateCondition: (rowIdx: number) => void;
  onMoveCondition: (rowIdx: number, direction: 'up' | 'down') => void;
}

const LOGIC_OPTS = LOGIC_OPERATORS.map((o) => ({ value: o.value, label: o.label }));
const CHANNEL_OPTS = EDITABLE_CHANNELS.map((c) => ({ value: c, label: CHANNEL_LABELS[c] }));
const BRACKET_OPTS = BRACKET_OPTIONS.map((n) => ({ value: String(n), label: String(n) }));

/**
 * DistanceSliderCell — DS Slider has a self-triggering onChange loop
 * (`value` prop → setLocalValue → dispatchEvent('value_change') → onChange →
 * parent setState → `value` prop changes → loop → "Maximum update depth exceeded").
 *
 * Fix (D-1): pass NO `onChange` to DS Slider (so the internal `onChange?.()`
 * listener becomes a no-op), and commit the value on release/blur via native
 * input event handlers that DS Slider forwards through `...props` to the
 * inner `<input type="range">`. The visible label still tracks `localValue`
 * during drag (DS internal), but the PATCH fires once on commit.
 *
 * Verified against `node_modules/@beeline/design-system-react/build/components/Slider/Slider.js`:
 * `onChange` is destructured out of props and only invoked from the
 * 'value_change' event listener; `onMouseUp`/`onTouchEnd`/`onKeyUp`/`onBlur`
 * pass through `...props` to the inner input element.
 */
function DistanceSliderCell({
  value,
  disabled,
  onCommit,
}: {
  value: number;
  disabled?: boolean;
  onCommit: (n: number) => void;
}) {
  const commit = (target: EventTarget | null) => {
    if (!(target instanceof HTMLInputElement)) return;
    const n = Number(target.value);
    if (!Number.isNaN(n) && n !== value) onCommit(n);
  };

  return (
    <Slider
      min={DISTANCE_MIN}
      max={DISTANCE_MAX}
      step={DISTANCE_STEP}
      value={value}
      showLabel
      disabled={disabled}
      onMouseUp={(e: React.MouseEvent<HTMLInputElement>) => commit(e.currentTarget)}
      onTouchEnd={(e: React.TouchEvent<HTMLInputElement>) => commit(e.currentTarget)}
      onKeyUp={(e: React.KeyboardEvent<HTMLInputElement>) => commit(e.currentTarget)}
      onBlur={(e: React.FocusEvent<HTMLInputElement>) => commit(e.currentTarget)}
    />
  );
}

/**
 * PhraseInlineEdit — DS InlineEdit requires a forwardRef trigger child
 * (or `controlRef`). The previous ConditionsTable passed only `value` /
 * `onSubmit` / `onCancel` and relied on the InlineEdit rendering nothing —
 * which was masked by the (incorrect) TableCell usage that ignored children.
 * After C-1 fix (TableCell → TableData) the InlineEdit validation surfaced.
 * This wrapper passes a forwardRef Button as the trigger and manages `open`
 * state locally so clicking the button opens the DS edit modal.
 */
function PhraseInlineEdit({
  value,
  onSubmit,
  disabled,
}: {
  value: string;
  onSubmit: (v: string) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  return (
    <InlineEdit
      open={open}
      value={value}
      disabled={disabled}
      onCancel={() => setOpen(false)}
      onSubmit={(v) => {
        setOpen(false);
        if (typeof v === 'string' && v.trim().length > 0) onSubmit(v.trim());
      }}
    >
      <Button
        variant="plain"
        size="small"
        disabled={disabled}
        onClick={() => setOpen(true)}
        aria-label="Редактировать фразу"
      >
        {value}
      </Button>
    </InlineEdit>
  );
}

function ConditionsTableBase({
  conditions,
  rowStates,
  filter,
  highlightRowIdx,
  onHighlightConsumed,
  onUpdateField,
  onAddCondition,
  onRemoveCondition,
  onDuplicateCondition,
  onMoveCondition,
}: ConditionsTableProps) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [pagination, setPagination] = useState<PaginationState>({
    pageIndex: 0,
    pageSize: DEFAULT_PAGE_SIZE,
  });

  // Chunk 2 jump-to-condition: scroll target row into view + brief highlight.
  useEffect(() => {
    if (highlightRowIdx == null) return;
    if (highlightRowIdx < 0 || highlightRowIdx >= conditions.length) {
      onHighlightConsumed?.();
      return;
    }
    const el = document.querySelector<HTMLElement>(
      `[data-row-idx="${highlightRowIdx}"]`,
    );
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    onHighlightConsumed?.();
  }, [highlightRowIdx, conditions.length, onHighlightConsumed]);

  // Pre-filter conditions by search text + channel (client-side, LexiCore pattern).
  const filteredData = useMemo(() => {
    const q = filter.text.trim().toLowerCase();
    const ch = filter.channel;
    if (!q && !ch) return conditions;
    return conditions.filter((c) => {
      const textMatch = !q || c.text.toLowerCase().includes(q);
      const channelMatch = !ch || c.channel_constraint === ch;
      return textMatch && channelMatch;
    });
  }, [conditions, filter]);

  const columns = useMemo<ColumnDef<EditorCondition>[]>(
    () => [
      {
        id: 'index',
        header: '#',
        size: 48,
        enableSorting: false,
        cell: ({ row }) => <Typography variant="caption">{row.index + 1}</Typography>,
      },
      {
        id: 'logic_operator',
        header: 'Logic',
        size: 110,
        cell: ({ row }) => (
          <SimpleSelect
            options={LOGIC_OPTS}
            value={row.original.logic_operator}
            onChange={(v) => onUpdateField(row.index, 'logic_operator', v)}
            disabled={rowStates[row.index]?.status === 'saving'}
          />
        ),
      },
      {
        accessorKey: 'text',
        id: 'text',
        header: 'Phrase',
        size: 280,
        cell: ({ row }) => {
          const cond = row.original;
          const display = cond.is_exact ? `"${cond.text}"` : cond.text;
          return (
            <PhraseInlineEdit
              value={display}
              onSubmit={(v) => onUpdateField(row.index, 'text', v)}
              disabled={rowStates[row.index]?.status === 'saving'}
            />
          );
        },
      },
      {
        id: 'channel',
        header: 'Channel',
        size: 180,
        cell: ({ row }) => (
          <Stack direction="horizontal" gap="x2" align="center">
            <div style={{ minWidth: 140 }}>
              <SimpleSelect
                options={CHANNEL_OPTS}
                value={row.original.channel_constraint}
                onChange={(v) =>
                  onUpdateField(row.index, 'channel_constraint', v)
                }
                disabled={rowStates[row.index]?.status === 'saving'}
              />
            </div>
            <ChannelTag channel={row.original.channel_constraint} />
          </Stack>
        ),
      },
      {
        accessorKey: 'word_distance',
        id: 'word_distance',
        header: 'WD',
        size: 160,
        cell: ({ row }) => (
          <DistanceSliderCell
            value={row.original.word_distance}
            disabled={rowStates[row.index]?.status === 'saving'}
            onCommit={(n) => onUpdateField(row.index, 'word_distance', n)}
          />
        ),
      },
      {
        id: 'brackets',
        header: 'Brackets',
        size: 140,
        cell: ({ row }) => {
          const cond = row.original;
          const disabled = rowStates[row.index]?.status === 'saving';
          return (
            <Stack direction="horizontal" gap="x1" align="center">
              <div style={{ width: 56 }}>
                <SimpleSelect
                  options={BRACKET_OPTS}
                  value={String(cond.open_brackets)}
                  onChange={(v) =>
                    onUpdateField(row.index, 'open_brackets', Number(v))
                  }
                  disabled={disabled}
                  placeholder="("
                />
              </div>
              <div style={{ width: 56 }}>
                <SimpleSelect
                  options={BRACKET_OPTS}
                  value={String(cond.close_brackets)}
                  onChange={(v) =>
                    onUpdateField(row.index, 'close_brackets', Number(v))
                  }
                  disabled={disabled}
                  placeholder=")"
                />
              </div>
            </Stack>
          );
        },
      },
      {
        id: 'is_exact',
        header: 'Exact',
        size: 64,
        enableSorting: false,
        cell: ({ row }) => (
          <Checkbox
            checked={row.original.is_exact}
            onChange={() =>
              onUpdateField(row.index, 'is_exact', !row.original.is_exact)
            }
            disabled={rowStates[row.index]?.status === 'saving'}
            aria-label="Точное совпадение"
          />
        ),
      },
      {
        id: 'actions',
        header: '⋯',
        size: 56,
        enableSorting: false,
        cell: ({ row }) => {
          const rs = rowStates[row.index];
          if (rs?.status === 'saving') {
            return <Progress shape="circle" size="mini" cycled />;
          }
          return (
            <ConditionRowActions
              rowIdx={row.index}
              isFirst={row.index === 0}
              isLast={row.index === filteredData.length - 1}
              onAddAbove={() => onAddCondition(row.index - 1)}
              onAddBelow={() => onAddCondition(row.index)}
              onRemove={() => onRemoveCondition(row.index)}
              onMoveUp={() => onMoveCondition(row.index, 'up')}
              onMoveDown={() => onMoveCondition(row.index, 'down')}
              onDuplicate={() => onDuplicateCondition(row.index)}
            />
          );
        },
      },
    ],
    [filteredData.length, onAddCondition, onDuplicateCondition, onMoveCondition, onRemoveCondition, onUpdateField, rowStates],
  );

  // eslint-disable-next-line react-hooks/incompatible-library -- TanStack Table v8 useReactTable returns stable function refs; React Compiler skips memoization by design.
  const table = useReactTable({
    data: filteredData,
    columns,
    state: { sorting, pagination },
    onSortingChange: setSorting,
    onPaginationChange: setPagination,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  });

  // Empty state — no conditions at all (not "filtered to 0", but truly empty).
  if (conditions.length === 0) {
    return (
      <Box padding="x6">
        <Stack direction="vertical" gap="x3" align="center">
          <Typography variant="body1" color="colorTextInactive">
            Нет условий. Добавьте первое условие для этого словаря.
          </Typography>
          <Button
            variant="contained"
            startIcon={<Icon iconName={Icons.Add} />}
            onClick={() => onAddCondition()}
          >
            Добавить условие
          </Button>
        </Stack>
      </Box>
    );
  }

  const rows = table.getRowModel().rows;

  return (
    <Stack direction="vertical" gap="x3">
      <Table dense hover scroll={{ x: 'max-content' }}>
        <TableHead>
          <TableRow>
            {table.getHeaderGroups().flatMap((hg) =>
              hg.headers.map((header) => (
                <TableHeaderData
                  key={header.id}
                  onClick={header.column.getToggleSortingHandler()}
                  style={{
                    cursor: header.column.getCanSort() ? 'pointer' : 'default',
                  }}
                >
                  {flexRender(header.column.columnDef.header, header.getContext())}
                  {header.column.getIsSorted() ? (
                    <span style={{ marginLeft: 4 }}>
                      {header.column.getIsSorted() === 'asc' ? '▲' : '▼'}
                    </span>
                  ) : null}
                </TableHeaderData>
              )),
            )}
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.length === 0 ? (
            <TableRow>
              <td colSpan={columns.length} style={{ padding: 16 }}>
                <InlineAlert type="info">
                  Ничего не найдено по фильтру. Очистите фильтр или измените запрос.
                </InlineAlert>
              </td>
            </TableRow>
          ) : (
            rows.map((row) => {
              const rs = rowStates[row.index];
              return (
                <TableRow
                  key={row.id}
                  selected={rs?.status === 'saving'}
                  data-row-idx={row.index}
                  style={
                    highlightRowIdx === row.index
                      ? { background: 'var(--color-background-active)' }
                      : undefined
                  }
                >
                  {row.getVisibleCells().map((cell) => (
                    <TableData
                      key={cell.id}
                      style={{ verticalAlign: 'middle' }}
                    >
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableData>
                  ))}
                </TableRow>
              );
            })
          )}
        </TableBody>
      </Table>

      {rows.some((r) => rowStates[r.index]?.status === 'error') && (
        <InlineAlert type="error">
          Ошибка сохранения одной или нескольких строк. Изменения откатаны. Повторите попытку.
        </InlineAlert>
      )}

      <Stack direction="horizontal" gap="x3" align="center" justify="space-between">
        <Button
          variant="contained"
          startIcon={<Icon iconName={Icons.Add} />}
          onClick={() => onAddCondition()}
        >
          Добавить условие
        </Button>
        <TablePagination
          rowsCount={filteredData.length}
          rowsPerPage={pagination.pageSize}
          // JK5 FIX: DS TablePagination treats `page` as 1-based
          // (default=1, formula `page * rowsPerPage - rowsPerPage + 1`).
          // Previously we passed `pagination.pageIndex` (0-based), which
          // produced negative range text like "-9-0 из 1".
          page={pagination.pageIndex + 1}
          rowsPerPageOptions={[...PAGE_SIZE_OPTIONS]}
          onUserActions={(event) => {
            if (event.rowsPerPage !== pagination.pageSize) {
              // Rows-per-page change — reset to first page.
              setPagination((p) => ({
                ...p,
                pageSize: event.rowsPerPage,
                pageIndex: 0,
              }));
            } else if (event.page - 1 !== pagination.pageIndex) {
              // Page change — DS emits 1-based page, TanStack wants 0-based.
              setPagination((p) => ({ ...p, pageIndex: event.page - 1 }));
            }
          }}
        />
      </Stack>
    </Stack>
  );
}

// Keep the unused ReactNode import honest (used implicitly via JSX return types).

export const ConditionsTable = memo(ConditionsTableBase);
