/**
 * QualityScorePanel — визуализация оценки качества диалога.
 *
 * Функционал:
 *   - Карточка общего балла (большое число + Badge уровня)
 *   - SVG radar chart с 12 осями (без внешних библиотек)
 *   - Таблица категорий: русское название | Badge уровня | Score bar | Обоснование (Collapse)
 *   - Сильные стороны / Слабые места как Chip
 *   - Рекомендации как Card список
 *   - Loading state с Skeleton
 *   - Error state с InlineAlert
 *
 * Интегрируется в ResultsPage как сворачиваемая секция.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Badge,
  Box,
  Button,
  Card,
  Chip,
  Icon,
  InlineAlert,
  Skeleton,
  Stack,
  Typography,
} from '@beeline/design-system-react';
import { Icons } from '@beeline/design-tokens/js/iconfont';

import { getQualityScore } from '../../api/client';
import {
  QUALITY_CATEGORY_LABELS,
  QUALITY_CATEGORIES,
} from '../../types/api';
import type {
  CategoryScore,
  QualityLevel,
  QualityScoreResult,
} from '../../types/api';

// ═══════════════════════════════════════════════════════════
// Props
// ═══════════════════════════════════════════════════════════

export interface QualityScorePanelProps {
  /** ID сессии для запроса оценки */
  sessionId: string;
  /** ID провайдера (по умолчанию 'beeline') */
  providerId?: string;
  /** Начальное состояние: свёрнут/развёрнут */
  defaultExpanded?: boolean;
}

// ═══════════════════════════════════════════════════════════
// Цветовая схема по уровню
// ═══════════════════════════════════════════════════════════

const LEVEL_COLORS: Record<QualityLevel, string> = {
  high: '#4caf50',
  medium: '#ff9800',
  low: '#f44336',
};

const LEVEL_LABELS: Record<QualityLevel, string> = {
  high: 'Высокий',
  medium: 'Средний',
  low: 'Низкий',
};

const LEVEL_BADGE_SEMANTIC: Record<QualityLevel, 'success' | 'warning' | 'danger'> = {
  high: 'success',
  medium: 'warning',
  low: 'danger',
};

// ═══════════════════════════════════════════════════════════
// SVG Radar Chart (12 осей, без внешних библиотек)
// ═══════════════════════════════════════════════════════════

const RADAR_SIZE = 280;
const RADAR_CENTER = RADAR_SIZE / 2;
const RADAR_RADIUS = 110;
const NUM_AXES = QUALITY_CATEGORIES.length; // 12

/** Вычисляет точку на оси radar chart по индексу и значению (0-1) */
function getRadarPoint(index: number, value: number): { x: number; y: number } {
  const angle = (Math.PI * 2 * index) / NUM_AXES - Math.PI / 2;
  const r = RADAR_RADIUS * value;
  return {
    x: RADAR_CENTER + r * Math.cos(angle),
    y: RADAR_CENTER + r * Math.sin(angle),
  };
}

interface RadarChartProps {
  categories: CategoryScore[];
}

