/**
 * PhraseSuggestionsModal — Modal with AI-generated phrase suggestions.
 *
 * DS Modal renders only `open` / `children`; this wrapper composes a Box +
 * Stack inside with:
 *   - header (Typography + close IconButton)
 *   - provider Select + "Подсказать" Button (POST /suggest-phrases, 180s timeout)
 *   - channel filter Select (optional)
 *   - suggestions List + ListItem (phrase + channel Badge + distance + add IconButton)
 *   - "Добавить все" Button (batch add visible suggestions)
 *   - added state: Badge success "Добавлено" + checkmark
 *
 * AbortController cancels fetch when modal closes.
 */

import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Badge,
  Box,
  Button,
  IconButton,
  InlineAlert,
  List,
  ListItem,
  Modal,
  Progress,
  Stack,
  Typography,
} from '@beeline/design-system-react';
import { Icons } from '@beeline/design-tokens/js/iconfont';
import { suggestDictionaryPhrases } from '../../api/client';
import type { DictionarySuggestion } from '../../types/api';
import { ChannelTag } from './ChannelTag';
import { SimpleSelect, type SimpleOption } from './SimpleSelect';
import { EDITABLE_CHANNELS, CHANNEL_LABELS } from './constants';

export interface PhraseSuggestionsModalProps {
  open: boolean;
  onClose: () => void;
  sessionId: string;
  dictName: string | null;
  /** Add a suggestion to conditions (POST /conditions handled by parent). */
  onAddSuggestion: (suggestion: DictionarySuggestion) => Promise<void> | void;
}

type Status = 'idle' | 'loading' | 'ready' | 'error';

const CHANNEL_FILTER_OPTIONS: SimpleOption[] = [
  { value: '', label: 'Все каналы' },
  ...EDITABLE_CHANNELS.map((c) => ({ value: c, label: CHANNEL_LABELS[c] })),
];

