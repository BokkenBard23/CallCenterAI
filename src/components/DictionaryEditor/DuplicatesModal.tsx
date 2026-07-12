/**
 * DuplicatesModal — Modal with full/soft duplicate groups + jump-to-condition.
 *
 * DS Modal renders only `open` / `children`; this wrapper composes a Box +
 * Stack inside with a header (Typography + close IconButton), Tabs for full/soft
 * groups, and per-DupPair ListItem with a "Перейти" Button that calls
 * `onJumpToCondition(rowA)` to highlight + scroll the ConditionsTable.
 *
 * Re-check Button re-runs /duplicates after edits.
 *
 * States: loading (Progress), ready (lists), empty (InlineAlert success),
 * error (InlineAlert + retry).
 */

import { memo, useCallback, useEffect, useRef, useState } from 'react';
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
  Tab,
  Tabs,
  Typography,
} from '@beeline/design-system-react';
import { Icons } from '@beeline/design-tokens/js/iconfont';
import { findDictionaryDuplicates } from '../../api/client';
import type { DuplicateReport, DupPair } from '../../types/api';

export interface DuplicatesModalProps {
  open: boolean;
  onClose: () => void;
  sessionId: string;
  dictName: string | null;
  /** Called when user clicks a DupPair row to highlight+scroll the ConditionsTable. */
  onJumpToCondition: (rowIdx: number) => void;
}

type Status = 'idle' | 'loading' | 'ready' | 'error';

function DuplicatesModalBase({
  open,
  onClose,
  sessionId,
  dictName,
  onJumpToCondition,
}: DuplicatesModalProps) {
  const [status, setStatus] = useState<Status>('idle');
  const [report, setReport] = useState<DuplicateReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tabIndex, setTabIndex] = useState(0);
  const abortRef = useRef<AbortController | null>(null);

  const fetchDuplicates = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setStatus('loading');
    setError(null);
    try {
      const data = await findDictionaryDuplicates(
        sessionId,
        { dict_name: dictName },
        controller.signal,
      );
      setReport(data);
      setStatus('ready');
    } catch (err) {
      if (controller.signal.aborted) return;
      setStatus('error');
      setError(
        err && typeof err === 'object' && 'message' in err
          ? String((err as { message: string }).message)
          : 'Ошибка поиска дубликатов',
      );
    }
  }, [sessionId, dictName]);

  useEffect(() => {
    if (open && dictName) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- reset tab + fetch on dialog open; intentional one-time sync.
      setTabIndex(0);
      void fetchDuplicates();
    }
    return () => abortRef.current?.abort();
  }, [open, dictName, fetchDuplicates]);

  const renderDupPair = (pair: DupPair, keyPrefix: string) => {
    const isExact = pair.is_exact_a || pair.is_exact_b;
    return (
      <ListItem
        key={`${keyPrefix}-${pair.row_a}-${pair.row_b}-${pair.phrase.slice(0, 12)}`}
      >
        <Stack
          direction="horizontal"
          gap="x2"
          align="center"
          justify="space-between"
          wrap="wrap"
          style={{ width: '100%' }}
        >
          <Stack direction="vertical" gap="x1">
            <Typography variant="body2">
              Строка #{pair.row_a + 1} ↔ #{pair.row_b + 1}
            </Typography>
            <Typography variant="body2" color="colorTextInactive">
              {pair.phrase}
            </Typography>
          </Stack>
          <Stack direction="horizontal" gap="x2" align="center">
            <Badge type="secondary" semantic={isExact ? 'info' : 'success'}>
              {isExact ? 'Точная' : 'Морфологическая'}
            </Badge>
            <Button
              variant="ghost"
              size="small"
              onClick={() => onJumpToCondition(pair.row_a)}
            >
              Перейти
            </Button>
          </Stack>
        </Stack>
      </ListItem>
    );
  };

  const fullCount = report?.full?.length ?? 0;
  const softCount = report?.soft?.length ?? 0;
  const total = fullCount + softCount;
  const isEmpty = status === 'ready' && total === 0;

  return (
    <Modal open={open}>
      <Box
        style={{
          background: 'var(--color-background-base)',
          borderRadius: 'var(--size-border-radius-x4)',
          maxWidth: '700px',
          width: 'min(700px, 92vw)',
          maxHeight: '85vh',
          overflow: 'auto',
        }}
      >
        <Box style={{ padding: 'var(--size-spacing-x4)' }}>
          <Stack direction="vertical" gap="x3">
            <Stack direction="horizontal" gap="x2" align="center" justify="space-between">
              <Typography variant="h6">Дубликаты фраз</Typography>
              <Stack direction="horizontal" gap="x2" align="center">
                <Button
                  variant="outlined"
                  size="small"
                  disabled={status === 'loading' || !dictName}
                  onClick={() => void fetchDuplicates()}
                >
                  {status === 'loading' ? 'Ищем…' : 'Перепроверить'}
                </Button>
                <IconButton
                  iconName={Icons.Close}
                  variant="plain"
                  aria-label="Закрыть"
                  onClick={onClose}
                />
              </Stack>
            </Stack>

            {!dictName ? (
              <InlineAlert type="info">Выберите словарь.</InlineAlert>
            ) : status === 'loading' ? (
              <Stack direction="horizontal" gap="x2" align="center">
                <Progress shape="circle" cycled />
                <Typography variant="body2" color="colorTextInactive">
                  Ищем дубликаты…
                </Typography>
              </Stack>
            ) : status === 'error' ? (
              <Stack direction="vertical" gap="x3">
                <InlineAlert type="error">Ошибка поиска дубликатов</InlineAlert>
                {error && (
                  <Typography variant="caption" color="colorTextInactive">
                    {error}
                  </Typography>
                )}
                <Button variant="outlined" size="small" onClick={() => void fetchDuplicates()}>
                  Повторить
                </Button>
              </Stack>
            ) : isEmpty ? (
              <InlineAlert type="success">Дубликатов не найдено</InlineAlert>
            ) : report ? (
              <Stack direction="vertical" gap="x3">
                <Tabs selectedTabIndex={tabIndex} onChange={setTabIndex}>
                  <Tab label={`Полные (${fullCount})`}>
                    <List>
                      {report.full.length === 0 ? (
                        <ListItem>
                          <Typography variant="body2" color="colorTextInactive">
                            Нет полных дубликатов.
                          </Typography>
                        </ListItem>
                      ) : (
                        report.full.map((p) => renderDupPair(p, 'full'))
                      )}
                    </List>
                  </Tab>
                  <Tab label={`Частичные (${softCount})`}>
                    <List>
                      {report.soft.length === 0 ? (
                        <ListItem>
                          <Typography variant="body2" color="colorTextInactive">
                            Нет частичных дубликатов.
                          </Typography>
                        </ListItem>
                      ) : (
                        report.soft.map((p) => renderDupPair(p, 'soft'))
                      )}
                    </List>
                  </Tab>
                </Tabs>
                <Stack direction="horizontal" justify="end">
                  <Button variant="outlined" onClick={onClose}>
                    Закрыть
                  </Button>
                </Stack>
              </Stack>
            ) : null}
          </Stack>
        </Box>
      </Box>
    </Modal>
  );
}

export const DuplicatesModal = memo(DuplicatesModalBase);
