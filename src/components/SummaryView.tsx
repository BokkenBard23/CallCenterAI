/**
 * SummaryView — displays LLM analysis summary.
 * Shows topic, sentiment, resolution, key points, and summary text.
 */

import { useMemo, memo } from 'react';
import {
  Badge,
  Box,
  Card,
  Divider,
  Progress,
  Stack,
  Typography,
} from '@beeline/design-system-react';

import type { LLMResult, SearchResult } from '../types/api';
import RestructuredDialogue from './RestructuredDialogue';

interface SummaryViewProps {
  llmResult: LLMResult | null;
  searchResult: SearchResult | null;
  /** True while LLM analysis is in progress */
  llmLoading?: boolean;
}

/** Map sentiment string to Badge props */
function sentimentBadgeProps(sentiment: string): {
  semantic: 'success' | 'warning' | 'danger' | 'info';
  type: 'primary' | 'secondary' | 'tertiary';
  label: string;
} {
  switch (sentiment) {
    case 'positive':
      return { semantic: 'success', type: 'secondary', label: 'Позитивный' };
    case 'negative':
      return { semantic: 'danger', type: 'secondary', label: 'Негативный' };
    case 'mixed':
      return { semantic: 'warning', type: 'secondary', label: 'Смешанный' };
    default:
      return { semantic: 'info', type: 'secondary', label: 'Нейтральный' };
  }
}

/** Map resolution string to Badge props */
function resolutionBadgeProps(resolution: string): {
  semantic: 'success' | 'warning' | 'danger' | 'info';
  type: 'primary' | 'secondary' | 'tertiary';
  label: string;
} {
  switch (resolution) {
    case 'resolved':
      return { semantic: 'success', type: 'tertiary', label: 'Решён' };
    case 'escalated':
      return { semantic: 'danger', type: 'tertiary', label: 'Эскалация' };
    case 'partial':
      return { semantic: 'warning', type: 'tertiary', label: 'Частично' };
    default:
      return { semantic: 'info', type: 'tertiary', label: 'Не решён' };
  }
}

export default memo(function SummaryView({ llmResult, searchResult, llmLoading }: SummaryViewProps) {
  const sentiment = useMemo(
    () => (llmResult ? sentimentBadgeProps(llmResult.client_sentiment) : null),
    [llmResult],
  );

  const resolution = useMemo(
    () => (llmResult ? resolutionBadgeProps(llmResult.resolution) : null),
    [llmResult],
  );

  // ─── LLM Loading ────────────────────────────────────
  if (llmLoading) {
    return (
      <Card>
        <Box padding="x6">
          <Stack direction="vertical" spacing="x4" align="center">
            <Typography variant="h5" style={{ color: 'var(--color-status-info, #1e88e5)' }}>
              LLM-анализ выполняется...
            </Typography>
            <Progress shape="animated" cycled />
            <Typography variant="body2" inactive>
              Результаты поиска текста доступны на вкладке «Выделенный текст».
            </Typography>
          </Stack>
        </Box>
      </Card>
    );
  }

  // ─── No LLM result ───────────────────────────────────
  // R-H1 FIX (vision-audit iter 3): canonical "LLM-unavailable" status lives
  // HERE as the single consolidated status block — the page-level Banner in
  // ResultsPage was removed to avoid the state-mixing defect (banner + card
  // heading + body + stats shown simultaneously — vision audit R-H1-STATE-MIX).
  // This Card now carries: heading (h5) → cause subtitle → actionable hint,
  // giving ONE unambiguous status representation in the LLM-unavailable state.
  if (!llmResult) {
    return (
      <Card className="summary-unavailable-card">
        <Box padding="x6">
          <Stack direction="vertical" spacing="x4" align="stretch">
            <Stack direction="horizontal" spacing="x3" align="center">
              <Typography variant="h5" style={{ margin: 0 }}>
                LLM-сводка недоступна
              </Typography>
              <Badge semantic="warning" type="tertiary" dot>
                Анализ не выполнен
              </Badge>
            </Stack>
            <Typography variant="body1" inactive>
              Сводный анализ не выполнен или завершился с ошибкой.
              Причины: провайдер недоступен, превышен лимит запросов
              или внутренняя ошибка LLM.
            </Typography>
            <Divider />
            <Stack direction="horizontal" spacing="x3" align="center" justify="space-between" wrap="wrap">
              <Typography variant="body2" inactive>
                Результаты поиска по словарю доступны во вкладке «Выделенный текст».
              </Typography>
              <Typography variant="caption" inactive>
                Повторите анализ позже или обратитесь к администратору.
              </Typography>
            </Stack>
          </Stack>
        </Box>
      </Card>
    );
  }

  // ─── Full summary ─────────────────────────────────────
  return (
    <Stack direction="vertical" spacing="x4">
      {/* ── Meta badges ── */}
      <Card>
        <Box padding="x4">
          <Stack direction="horizontal" spacing="x3" align="center" wrap="wrap">
            {llmResult.topic && (
              <Typography variant="subtitle2">{llmResult.topic}</Typography>
            )}
            {sentiment && (
              <Badge semantic={sentiment.semantic} type={sentiment.type}>
                {sentiment.label}
              </Badge>
            )}
            {resolution && (
              <Badge semantic={resolution.semantic} type={resolution.type} dot>
                {resolution.label}
              </Badge>
            )}
            <Typography variant="caption" inactive>
              {llmResult.provider} / {llmResult.model}
            </Typography>
          </Stack>
        </Box>
      </Card>

      {/* ── Summary text ── */}
      {llmResult.summary && (
        <Card>
          <Box padding="x4">
            <Stack direction="vertical" spacing="x3">
              <Typography variant="h6">Сводка</Typography>
              <Typography variant="body1">{llmResult.summary}</Typography>
            </Stack>
          </Box>
        </Card>
      )}

      {/* ── Key points ── */}
      {llmResult.key_points.length > 0 && (
        <Card>
          <Box padding="x4">
            <Stack direction="vertical" spacing="x3">
              <Typography variant="h6">Ключевые моменты</Typography>
              <ul className="key-points-list">
                {llmResult.key_points.map((point, idx) => (
                  <li key={idx}>
                    <Typography variant="body2">{point}</Typography>
                  </li>
                ))}
              </ul>
            </Stack>
          </Box>
        </Card>
      )}

      {/* ── Result / recommendation ── */}
      {llmResult.result && (
        <Card>
          <Box padding="x4">
            <Stack direction="vertical" spacing="x3">
              <Typography variant="h6">Результат</Typography>
              <Typography variant="body1">{llmResult.result}</Typography>
            </Stack>
          </Box>
        </Card>
      )}

      {/* ── Dictionary match stats ── */}
      {searchResult && (
        <>
          <Divider />
          <Card>
            <Box padding="x4">
              <Stack direction="vertical" spacing="x3">
                <Typography variant="h6">Статистика совпадений</Typography>
                <Stack direction="horizontal" spacing="x4" wrap="wrap">
                  <Typography variant="body2">
                    Всего совпадений: {searchResult.total_matches}
                  </Typography>
                  <Typography variant="body2">
                    Сегментов: {searchResult.segments.length}
                  </Typography>
                </Stack>
              </Stack>
            </Box>
          </Card>
        </>
      )}

      {/* ── Restructured dialogue ── */}
      {llmResult.restructured_dialogue && (
        <>
          <Divider />
          <RestructuredDialogue text={llmResult.restructured_dialogue} />
        </>
      )}
    </Stack>
  );
});