function PhraseSuggestionsModalBase({
  open,
  onClose,
  sessionId,
  dictName,
  onAddSuggestion,
}: PhraseSuggestionsModalProps) {
  const [status, setStatus] = useState<Status>('idle');
  const [suggestions, setSuggestions] = useState<DictionarySuggestion[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [addedKeys, setAddedKeys] = useState<Set<string>>(new Set());
  const [channelFilter, setChannelFilter] = useState<string>('');
  const [batchAdding, setBatchAdding] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const fetchSuggestions = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setStatus('loading');
    setError(null);
    setAddedKeys(new Set());
    try {
      const data = await suggestDictionaryPhrases(
        sessionId,
        { dict_name: dictName, count: 25 },
        controller.signal,
      );
      setSuggestions(data.suggestions ?? []);
      setStatus('ready');
    } catch (err) {
      if (controller.signal.aborted) return;
      setStatus('error');
      setError(
        err && typeof err === 'object' && 'message' in err
          ? String((err as { message: string }).message)
          : 'AI временно недоступен',
      );
    }
  }, [sessionId, dictName]);

  useEffect(() => {
    if (open && dictName) {
      // Auto-fetch on open — the user clicked "Подсказать фразы" expecting suggestions.
      // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on modal open; setState is async, not synchronous cascading.
      void fetchSuggestions();
    }
    return () => abortRef.current?.abort();
  }, [open, dictName, fetchSuggestions]);

  const filtered = useMemo(() => {
    if (!channelFilter) return suggestions;
    return suggestions.filter((s) => s.channel === channelFilter);
  }, [suggestions, channelFilter]);

  const sugKey = (s: DictionarySuggestion, i: number): string =>
    `${s.phrase}|${s.channel}|${i}`;

  const handleAdd = useCallback(
    async (s: DictionarySuggestion, key: string) => {
      try {
        await onAddSuggestion(s);
        setAddedKeys((prev) => new Set(prev).add(key));
      } catch {
        // Parent surfaces its own error; nothing to do here.
      }
    },
    [onAddSuggestion],
  );

  const handleAddAll = useCallback(async () => {
    setBatchAdding(true);
    try {
      for (const [i, s] of filtered.entries()) {
        const k = sugKey(s, i);
        if (!addedKeys.has(k)) {
          await handleAdd(s, k);
        }
      }
    } finally {
      setBatchAdding(false);
    }
  }, [filtered, addedKeys, handleAdd]);

  const remainingCount = filtered.filter(
    (s, i) => !addedKeys.has(sugKey(s, i)),
  ).length;

  return (
    <Modal open={open}>
      <Box
        style={{
          background: 'var(--color-background-base)',
          borderRadius: 'var(--size-border-radius-x4)',
          maxWidth: '600px',
          width: 'min(600px, 92vw)',
          maxHeight: '85vh',
          overflow: 'auto',
        }}
      >
        <Box style={{ padding: 'var(--size-spacing-x4)' }}>
          <Stack direction="vertical" gap="x3">
            <Stack direction="horizontal" gap="x2" align="center" justify="space-between">
              <Typography variant="h6">AI подсказки фраз</Typography>
              <IconButton
                iconName={Icons.Close}
                variant="plain"
                aria-label="Закрыть"
                onClick={onClose}
              />
            </Stack>

            {!dictName ? (
              <InlineAlert type="info">Выберите словарь.</InlineAlert>
            ) : status === 'loading' ? (
              <Stack direction="vertical" gap="x3" align="center">
                <Progress shape="circle" cycled />
                <Typography variant="body2" color="colorTextInactive">
                  Генерируем фразы…
                </Typography>
              </Stack>
            ) : status === 'error' ? (
              <Stack direction="vertical" gap="x3">
                <InlineAlert type="error">AI временно недоступен</InlineAlert>
                {error && (
                  <Typography variant="caption" color="colorTextInactive">
                    {error}
                  </Typography>
                )}
                <Button variant="outlined" size="small" onClick={() => void fetchSuggestions()}>
                  Повторить
                </Button>
              </Stack>
            ) : status === 'ready' ? (
              <Stack direction="vertical" gap="x3">
                <Stack direction="horizontal" gap="x2" align="center" wrap="wrap">
                  <div style={{ minWidth: 180 }}>
                    <SimpleSelect
                      options={CHANNEL_FILTER_OPTIONS}
                      value={channelFilter}
                      onChange={setChannelFilter}
                      placeholder="Все каналы"
                    />
                  </div>
                  <Button
                    variant="outlined"
                    size="small"
                    onClick={() => void fetchSuggestions()}
                  >
                    Обновить
                  </Button>
                </Stack>

                {filtered.length === 0 ? (
                  <InlineAlert type="info">
                    0 подсказок. Попробуйте другой словарь или провайдер.
                  </InlineAlert>
                ) : (
                  <>
                    <List>
                      {filtered.map((s, i) => {
                        const key = sugKey(s, i);
                        const added = addedKeys.has(key);
                        return (
                          <ListItem key={key}>
                            <Stack
                              direction="horizontal"
                              gap="x2"
                              align="center"
                              justify="space-between"
                              wrap="wrap"
                              style={{ width: '100%' }}
                            >
                              <Stack direction="vertical" gap="x1">
                                <Typography variant="body2">{s.phrase}</Typography>
                                <Stack direction="horizontal" gap="x2" align="center">
                                  <ChannelTag channel={s.channel} />
                                  <Typography variant="caption" color="colorTextInactive">
                                    WD: {s.distance}
                                  </Typography>
                                </Stack>
                              </Stack>
                              {added ? (
                                <Badge type="secondary" semantic="success" dot>
                                  Добавлено
                                </Badge>
                              ) : (
                                <IconButton
                                  iconName={Icons.Add}
                                  variant="plain"
                                  aria-label={`Добавить: ${s.phrase}`}
                                  disabled={batchAdding}
                                  onClick={() => void handleAdd(s, key)}
                                />
                              )}
                            </Stack>
                          </ListItem>
                        );
                      })}
                    </List>
                    <Button
                      variant="contained"
                      disabled={remainingCount === 0 || batchAdding}
                      onClick={() => void handleAddAll()}
                    >
                      {batchAdding
                        ? 'Добавляем…'
                        : `Добавить все (${remainingCount})`}
                    </Button>
                  </>
                )}
              </Stack>
            ) : null}
          </Stack>
        </Box>
      </Box>
    </Modal>
  );
}

export const PhraseSuggestionsModal = memo(PhraseSuggestionsModalBase);
