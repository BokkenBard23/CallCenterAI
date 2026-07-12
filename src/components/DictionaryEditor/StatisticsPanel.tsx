/**
 * StatisticsPanel — Card with aggregate statistics for the dictionary.
 *
 * Renders when visible (`open=true`): the parent (DictionaryEditorPage)
 * toggles visibility from the header "Статистика" button. Re-fetches on
 * first visibility. Refresh IconButton re-runs /statistics.
 *
 * Layout:
 *   - Card header: "Статистика" + refresh IconButton + collapse hint
 *   - 4 × Counter (total_conditions / total_words / unique_words / brackets_count)
 *   - channels_distribution: 3 × Badge (ANY neutral, OPERATOR violet, CLIENT success)
 *   - operators_count: 6 × Badge (one per canonical operator)
 *   - WordFrequencyBar (top-15, custom component, DS tokens)
 *
 * States: loading (Skeleton), ready, error (InlineAlert + retry).
 */

import { memo, useCallback, useEffect, useRef, useState } from 'react';
import {
  Badge,
  Box,
  Button,
  Card,
  IconButton,
  InlineAlert,
  Skeleton,
  Stack,
  Typography,
} from '@beeline/design-system-react';
import { Icons } from '@beeline/design-tokens/js/iconfont';
import { getDictionaryStatistics } from '../../api/client';
import type { DictionaryStats } from '../../types/api';
import { WordFrequencyBar } from './WordFrequencyBar';

export interface StatisticsPanelProps {
  open: boolean;
  sessionId: string;
  dictName: string | null;
}

type Status = 'idle' | 'loading' | 'ready' | 'error';

const CHANNEL_LABEL: Record<string, string> = {
  ANY: 'ANY',
  OPERATOR: 'OPERATOR',
  CLIENT: 'CLIENT',
};

const OPERATOR_LABEL: Record<string, string> = {
  '': '—',
  'И': 'И',
  'ИЛИ': 'ИЛИ',
  'НЕ': 'НЕ',
  'И НЕ': 'И НЕ',
  'ИЛИ НЕ': 'ИЛИ НЕ',
};

function StatisticsPanelBase({ open, sessionId, dictName }: StatisticsPanelProps) {
  const [status, setStatus] = useState<Status>('idle');
  const [stats, setStats] = useState<DictionaryStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const fetchStats = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setStatus('loading');
    setError(null);
    try {
      const data = await getDictionaryStatistics(
        sessionId,
        { dict_name: dictName },
        controller.signal,
      );
      setStats(data);
      setStatus('ready');
    } catch (err) {
      if (controller.signal.aborted) return;
      setStatus('error');
      setError(
        err && typeof err === 'object' && 'message' in err
          ? String((err as { message: string }).message)
          : 'Ошибка загрузки статистики',
      );
    }
  }, [sessionId, dictName]);

  // Fetch when panel opens for the first time, or when dictName changes while open.
  useEffect(() => {
    if (open && dictName) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on panel open; setState is async, not synchronous cascading.
      void fetchStats();
    }
    return () => abortRef.current?.abort();
  }, [open, dictName, fetchStats]);

  if (!open) return null;

  return (
    <Card>
      <Box style={{ padding: 'var(--size-spacing-x4)' }}>
        <Stack direction="vertical" gap="x3">
          <Stack direction="horizontal" gap="x2" align="center" justify="space-between">
            <Typography variant="h6">Статистика</Typography>
            <Stack direction="horizontal" gap="x2" align="center">
              <IconButton
                iconName={Icons.Refresh}
                variant="plain"
                aria-label="Обновить статистику"
                disabled={status === 'loading' || !dictName}
                onClick={() => void fetchStats()}
              />
              <Badge type="secondary" semantic="info">
                {dictName ?? '—'}
              </Badge>
            </Stack>
          </Stack>

          {!dictName ? (
            <InlineAlert type="info">Выберите словарь для статистики.</InlineAlert>
          ) : status === 'loading' ? (
            <Stack direction="vertical" gap="x2">
              {[1, 2, 3, 4].map((i) => (
                <Skeleton key={i} variant="text" width="100%" height={32} />
              ))}
            </Stack>
          ) : status === 'error' ? (
            <Stack direction="vertical" gap="x3">
              <InlineAlert type="error">Ошибка загрузки статистики</InlineAlert>
              {error && (
                <Typography variant="caption" color="colorTextInactive">
                  {error}
                </Typography>
              )}
              <Button variant="outlined" size="small" onClick={() => void fetchStats()}>
                Повторить
              </Button>
            </Stack>
          ) : stats ? (
            <Stack direction="vertical" gap="x3">
              <Stack direction="horizontal" gap="x4" wrap="wrap">
                <Stack direction="vertical" gap="x1" align="center">
                  <Typography variant="caption" color="colorTextInactive">
                    Условий
                  </Typography>
                  <Typography variant="h6">{stats.total_conditions}</Typography>
                </Stack>
                <Stack direction="vertical" gap="x1" align="center">
                  <Typography variant="caption" color="colorTextInactive">
                    Слов всего
                  </Typography>
                  <Typography variant="h6">{stats.total_words}</Typography>
                </Stack>
                <Stack direction="vertical" gap="x1" align="center">
                  <Typography variant="caption" color="colorTextInactive">
                    Уникальных слов
                  </Typography>
                  <Typography variant="h6">{stats.unique_words}</Typography>
                </Stack>
                <Stack direction="vertical" gap="x1" align="center">
                  <Typography variant="caption" color="colorTextInactive">
                    Скобок
                  </Typography>
                  <Typography variant="h6">{stats.brackets_count}</Typography>
                </Stack>
              </Stack>

              <Stack direction="vertical" gap="x1">
                <Typography variant="body2" color="colorTextInactive">
                  Каналы
                </Typography>
                <Stack direction="horizontal" gap="x2" wrap="wrap">
                  {(['ANY', 'OPERATOR', 'CLIENT'] as const).map((ch) => (
                    <Badge
                      key={ch}
                      type="secondary"
                      semantic={
                        ch === 'ANY'
                          ? 'neutral'
                          : ch === 'OPERATOR'
                            ? 'violet'
                            : 'success'
                      }
                    >
                      {CHANNEL_LABEL[ch]}: {String(stats.channels_distribution?.[ch] ?? 0)}
                    </Badge>
                  ))}
                </Stack>
              </Stack>

              <Stack direction="vertical" gap="x1">
                <Typography variant="body2" color="colorTextInactive">
                  Операторы
                </Typography>
                <Stack direction="horizontal" gap="x2" wrap="wrap">
                  {Object.keys(OPERATOR_LABEL).map((op) => (
                    <Badge key={op || 'empty'} type="secondary" semantic="neutral">
                      {OPERATOR_LABEL[op]}: {String(stats.operators_count?.[op] ?? 0)}
                    </Badge>
                  ))}
                </Stack>
              </Stack>

              <Stack direction="vertical" gap="x1">
                <Typography variant="body2" color="colorTextInactive">
                  Топ-15 слов по частоте
                </Typography>
                <WordFrequencyBar data={(stats as DictionaryStats & { word_frequency?: { word: string; count: number }[] }).word_frequency ?? []} />
              </Stack>
            </Stack>
          ) : null}
        </Stack>
      </Box>
    </Card>
  );
}

export const StatisticsPanel = memo(StatisticsPanelBase);
