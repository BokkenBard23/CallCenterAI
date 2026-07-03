/**
 * PhrasePopover — Popover shown when clicking a highlighted phrase.
 *
 * Shows phrase parameters (channel, word_distance, is_exact, group structure,
 * exceptions, nested phrases) and a feedback form.
 *
 * States: editing → submitting → submitted (Snackbar) / error (InlineAlert)
 */

import { useState, useCallback, useRef, useEffect } from 'react';
import {
  Box,
  Button,
  Divider,
  Icon,
  InlineAlert,
  Popover,
  Stack,
  TextArea,
  Typography,
} from '@beeline/design-system-react';
import { Icons } from '@beeline/design-tokens/js/iconfont';

import type { DictMatch, DictionaryCondition } from '../../types/api';
import { submitFeedback, ApiError } from '../../api/client';

// ═══════════════════════════════════════════════════════════
// Channel label helper
// ═══════════════════════════════════════════════════════════

function getChannelLabel(channel: string | undefined): string {
  switch (channel?.toUpperCase()) {
    case 'CLIENT':
      return 'Клиент';
    case 'OPERATOR':
      return 'Сотрудник';
    case 'ANY':
      return 'Любой';
    default:
      return channel ?? '—';
  }
}

function getChannelColor(channel: string | undefined): string {
  switch (channel?.toUpperCase()) {
    case 'CLIENT':
      return 'var(--dict-channel-client, #1e88e5)';
    case 'OPERATOR':
      return 'var(--dict-channel-operator, #64b5f6)';
    default:
      return 'var(--dict-channel-any, #e08600)';
  }
}

function getDistanceLabel(distance: number | undefined): string {
  if (distance === undefined) return '—';
  if (distance === 0) return '0 (смежные)';
  return `${distance} (${distance === 1 ? '1 пропуск' : distance < 5 ? `${distance} пропуска` : `${distance} пропусков`})`;
}

// ═══════════════════════════════════════════════════════════
// Props
// ═══════════════════════════════════════════════════════════

interface PhrasePopoverProps {
  /** The match data to display */
  match: DictMatch | null;
  /** The corresponding condition (if available) for structure info */
  condition: DictionaryCondition | null;
  /** Whether the popover is open */
  open: boolean;
  /** Callback when popover should close */
  onClose: () => void;
  /** Anchor element ref */
  anchorElement: HTMLElement | null;
  /** Session ID for feedback submission */
  sessionId: string | null;
}

// ═══════════════════════════════════════════════════════════
// Component
// ═══════════════════════════════════════════════════════════