function RadarChart({ categories }: RadarChartProps) {
  // Строим карту category -> score
  const scoreMap = new Map<string, number>();
  categories.forEach((c) => {
    scoreMap.set(c.category, c.score);
  });

  // Точки многоугольника данных
  const dataPoints = QUALITY_CATEGORIES.map((cat, i) => {
    const score = scoreMap.get(cat) ?? 0;
    return getRadarPoint(i, score);
  });

  const dataPath = dataPoints.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ') + ' Z';

  // Концентрические кольца (20%, 40%, 60%, 80%, 100%)
  const rings = [0.2, 0.4, 0.6, 0.8, 1.0].map((level) => {
    const pts = QUALITY_CATEGORIES.map((_, i) => getRadarPoint(i, level));
    return pts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ') + ' Z';
  });

  // Оси
  const axisLines = QUALITY_CATEGORIES.map((_, i) => {
    const edge = getRadarPoint(i, 1);
    return `M ${RADAR_CENTER} ${RADAR_CENTER} L ${edge.x} ${edge.y}`;
  });

  // Подписи осей
  const labels = QUALITY_CATEGORIES.map((cat, i) => {
    const edge = getRadarPoint(i, 1.22);
    return {
      x: edge.x,
      y: edge.y,
      text: QUALITY_CATEGORY_LABELS[cat],
      key: cat,
    };
  });

  return (
    <svg
      viewBox={`0 0 ${RADAR_SIZE} ${RADAR_SIZE}`}
      width={RADAR_SIZE}
      height={RADAR_SIZE}
      role="img"
      aria-label="Радарная диаграмма оценки качества по 12 категориям"
      style={{ maxWidth: '100%', height: 'auto' }}
    >
      {/* Кольца */}
      {rings.map((d, i) => (
        <path
          key={`ring-${i}`}
          d={d}
          fill="none"
          stroke="var(--color-border-default, #e0e0e0)"
          strokeWidth={0.5}
        />
      ))}

      {/* Оси */}
      {axisLines.map((d, i) => (
        <path
          key={`axis-${i}`}
          d={d}
          fill="none"
          stroke="var(--color-border-default, #e0e0e0)"
          strokeWidth={0.5}
        />
      ))}

      {/* Заливка данных */}
      <path
        d={dataPath}
        fill="rgba(0, 112, 224, 0.15)"
        stroke="var(--color-background-brand, #0070E0)"
        strokeWidth={1.5}
      />

      {/* Точки данных */}
      {dataPoints.map((p, i) => {
        const cat = QUALITY_CATEGORIES[i];
        const score = scoreMap.get(cat) ?? 0;
        const level = categories.find((c) => c.category === cat)?.level ?? 'medium';
        return (
          <circle
            key={`dot-${cat}`}
            cx={p.x}
            cy={p.y}
            r={3.5}
            fill={LEVEL_COLORS[level]}
            stroke="white"
            strokeWidth={1}
          >
            <title>{`${QUALITY_CATEGORY_LABELS[cat]}: ${(score * 100).toFixed(0)}%`}</title>
          </circle>
        );
      })}

      {/* Подписи */}
      {labels.map((l) => (
        <text
          key={l.key}
          x={l.x}
          y={l.y}
          textAnchor="middle"
          dominantBaseline="middle"
          fontSize={9}
          fill="var(--color-text-primary, #333)"
        >
          {l.text}
        </text>
      ))}
    </svg>
  );
}

// ═══════════════════════════════════════════════════════════
// Score Bar (CSS-based progress bar для таблицы)
// ═══════════════════════════════════════════════════════════

interface ScoreBarProps {
  score: number;
  level: QualityLevel;
}

function ScoreBar({ score, level }: ScoreBarProps) {
  const percent = Math.round(score * 100);
  return (
    <Box
      style={{ display: 'flex', alignItems: 'center', gap: '8px', width: '100%' }}
      role="meter"
      aria-valuenow={percent}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={`Оценка: ${percent}%`}
    >
      <Box
        style={{
          flex: 1,
          height: '8px',
          borderRadius: '4px',
          background: 'var(--color-background-secondary, #e8e8e8)',
          overflow: 'hidden',
        }}
      >
        <Box
          style={{
            width: `${percent}%`,
            height: '100%',
            borderRadius: '4px',
            background: LEVEL_COLORS[level],
            transition: 'width 0.5s ease',
          }}
        />
      </Box>
      <Typography variant="caption" style={{ minWidth: '36px', textAlign: 'right' }}>
        {percent}%
      </Typography>
    </Box>
  );
}

// ═══════════════════════════════════════════════════════════
// Loading Skeleton
// ═══════════════════════════════════════════════════════════

function QualityScoreSkeleton() {
  return (
    <Stack direction="vertical" spacing="x4">
      <Skeleton variant="title" width="60%" />
      <Stack direction="horizontal" spacing="x6" align="start">
        <Skeleton variant="text" width="280px" height="280px" />
        <Stack direction="vertical" spacing="x3" style={{ flex: 1 }}>
          {Array.from({ length: 5 }, (_, i) => (
            <Skeleton key={i} variant="text" width="100%" height={40} />
          ))}
        </Stack>
      </Stack>
      <Skeleton variant="text" width="100%" height={60} />
    </Stack>
  );
}

// ═══════════════════════════════════════════════════════════
// Main Component
// ═══════════════════════════════════════════════════════════

