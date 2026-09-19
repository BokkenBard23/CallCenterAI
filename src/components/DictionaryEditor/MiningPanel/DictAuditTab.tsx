/**
 * DictAuditTab — Tab 3: LLM audit report with per-PhraseGroup recommendations.
 *
 * Composition (RAC-1: ExpansionPanel primary over Card):
 *   <Button primary onClick={handleAudit} loading={auditing}>Запустить аудит</Button>
 *   {partial && <InlineAlert type="warning">LLM rate limited, partial results</InlineAlert>}
 *   {auditResults.length > 0 && (
 *     <Box>
 *       <Box display="grid">{KPI cards}</Box>
 *       {auditResults.map(pg => (
 *         <ExpansionPanel title={pg.phrase_text} subTitle={...} open onOpen onClose>
 *           <ReactMarkdown components={Typography mapping}>{pg.llm_explanation}</ReactMarkdown>
 *           {pg.recommendations.map(rec => <RecommendationCard ... />)}
 *         </ExpansionPanel>
 *       ))}
 *       <BackToTop />  // Pattern 8 custom + DS tokens
 *     </Box>
 *   )}
 *
 * react-markdown → DS Typography mapping (AIAnalysisPanel.tsx pattern).
 * Click-to-add: onAddSuggestion({phrase: rec.phrase, channel: 'ANY', distance: rec.word_distance ?? 2}).
 */

import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import {
  Box,
  Button,
  Card,
  Counter,
  ExpansionPanel,
  Icon,
  InlineAlert,
  Skeleton,
  Stack,
  Typography,
} from '@beeline/design-system-react';
import { Icons } from '@beeline/design-tokens/js/iconfont';
import type { DictionarySuggestion, PhraseGroupAudit } from '../../../types/api';

export interface DictAuditTabProps {
  /** Completed indexing job_id (from useMiningState). */
  jobId: string | null;
  /** True while audit request is in-flight. */
  loading: boolean;
  /** Error message from audit failure (null when ok). */
  error: string | null;
  /** Last fetched PhraseGroup audit results. */
  results: PhraseGroupAudit[];
  /** True when status=partial (LLM rate limited). */
  partial: boolean;
  /** Click-to-add handler — delegates to DictionaryEditorPage.handleAddSuggestion. */
  onAddSuggestion: (suggestion: DictionarySuggestion) => Promise<void> | void;
  /** Trigger audit API call (delegated to useMiningState). */
  onAudit: () => void;
  /** True when a cancel request is in-flight. */
  cancelling?: boolean;
  /** Cancel the running audit job. */
  onCancel?: () => void;
}

function averageRecall(groups: PhraseGroupAudit[]): number {
  if (groups.length === 0) return 0;
  const sum = groups.reduce((acc, g) => acc + g.recall, 0);
  return sum / groups.length;
}

function totalRecommendations(groups: PhraseGroupAudit[]): number {
  return groups.reduce((acc, g) => acc + g.recommendations.length, 0);
}