export default function PhrasePopover({
  match,
  condition,
  open,
  onClose,
  anchorElement,
  sessionId,
}: PhrasePopoverProps) {
  const [feedbackText, setFeedbackText] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitStatus, setSubmitStatus] = useState<'idle' | 'success' | 'error'>('idle');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const autoCloseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Track the match identity to reset form when it changes
  const matchKey = `${match?.phrase_text ?? ''}-${match?.turn_index ?? -1}`;
  const [lastMatchKey, setLastMatchKey] = useState(matchKey);

  // Reset state when match changes — using key comparison instead of useEffect
  if (matchKey !== lastMatchKey) {
    setLastMatchKey(matchKey);
    setFeedbackText('');
    setSubmitStatus('idle');
    setErrorMessage(null);
    setIsSubmitting(false);
  }

  // Cancel auto-close timer when match changes or on unmount
  useEffect(() => {
    return () => {
      if (autoCloseTimerRef.current !== null) {
        clearTimeout(autoCloseTimerRef.current);
        autoCloseTimerRef.current = null;
      }
    };
  }, [matchKey]);

  // Cleanup abort controller on unmount
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  const isFeedbackValid = feedbackText.trim().length >= 3 && feedbackText.length <= 1000;
  const isFeedbackTooLong = feedbackText.length > 1000;

  const handleSubmit = useCallback(async () => {
    if (!match || !sessionId || !isFeedbackValid) return;

    // Abort previous request
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setIsSubmitting(true);
    setSubmitStatus('idle');
    setErrorMessage(null);

    try {
      await submitFeedback(
        {
          session_id: sessionId,
          phrase_text: match.phrase_text,
          matched_text: match.matched_text,
          turn_index: match.turn_index,
          feedback_text: feedbackText.trim(),
          channel_constraint: match.channel_constraint,
          word_distance: match.word_distance,
          is_exact: match.is_exact_match,
        },
        controller.signal,
      );

      setSubmitStatus('success');
      setFeedbackText('');

      // Auto-close after 2 seconds
      autoCloseTimerRef.current = setTimeout(() => {
        autoCloseTimerRef.current = null;
        onClose();
      }, 2000);
    } catch (err) {
      if (controller.signal.aborted) return;

      if (err instanceof ApiError) {
        if (err.status === 429) {
          setErrorMessage('Слишком много запросов. Попробуйте позже.');
        } else {
          setErrorMessage(err.message || 'Ошибка при отправке');
        }
      } else {
        setErrorMessage('Ошибка при отправке замечания');
      }
      setSubmitStatus('error');
    } finally {
      if (!controller.signal.aborted) {
        setIsSubmitting(false);
      }
    }
  }, [match, sessionId, feedbackText, isFeedbackValid, onClose]);

  if (!match || !anchorElement) return null;

  // Channel info
  const channelColor = getChannelColor(match.channel_constraint);
  const channelLabel = getChannelLabel(match.channel_constraint);

  // OR-groups from condition (Chunk 5)
  const orGroups = condition?.phrase_groups?.filter((g) => g.is_or_group) ?? [];

  // Exceptions from condition (Chunk 5)
  const exceptionPhrases = condition?.exception_phrases ?? [];
  const isException = condition?.is_exception === true;

  // Nested phrases (Chunk 5)
  const nestedPhrases = condition?.nested_phrases ?? [];

  return (
    <Popover
      content={
        <Box className="phrase-popover-content" padding="x4">
          <Stack direction="vertical" spacing="x3">
            {/* Header */}
            <Stack direction="horizontal" spacing="x2" align="center" justify="space-between">
              <Typography variant="h6">Параметры фразы</Typography>
            </Stack>

            <Divider />

            {/* Parameters */}
            <Stack direction="vertical" spacing="x2">
              {/* Channel */}
              <Box className="phrase-popover-param">
                <Typography variant="body2" className="phrase-popover-param-label">
                  Канал:
                </Typography>
                <Stack direction="horizontal" spacing="x1" align="center">
                  <span
                    style={{
                      display: 'inline-block',
                      width: '8px',
                      height: '8px',
                      borderRadius: '50%',
                      backgroundColor: channelColor,
                    }}
                    aria-hidden="true"
                  />
                  <Typography variant="body2">{channelLabel}</Typography>
                </Stack>
              </Box>

              {/* Distance */}
              <Box className="phrase-popover-param">
                <Typography variant="body2" className="phrase-popover-param-label">
                  Расстояние:
                </Typography>
                <Typography
                  variant="body2"
                  style={{ fontWeight: match.word_distance === 0 ? 600 : 400 }}
                >
                  {getDistanceLabel(match.word_distance)}
                </Typography>
              </Box>

              {/* Exact */}
              <Box className="phrase-popover-param">
                <Typography variant="body2" className="phrase-popover-param-label">
                  Точность:
                </Typography>
                <Typography variant="body2">
                  {match.is_exact_match ? `\u00AB${match.phrase_text}\u00BB (exact)` : 'нет'}
                </Typography>
              </Box>

              {/* Dictionary */}
              <Box className="phrase-popover-param">
                <Typography variant="body2" className="phrase-popover-param-label">
                  Словарь:
                </Typography>
                <Typography variant="body2">{match.quarter}</Typography>
              </Box>

              {/* Turn */}
              <Box className="phrase-popover-param">
                <Typography variant="body2" className="phrase-popover-param-label">
                  Реплика:
                </Typography>
                <Typography variant="body2">#{match.turn_index + 1}</Typography>
              </Box>
            </Stack>

            {/* OR-groups (Chunk 5) */}
            {orGroups.length > 0 && (
              <>
                <Divider />
                <Box className="phrase-popover-param">
                  <Typography variant="body2" className="phrase-popover-param-label">
                    Группа:
                  </Typography>
                  <Typography variant="body2">
                    {orGroups.map((g) => `[${g.words.join(', ')}]`).join(' ')}
                  </Typography>
                </Box>
              </>
            )}

            {/* Exceptions (Chunk 5) */}
            {(isException || exceptionPhrases.length > 0) && (
              <>
                <Divider />
                <Stack direction="vertical" spacing="x1">
                  <Stack direction="horizontal" spacing="x1" align="center">
                    <Icon
                      iconName={Icons.WarningCircled}
                      size="small"
                      style={{ color: 'var(--color-status-warning, #e08600)' }}
                    />
                    <Typography
                      variant="body2"
                      style={{
                        fontWeight: 600,
                        color: 'var(--color-status-warning, #e08600)',
                      }}
                    >
                      Исключения:
                    </Typography>
                  </Stack>
                  {exceptionPhrases.map((phrase, idx) => (
                    <Typography key={idx} variant="body2" style={{ paddingLeft: '24px' }}>
                      НЕ {phrase}
                    </Typography>
                  ))}
                </Stack>
              </>
            )}

            {/* Nested phrases (Chunk 5) */}
            {nestedPhrases.length > 0 && (
              <>
                <Divider />
                <Stack direction="vertical" spacing="x1">
                  <Typography variant="body2" className="phrase-popover-param-label">
                    Доп. фразы:
                  </Typography>
                  {nestedPhrases.map((phrase, idx) => (
                    <Typography key={idx} variant="caption" style={{ paddingLeft: '24px' }}>
                      {phrase}
                    </Typography>
                  ))}
                </Stack>
              </>
            )}

            <Divider />

            {/* Feedback form */}
            <Box className="phrase-popover-feedback">
              {submitStatus === 'success' ? (
                <InlineAlert type="success" iconName={Icons.CheckCircled}>
                  Спасибо за замечание!
                </InlineAlert>
              ) : (
                <Stack direction="vertical" spacing="x2">
                  <TextArea
                    label="Что не так с этой фразой?"
                    value={feedbackText}
                    onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => {
                      setFeedbackText(e.target.value);
                      if (submitStatus === 'error') setSubmitStatus('idle');
                    }}
                    error={isFeedbackTooLong || (feedbackText.trim().length > 0 && feedbackText.trim().length < 3)}
                    helperText={
                      isFeedbackTooLong
                        ? 'Слишком длинное замечание (макс. 1000 символов)'
                        : feedbackText.trim().length > 0 && feedbackText.trim().length < 3
                          ? 'Введите хотя бы 3 символа'
                          : undefined
                    }
                    disabled={isSubmitting}
                    fullWidth
                    size="small"
                  />
                  <Stack direction="horizontal" spacing="x2" align="center" justify="space-between">
                    <Typography variant="caption" className="phrase-popover-char-count">
                      {feedbackText.length}/1000
                    </Typography>
                    <Button
                      variant="contained"
                      size="small"
                      onClick={handleSubmit}
                      disabled={!isFeedbackValid || isSubmitting}
                      startIcon={<Icon iconName={Icons.Send} />}
                    >
                      {isSubmitting ? 'Отправка...' : 'Отправить'}
                    </Button>
                  </Stack>

                  {/* Error state */}
                  {submitStatus === 'error' && errorMessage && (
                    <InlineAlert type="error" iconName={Icons.WarningCircled}>
                      {errorMessage}
                    </InlineAlert>
                  )}
                </Stack>
              )}
            </Box>
          </Stack>
        </Box>
      }
      open={open}
      triggerMode="click"
      closeMode="outside-click"
      placement="top"
      disableHover
    >
      <span />
    </Popover>
  );
}
