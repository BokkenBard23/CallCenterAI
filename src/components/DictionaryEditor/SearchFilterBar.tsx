/**
 * SearchFilterBar — search input + channel filter + clear button.
 * Sits above ConditionsTable. Owns its text input state locally and
 * propagates filter changes upward via a debounced onChange callback.
 *
 * The parent passes `value` only as the initial seed; subsequent
 * changes flow upward via onChange. The clear button resets local
 * state directly (no prop round-trip needed).
 */

import { memo, useEffect, useRef, useState } from 'react';
import { Badge, Button, Icon, Stack, TextField } from '@beeline/design-system-react';
import { Icons } from '@beeline/design-tokens/js/iconfont';
import { SimpleSelect, type SimpleOption } from './SimpleSelect';
import { EDITABLE_CHANNELS, CHANNEL_LABELS } from './constants';

export interface SearchFilterValue {
  text: string;
  channel: '' | 'ANY' | 'CLIENT' | 'OPERATOR';
}

export interface SearchFilterBarProps {
  /** Initial seed value (used only on mount). */
  initialValue?: SearchFilterValue;
  onChange: (next: SearchFilterValue) => void;
  /** Total matched rows after filter applied (for "no results" state). */
  matchedCount: number;
  /** Whether the underlying table has any rows at all (for empty vs filtered). */
  hasRows: boolean;
}

const CHANNEL_OPTIONS: SimpleOption[] = [
  { value: '', label: 'Все каналы' },
  ...EDITABLE_CHANNELS.map((c) => ({ value: c, label: CHANNEL_LABELS[c] })),
];

const DEBOUNCE_MS = 300;

function SearchFilterBarBase({
  initialValue,
  onChange,
  matchedCount,
  hasRows,
}: SearchFilterBarProps) {
  const [text, setText] = useState(initialValue?.text ?? '');
  const [channel, setChannel] = useState<SearchFilterValue['channel']>(
    initialValue?.channel ?? '',
  );
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const propagate = (next: SearchFilterValue) => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      onChange(next);
    }, DEBOUNCE_MS);
  };

  const handleTextChange = (next: string) => {
    setText(next);
    propagate({ text: next, channel });
  };

  const handleChannelChange = (next: SearchFilterValue['channel']) => {
    setChannel(next);
    // Channel change is immediate (no debounce) — it's a discrete selection.
    if (timerRef.current) clearTimeout(timerRef.current);
    onChange({ text, channel: next });
  };

  const handleClear = () => {
    setText('');
    setChannel('');
    if (timerRef.current) clearTimeout(timerRef.current);
    onChange({ text: '', channel: '' });
  };

  useEffect(
    () => () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    },
    [],
  );

  const filterActive = text.trim().length > 0 || channel !== '';
  const noResults = filterActive && hasRows && matchedCount === 0;

  return (
    <Stack direction="horizontal" gap="x3" align="center" wrap="wrap">
      <TextField
        placeholder="Поиск фразы…"
        value={text}
        onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
          handleTextChange(e.target.value)
        }
        fullWidth={false}
        style={{ minWidth: 240 }}
      />
      <div style={{ minWidth: 200 }}>
        <SimpleSelect
          options={CHANNEL_OPTIONS}
          value={channel}
          onChange={(v) =>
            handleChannelChange(v as SearchFilterValue['channel'])
          }
          placeholder="Все каналы"
        />
      </div>
      {filterActive && (
        <>
          <Badge type="secondary" semantic="info">
            Фильтр активен
          </Badge>
          <Button
            variant="outlined"
            size="small"
            startIcon={<Icon iconName={Icons.Close} />}
            onClick={handleClear}
          >
            Очистить
          </Button>
        </>
      )}
      {noResults && (
        <Badge type="secondary" semantic="warning">
          Ничего не найдено
        </Badge>
      )}
    </Stack>
  );
}

export const SearchFilterBar = memo(SearchFilterBarBase);