function DictAuditTabBase({
  jobId,
  loading,
  error,
  results,
  partial,
  onAddSuggestion,
  onAudit,
  cancelling = false,
  onCancel,
}: DictAuditTabProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [showBackToTop, setShowBackToTop] = useState(false);

  // Track which recommendations have been added (per phrase_group_id + phrase key).
  const [added, setAdded] = useState<Set<string>>(new Set());

  const avgRecall = useMemo(() => averageRecall(results), [results]);
  const totalRecs = useMemo(() => totalRecommendations(results), [results]);

  const handleScroll = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    setShowBackToTop(el.scrollTop > 320);
  }, []);

  const scrollToTop = useCallback(() => {
    containerRef.current?.scrollTo({ top: 0, behavior: 'smooth' });
  }, []);

  // Reset scroll position when results change.
  useEffect(() => {
    containerRef.current?.scrollTo({ top: 0 });
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reset local state on results change (same pattern as DictionaryEditor Chunk 2 overlays)
    setShowBackToTop(false);
    setAdded(new Set());
  }, [results]);

  const handleAddRec = useCallback(
    (groupId: string, phrase: string, wordDistance?: number | null) => {
      const key = `${groupId}|${phrase}`;
      if (added.has(key)) return;
      void onAddSuggestion({
        phrase,
        channel: 'ANY',
        distance: wordDistance ?? 2,
      });
      setAdded((prev) => new Set(prev).add(key));
    },
    [added, onAddSuggestion],
  );

  return (
    <Stack direction="vertical" gap="x3">
      <Stack direction="horizontal" gap="x2" align="center" wrap="wrap">
        <Button
          variant="primary"
          loading={loading}
          disabled={!jobId || loading}
          onClick={onAudit}
        >
          Запустить аудит
        </Button>
        {loading && onCancel && (
          <Button
            variant="ghost"
            size="small"
            disabled={cancelling}
            loading={cancelling}
            onClick={onCancel}
          >
            Отменить
          </Button>
        )}
      </Stack>

      {!jobId && (
        <Typography variant="body2" color="colorTextInactive">
          Сначала проиндексируйте корпус, чтобы запустить аудит словаря.
        </Typography>
      )}

      {partial && (
        <InlineAlert type="warning">
          LLM rate limited: показаны частичные результаты аудита.
        </InlineAlert>
      )}

      {error && <InlineAlert type="error">{error}</InlineAlert>}

      {loading && (
        <Stack direction="vertical" gap="x2">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} variant="text" width="100%" height={48} />
          ))}
        </Stack>
      )}

      {!loading && !error && results.length === 0 && jobId && (
        <Stack direction="vertical" gap="x2" align="start">
          <Typography variant="body2" color="colorTextInactive">
            Запустите аудит, чтобы получить рекомендации по улучшению словаря.
          </Typography>
        </Stack>
      )}

      {!loading && !error && results.length > 0 && (
        <Box
          ref={containerRef}
          onScroll={handleScroll}
          style={{ maxHeight: '520px', overflow: 'auto', position: 'relative' }}
        >
          <Stack direction="vertical" gap="x3">
            {/* KPI cards grid (Pattern 1 inspiration, NOT CSS clone). */}
            <Box display="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 'var(--size-spacing-x3)' }}>
              <Card border="default" elevation="low">
                <Box padding="x3">
                  <Typography variant="caption" color="colorTextInactive">PhraseGroups</Typography>
                  <Typography variant="h3">{results.length}</Typography>
                </Box>
              </Card>
              <Card border="default" elevation="low">
                <Box padding="x3">
                  <Typography variant="caption" color="colorTextInactive">Avg recall</Typography>
                  <Typography variant="h3">{avgRecall.toFixed(2)}</Typography>
                </Box>
              </Card>
              <Card border="default" elevation="low">
                <Box padding="x3">
                  <Typography variant="caption" color="colorTextInactive">Recommendations</Typography>
                  <Typography variant="h3">{totalRecs}</Typography>
                </Box>
              </Card>
            </Box>

            {results.map((pg) => (
              <ExpansionPanel
                key={pg.phrase_group_id}
                title={pg.phrase_text}
                subTitle={`Recall: ${pg.recall.toFixed(2)}, Missed: ${pg.missed_count}`}
                iconName={Icons.List}
              >
                <Stack direction="vertical" gap="x2">
                  <Box>
                    {/* react-markdown → Typography mapping (AIAnalysisPanel pattern).
                        Without `components` override ReactMarkdown renders native <p>/<h*>.
                        JK6 FIX (W2): .dict-audit-markdown scope (MiningPanel.css)
                        forces the primary text token for dark-theme contrast. */}
                    <div className="dict-audit-markdown">
                      <ReactMarkdown>{pg.llm_explanation}</ReactMarkdown>
                    </div>
                  </Box>
                  {pg.recommendations.length === 0 ? (
                    <Typography variant="body2" color="colorTextInactive">
                      Нет рекомендаций для этой группы.
                    </Typography>
                  ) : (
                    <Stack direction="vertical" gap="x2">
                      {pg.recommendations.map((rec, idx) => {
                        const key = `${pg.phrase_group_id}|${rec.phrase}|${idx}`;
                        const isAdded = added.has(key);
                        return (
                          <Card key={key} border="default" elevation="low">
                            <Box padding="x3">
                              <Stack direction="vertical" gap="x1">
                                <Stack direction="horizontal" gap="x2" align="center" wrap="wrap">
                                  <Counter count={0} tooltipTitle={rec.type} size="small" />
                                  <Typography variant="body2">{rec.phrase}</Typography>
                                </Stack>
                                <Typography variant="body2" color="colorTextInactive">
                                  {rec.reason}
                                </Typography>
                                <Button
                                  variant="ghost"
                                  size="small"
                                  startIcon={<Icon iconName={isAdded ? Icons.Check : Icons.Add} />}
                                  disabled={isAdded}
                                  onClick={() =>
                                    handleAddRec(
                                      pg.phrase_group_id,
                                      rec.phrase,
                                      rec.word_distance,
                                    )
                                  }
                                >
                                  {isAdded ? 'Добавлено' : 'Добавить'}
                                </Button>
                              </Stack>
                            </Box>
                          </Card>
                        );
                      })}
                    </Stack>
                  )}
                </Stack>
              </ExpansionPanel>
            ))}

            {/* Pattern 8 Back to Top: custom fixed button + DS tokens (NOT CSS clone). */}
            {showBackToTop && (
              <Box
                style={{
                  position: 'sticky',
                  bottom: 'var(--size-spacing-x2)',
                  display: 'flex',
                  justifyContent: 'end',
                  marginTop: 'var(--size-spacing-x2)',
                }}
              >
                <Button
                  variant="primary"
                  size="small"
                  startIcon={<Icon iconName={Icons.NavArrowUp} />}
                  onClick={scrollToTop}
                >
                  Наверх
                </Button>
              </Box>
            )}
          </Stack>
        </Box>
      )}
    </Stack>
  );
}

export const DictAuditTab = memo(DictAuditTabBase);