export function QualityScorePanel({
  sessionId,
  providerId = 'beeline',
  defaultExpanded = false,
}: QualityScorePanelProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const [data, setData] = useState<QualityScoreResult | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // ── Загрузка оценки по требованию ──
  const fetchScore = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setIsLoading(true);
    setError(null);

    try {
      const result = await getQualityScore(
        { session_id: sessionId, provider_id: providerId },
        controller.signal,
      );
      setData(result);
    } catch (err) {
      if (controller.signal.aborted) return;
      const message = err instanceof Error ? err.message : 'Ошибка при получении оценки качества';
      setError(message);
    } finally {
      if (!controller.signal.aborted) {
        setIsLoading(false);
      }
    }
  }, [sessionId, providerId]);

  // ── При раскрытии — загрузить данные ──
  const handleToggle = useCallback(() => {
    const nextExpanded = !expanded;
    setExpanded(nextExpanded);
    if (nextExpanded && !data && !isLoading && !error) {
      fetchScore();
    }
  }, [expanded, data, isLoading, error, fetchScore]);

  // ── Если defaultExpanded, загрузить данные при маунте ──
  // fetchScore triggers setState internally, but this is intentional:
  // on mount, if expanded (defaultExpanded), we must fetch quality data.
  // This is a "subscribe to external system" pattern — the external system
  // is the API server, and we fetch data when the panel is expanded.
  useEffect(() => {
    if (expanded && !data && !isLoading && !error) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- Intentional: fetch quality data on mount when defaultExpanded
      fetchScore();
    }
    // Only on mount — intentional: fetch data once when defaultExpanded=true
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Повторная попытка при ошибке ──
  const handleRetry = useCallback(() => {
    fetchScore();
  }, [fetchScore]);

  // ── Cleanup ──
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  // ── Вычисляем общий уровень для Badge ──
  const overallLevel = data?.overall_level ?? 'medium';
  const overallPercent = data ? Math.round(data.overall_score * 100) : 0;

  return (
    <Box aria-label="Панель оценки качества">
      {/* ═══ Toggle button ═══ */}
      <Button
        variant="outlined"
        size="small"
        onClick={handleToggle}
        startIcon={<Icon iconName={expanded ? Icons.ArrowUp : Icons.ArrowDown} />}
      >
        {expanded ? 'Скрыть оценку качества' : 'Оценка качества'}
      </Button>

      {/* ═══ Content (only when expanded) ═══ */}
      {expanded && (
        <Stack direction="vertical" spacing="x4">
          {/* ═══ Loading ═══ */}
          {isLoading && !data && <QualityScoreSkeleton />}

          {/* ═══ Error ═══ */}
          {error && !isLoading && (
            <InlineAlert type="error" iconName={Icons.WarningCircled}>
              <Stack direction="horizontal" spacing="x2" align="center">
                <Typography variant="body2">{error}</Typography>
                <Button variant="outlined" size="small" onClick={handleRetry}>
                  Повторить
                </Button>
              </Stack>
            </InlineAlert>
          )}

          {/* ═══ Data loaded ═══ */}
          {data && (
            <Stack direction="vertical" spacing="x6">
            {/* ── Общая оценка + Radar ── */}
            <Stack
              direction="horizontal"
              spacing="x6"
              align="start"
              style={{ flexWrap: 'wrap' }}
            >
              {/* Карточка общего балла */}
              <Card style={{ minWidth: '180px', textAlign: 'center' }}>
                <Stack direction="vertical" spacing="x3" align="center">
                  <Typography variant="caption" inactive>
                    Общая оценка
                  </Typography>
                  <Typography
                    variant="h1"
                    style={{
                      margin: 0,
                      color: LEVEL_COLORS[overallLevel],
                      fontSize: '3rem',
                      lineHeight: 1,
                    }}
                  >
                    {overallPercent}
                  </Typography>
                  <Badge
                    type="secondary"
                    semantic={LEVEL_BADGE_SEMANTIC[overallLevel]}
                  >
                    {LEVEL_LABELS[overallLevel]}
                  </Badge>
                  {data.provider && (
                    <Typography variant="caption" inactive>
                      {data.provider} / {data.model}
                    </Typography>
                  )}
                </Stack>
              </Card>

              {/* Radar Chart */}
              <RadarChart categories={data.categories} />
            </Stack>

            {/* ── Таблица категорий ── */}
            <Card>
              <Stack direction="vertical" spacing="x2">
                <Typography variant="h5" style={{ margin: 0 }}>
                  Категории оценки
                </Typography>
                <table
                  style={{
                    width: '100%',
                    borderCollapse: 'collapse',
                    fontSize: '14px',
                  }}
                  role="table"
                  aria-label="Детальные оценки по категориям"
                >
                  <thead>
                    <tr>
                      <th style={{ textAlign: 'left', padding: '8px 12px', borderBottom: '1px solid var(--color-border-default, #e0e0e0)' }}>
                        Категория
                      </th>
                      <th style={{ textAlign: 'left', padding: '8px 12px', borderBottom: '1px solid var(--color-border-default, #e0e0e0)' }}>
                        Уровень
                      </th>
                      <th style={{ textAlign: 'left', padding: '8px 12px', borderBottom: '1px solid var(--color-border-default, #e0e0e0)', minWidth: '200px' }}>
                        Оценка
                      </th>
                      <th style={{ textAlign: 'left', padding: '8px 12px', borderBottom: '1px solid var(--color-border-default, #e0e0e0)' }}>
                        Обоснование
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.categories.map((cat) => (
                      <tr key={cat.category}>
                        <td style={{ padding: '8px 12px', borderBottom: '1px solid var(--color-border-default, #e0e0e0)' }}>
                          <Typography variant="body2">
                            {QUALITY_CATEGORY_LABELS[cat.category as keyof typeof QUALITY_CATEGORY_LABELS] ?? cat.category}
                          </Typography>
                        </td>
                        <td style={{ padding: '8px 12px', borderBottom: '1px solid var(--color-border-default, #e0e0e0)' }}>
                          <Badge
                            type="secondary"
                            semantic={LEVEL_BADGE_SEMANTIC[cat.level]}
                          >
                            {LEVEL_LABELS[cat.level]}
                          </Badge>
                        </td>
                        <td style={{ padding: '8px 12px', borderBottom: '1px solid var(--color-border-default, #e0e0e0)' }}>
                          <ScoreBar score={cat.score} level={cat.level} />
                        </td>
                        <td style={{ padding: '8px 12px', borderBottom: '1px solid var(--color-border-default, #e0e0e0)', maxWidth: '300px' }}>
                          <details>
                            <summary style={{ cursor: 'pointer', color: 'var(--color-background-brand, #0070E0)' }}>
                              Показать обоснование
                            </summary>
                            <Typography variant="body2">
                              {cat.justification || 'Нет обоснования'}
                            </Typography>
                          </details>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Stack>
            </Card>

            {/* ── Сильные и слабые стороны (Chips) ── */}
            <Stack direction="horizontal" spacing="x6" style={{ flexWrap: 'wrap' }}>
              {/* Сильные стороны */}
              {data.strengths.length > 0 && (
                <Stack direction="vertical" spacing="x2" style={{ flex: '1 1 300px', minWidth: '250px' }}>
                  <Typography variant="h6" style={{ color: LEVEL_COLORS.high, margin: 0 }}>
                    Сильные стороны
                  </Typography>
                  <Stack direction="horizontal" spacing="x1" style={{ flexWrap: 'wrap' }}>
                    {data.strengths.map((s, i) => (
                      <Chip
                        key={`strength-${i}`}
                        label={s}
                        active
                      />
                    ))}
                  </Stack>
                </Stack>
              )}

              {/* Слабые стороны */}
              {data.weaknesses.length > 0 && (
                <Stack direction="vertical" spacing="x2" style={{ flex: '1 1 300px', minWidth: '250px' }}>
                  <Typography variant="h6" style={{ color: LEVEL_COLORS.low, margin: 0 }}>
                    Слабые стороны
                  </Typography>
                  <Stack direction="horizontal" spacing="x1" style={{ flexWrap: 'wrap' }}>
                    {data.weaknesses.map((w, i) => (
                      <Chip
                        key={`weakness-${i}`}
                        label={w}
                      />
                    ))}
                  </Stack>
                </Stack>
              )}
            </Stack>

            {/* ── Рекомендации (Card список) ── */}
            {data.recommendations.length > 0 && (
              <Stack direction="vertical" spacing="x3">
                <Typography variant="h5" style={{ margin: 0 }}>
                  Рекомендации
                </Typography>
                {data.recommendations.map((rec, i) => (
                  <Card key={`rec-${i}`}>
                    <Stack direction="horizontal" spacing="x3" align="start">
                      <Typography
                        variant="h6"
                        style={{
                          margin: 0,
                          color: 'var(--color-background-brand, #0070E0)',
                          minWidth: '24px',
                        }}
                      >
                        {i + 1}
                      </Typography>
                      <Typography variant="body2">{rec}</Typography>
                     </Stack>
                   </Card>
                 ))}
               </Stack>
             )}
            </Stack>
          )}
        </Stack>
      )}
    </Box>
  );
}


