/**
 * AIAnalysisPanel — Sidesheet with LLM dictionary analysis.
 *
 * Renders when `open=true`. Provider select (optional, default=auto) +
 * "Запустить анализ" Button → POST /analyze-ai (180s timeout, AbortController
 * for cancel on close). Markdown rendering via `react-markdown` (ds_gap dep).
 *
 * Layout:
 *   - Sidesheet (size='large' 444px, mode='modal', hasOverlay=true)
 *   - Provider Select + Run Button
 *   - Loading: Progress circular indeterminate + "Анализируем словарь…"
 *   - Summary section: Typography (title) + react-markdown
 *   - Examples section: Typography + List + ListItem
 *   - Recommendations section: Typography + numbered List
 *   - Error: InlineAlert danger + retry (graceful degradation — editor remains functional)
 *   - Empty: "Выберите словарь для анализа"
 *
 * Anti-clone: uses `react-markdown` for AI summary (NOT LexiCore regex `^###? `).
 */

import { memo, useCallback, useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import {
  Box,
  Button,
  Divider,
  Icon,
  InlineAlert,
  List,
  ListItem,
  Progress,
  Sidesheet,
  Stack,
  Typography,
} from '@beeline/design-system-react';
import { Icons } from '@beeline/design-tokens/js/iconfont';
import { analyzeDictionaryAi, getProviders } from '../../api/client';
import type { DictionaryAnalysisResult, ProviderInfo } from '../../types/api';
import { SimpleSelect, type SimpleOption } from './SimpleSelect';

export interface AIAnalysisPanelProps {
  open: boolean;
  onClose: () => void;
  sessionId: string;
  dictName: string | null;
}

type Status = 'idle' | 'loading' | 'ready' | 'error';

const AUTO_PROVIDER = '__auto__';

function AIAnalysisPanelBase({
  open,
  onClose,
  sessionId,
  dictName,
}: AIAnalysisPanelProps) {
  const [status, setStatus] = useState<Status>('idle');
  const [data, setData] = useState<DictionaryAnalysisResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [providerId, setProviderId] = useState<string>(AUTO_PROVIDER);
  const abortRef = useRef<AbortController | null>(null);

  // Lazy-load providers list (filtered to configured+available).
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    getProviders()
      .then((res) => {
        if (cancelled) return;
        const list = (res.providers ?? []).filter((p) => p.configured && p.available);
        setProviders(list);
      })
      .catch(() => {
        if (cancelled) return;
        // Non-fatal: provider select just stays empty (auto).
        setProviders([]);
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  const providerOptions: SimpleOption[] = [
    { value: AUTO_PROVIDER, label: 'Авто' },
    ...providers.map((p) => ({ value: p.id, label: p.name })),
  ];

  const runAnalysis = useCallback(async () => {
    if (!dictName) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setStatus('loading');
    setError(null);
    try {
      const apiProviderId = providerId === AUTO_PROVIDER ? null : providerId;
      const result = await analyzeDictionaryAi(
        sessionId,
        { dict_name: dictName, provider_id: apiProviderId },
        controller.signal,
      );
      setData(result);
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
  }, [dictName, providerId, sessionId]);

  // Cancel any in-flight request on close.
  useEffect(() => {
    if (!open) {
      abortRef.current?.abort();
      abortRef.current = null;
    }
  }, [open]);

  const content = (
    <Box style={{ padding: 'var(--size-spacing-x4)' }}>
      <Stack direction="vertical" gap="x3">
        <Stack direction="horizontal" gap="x2" align="center" wrap="wrap">
          <div style={{ minWidth: 160 }}>
            <SimpleSelect
              options={providerOptions}
              value={providerId}
              onChange={setProviderId}
              placeholder="Авто"
            />
          </div>
          <Button
            variant="contained"
            disabled={status === 'loading' || !dictName}
            startIcon={status === 'loading' ? undefined : <Icon iconName={Icons.CpuWarning} />}
            onClick={() => void runAnalysis()}
          >
            {status === 'loading' ? 'Анализируем…' : 'Запустить анализ'}
          </Button>
        </Stack>

        {!dictName ? (
          <InlineAlert type="info">Выберите словарь для анализа.</InlineAlert>
        ) : status === 'loading' ? (
          <Stack direction="vertical" gap="x3" align="center">
            <Progress shape="circle" cycled />
            <Typography variant="body2" color="colorTextInactive">
              Анализируем словарь…
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
            <Button variant="outlined" size="small" onClick={() => void runAnalysis()}>
              Повторить
            </Button>
          </Stack>
        ) : status === 'ready' && data ? (
          <Stack direction="vertical" gap="x3">
            <Stack direction="vertical" gap="x1">
              <Typography variant="h6">Сводка</Typography>
              <Box>
                {/* ds_gap: react-markdown for AI summary (NOT LexiCore regex). */}
                <ReactMarkdown>{data.summary}</ReactMarkdown>
              </Box>
            </Stack>

            <Divider />

            <Stack direction="vertical" gap="x1">
              <Typography variant="h6">Примеры</Typography>
              {data.examples.length === 0 ? (
                <Typography variant="body2" color="colorTextInactive">
                  Нет примеров.
                </Typography>
              ) : (
                <List>
                  {data.examples.map((ex, i) => (
                    <ListItem key={`ex-${i}-${ex.slice(0, 12)}`}>
                      <Typography variant="body2">{ex}</Typography>
                    </ListItem>
                  ))}
                </List>
              )}
            </Stack>

            <Divider />

            <Stack direction="vertical" gap="x1">
              <Typography variant="h6">Рекомендации</Typography>
              {data.recommendations.length === 0 ? (
                <Typography variant="body2" color="colorTextInactive">
                  Нет рекомендаций.
                </Typography>
              ) : (
                <List type="ol">
                  {data.recommendations.map((rec, i) => (
                    <ListItem key={`rec-${i}-${rec.slice(0, 12)}`}>
                      <Typography variant="body2">{rec}</Typography>
                    </ListItem>
                  ))}
                </List>
              )}
            </Stack>
          </Stack>
        ) : (
          <Typography variant="body2" color="colorTextInactive">
            Нажмите «Запустить анализ», чтобы получить сводку, примеры и рекомендации.
          </Typography>
        )}
      </Stack>
    </Box>
  );

  return (
    <Sidesheet
      isOpen={open}
      onClose={onClose}
      title="AI анализ"
      size="large"
      mode="modal"
      hasOverlay
      hasDivider
      content={content}
    />
  );
}

export const AIAnalysisPanel = memo(AIAnalysisPanelBase);
