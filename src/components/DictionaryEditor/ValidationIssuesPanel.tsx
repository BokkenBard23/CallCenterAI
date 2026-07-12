/**
 * ValidationIssuesPanel — Card with structural validation results.
 *
 * Visible when `open=true` (parent toggles from header "Валидация" button).
 * Re-fetches on first visibility and when `dictName` changes while open.
 *
 * Layout:
 *   - Card header: "Валидация" + Counter (errors/warnings) + re-validate Button
 *   - Errors group: "Ошибки" + Counter error + List (issue rows + jump button)
 *   - Warnings group: "Предупреждения" + Counter warning + List
 *   - Empty (0 issues): InlineAlert success + Badge success "Ошибок не найдено"
 *   - Error: InlineAlert danger + retry
 *
 * Jump-to-condition: each issue with row ≥ 0 calls `onJumpToCondition(row)`.
 */

import { memo, useCallback, useEffect, useRef, useState } from 'react';
import {
  Badge,
  Box,
  Button,
  Card,
  Counter,
  InlineAlert,
  List,
  ListItem,
  Progress,
  Stack,
  Typography,
} from '@beeline/design-system-react';
import { validateDictionary } from '../../api/client';
import type { ValidationResult, ValidationIssue } from '../../types/api';

export interface ValidationIssuesPanelProps {
  open: boolean;
  sessionId: string;
  dictName: string | null;
  /** Called when user clicks an issue row to navigate ConditionsTable. */
  onJumpToCondition: (rowIdx: number) => void;
}

type Status = 'idle' | 'loading' | 'ready' | 'error';

function ValidationIssuesPanelBase({
  open,
  sessionId,
  dictName,
  onJumpToCondition,
}: ValidationIssuesPanelProps) {
  const [status, setStatus] = useState<Status>('idle');
  const [result, setResult] = useState<ValidationResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const fetchValidation = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setStatus('loading');
    setError(null);
    try {
      const data = await validateDictionary(
        sessionId,
        { dict_name: dictName },
        controller.signal,
      );
      setResult(data);
      setStatus('ready');
    } catch (err) {
      if (controller.signal.aborted) return;
      setStatus('error');
      setError(
        err && typeof err === 'object' && 'message' in err
          ? String((err as { message: string }).message)
          : 'Ошибка валидации',
      );
    }
  }, [sessionId, dictName]);

  useEffect(() => {
    if (open && dictName) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on panel open; setState is async, not synchronous cascading.
      void fetchValidation();
    }
    return () => abortRef.current?.abort();
  }, [open, dictName, fetchValidation]);

  if (!open) return null;

  const renderIssue = (issue: ValidationIssue, keyPrefix: string) => {
    const isGlobal = issue.row < 0;
    const label = isGlobal ? 'Глобально' : `Строка #${issue.row + 1}`;
    return (
      <ListItem key={`${keyPrefix}-${issue.row}-${issue.message.slice(0, 16)}`}>
        <Stack
          direction="horizontal"
          gap="x2"
          align="center"
          justify="space-between"
          wrap="wrap"
          style={{ width: '100%' }}
        >
          <Stack direction="vertical" gap="x1">
            <Typography variant="body2" color="colorTextInactive">
              {label}
            </Typography>
            <Typography variant="body2">{issue.message}</Typography>
          </Stack>
          {!isGlobal && (
            <Button
              variant="ghost"
              size="small"
              onClick={() => onJumpToCondition(issue.row)}
            >
              Перейти
            </Button>
          )}
        </Stack>
      </ListItem>
    );
  };

  return (
    <Card>
      <Box style={{ padding: 'var(--size-spacing-x4)' }}>
        <Stack direction="vertical" gap="x3">
          <Stack direction="horizontal" gap="x2" align="center" justify="space-between">
            <Stack direction="horizontal" gap="x2" align="center">
              <Typography variant="h6">Валидация</Typography>
              {status === 'ready' && result && (
                <>
                  <Counter
                    count={result.errors.length}
                    error={result.errors.length > 0}
                    size="small"
                    tooltipTitle="Ошибки"
                  />
                  <Counter
                    count={result.warnings.length}
                    warning={result.warnings.length > 0}
                    size="small"
                    tooltipTitle="Предупреждения"
                  />
                </>
              )}
            </Stack>
            <Button
              variant="outlined"
              size="small"
              disabled={status === 'loading' || !dictName}
              startIcon={status === 'loading' ? undefined : undefined}
              onClick={() => void fetchValidation()}
            >
              {status === 'loading' ? 'Проверяем…' : 'Перепроверить'}
            </Button>
          </Stack>

          {!dictName ? (
            <InlineAlert type="info">Выберите словарь для валидации.</InlineAlert>
          ) : status === 'loading' ? (
            <Stack direction="horizontal" gap="x2" align="center">
              <Progress shape="circle" cycled />
              <Typography variant="body2" color="colorTextInactive">
                Проверяем…
              </Typography>
            </Stack>
          ) : status === 'error' ? (
            <Stack direction="vertical" gap="x3">
              <InlineAlert type="error">Ошибка валидации</InlineAlert>
              {error && (
                <Typography variant="caption" color="colorTextInactive">
                  {error}
                </Typography>
              )}
              <Button variant="outlined" size="small" onClick={() => void fetchValidation()}>
                Повторить
              </Button>
            </Stack>
          ) : status === 'ready' && result ? (
            result.errors.length === 0 && result.warnings.length === 0 ? (
              <Stack direction="horizontal" gap="x2" align="center">
                <InlineAlert type="success">Ошибок не найдено</InlineAlert>
                <Badge type="secondary" semantic="success" dot>
                  OK
                </Badge>
              </Stack>
            ) : (
              <Stack direction="vertical" gap="x3">
                {result.errors.length > 0 && (
                  <Stack direction="vertical" gap="x1">
                    <Stack direction="horizontal" gap="x2" align="center">
                      <Typography variant="body2">Ошибки</Typography>
                      <Counter count={result.errors.length} error size="small" />
                    </Stack>
                    <List>
                      {result.errors.map((e) => renderIssue(e, 'err'))}
                    </List>
                  </Stack>
                )}
                {result.warnings.length > 0 && (
                  <Stack direction="vertical" gap="x1">
                    <Stack direction="horizontal" gap="x2" align="center">
                      <Typography variant="body2">Предупреждения</Typography>
                      <Counter count={result.warnings.length} warning size="small" />
                    </Stack>
                    <List>
                      {result.warnings.map((w) => renderIssue(w, 'warn'))}
                    </List>
                  </Stack>
                )}
              </Stack>
            )
          ) : null}
        </Stack>
      </Box>
    </Card>
  );
}

export const ValidationIssuesPanel = memo(ValidationIssuesPanelBase);
