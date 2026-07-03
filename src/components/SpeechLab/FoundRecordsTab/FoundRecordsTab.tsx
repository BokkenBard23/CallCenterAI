/**
 * FoundRecordsTab — shows search results as RecordCard list.
 *
 * From design-spec-chunk-4:
 *   - no-search: "Запустите анализ" + Button "Найти"
 *   - loading: Progress
 *   - empty: "Фразы не найдены"
 *   - loaded: RecordCard[] with HighlightRenderer
 *   - error: Banner with error text
 */

import React, { useCallback } from 'react';
import {
  Box,
  Button,
  Card,
  Counter,
  Icon,
  Progress,
  Stack,
  Typography,
} from '@beeline/design-system-react';
import { Icons } from '@beeline/design-tokens/js/iconfont';

import type { DictMatch, TextSegment, SearchResult } from '../../../types/api';
import HighlightRenderer from '../../HighlightRenderer';

import './FoundRecordsTab.scss';

interface FoundRecordsTabProps {
  /** Search result from analysis */
  searchResult: SearchResult | null;
  /** Whether analysis is in progress */
  isSearching: boolean;
  /** Error message */
  error: string | null;
  /** Callback to run analysis */
  onRunAnalysis: () => void;
  /** Dialogue segments for displaying full text */
  segments: TextSegment[];
}

/** Single record card: collapsed shows first line + count, expanded shows full text */
interface RecordCardProps {
  segment: TextSegment;
  matches: DictMatch[];
}

const RecordCard = React.memo(function RecordCard({ segment, matches }: RecordCardProps) {
  const [isExpanded, setIsExpanded] = React.useState(false);

  const handleToggle = useCallback(() => {
    setIsExpanded((prev) => !prev);
  }, []);

  return (
    <Card className="found-record-card" elevation="low">
      <Box
        className="found-record-card__header"
        onClick={handleToggle}
        style={{ cursor: 'pointer' }}
      >
        <Stack direction="horizontal" spacing="x2" align="center" justify="space-between">
          <Stack direction="horizontal" spacing="x2" align="center" style={{ flex: 1, overflow: 'hidden' }}>
            <Icon iconName={Icons.Book} size="small" />
            <Typography variant="body2" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {segment.speaker}: {segment.text.slice(0, 80)}{segment.text.length > 80 ? '...' : ''}
            </Typography>
          </Stack>
          <Stack direction="horizontal" spacing="x2" align="center">
            <Counter count={matches.length} size="small" />
            <Icon
              iconName={isExpanded ? Icons.ArrowDown : Icons.ArrowRight}
              size="small"
            />
          </Stack>
        </Stack>
      </Box>

      {isExpanded && (
        <Box className="found-record-card__content" padding="x2">
          <Typography variant="caption" inactive>
            {segment.speaker}
          </Typography>
          <Box className="found-record-card__text">
            <HighlightRenderer text={segment.text} matches={matches} />
          </Box>
        </Box>
      )}
    </Card>
  );
});

export default function FoundRecordsTab({
  searchResult,
  isSearching,
  error,
  onRunAnalysis,
  segments,
}: FoundRecordsTabProps) {
  // Group matches by turn_index
  const matchesByTurn = React.useMemo(() => {
    if (!searchResult?.matches) return new Map<number, DictMatch[]>();
    const map = new Map<number, DictMatch[]>();
    for (const match of searchResult.matches) {
      const existing = map.get(match.turn_index) ?? [];
      existing.push(match);
      map.set(match.turn_index, existing);
    }
    return map;
  }, [searchResult]);

  // Get segments that have matches
  const matchedSegments = React.useMemo(() => {
    return segments.filter((seg) => matchesByTurn.has(seg.turn_index));
  }, [segments, matchesByTurn]);

  // No search started
  if (!searchResult && !isSearching && !error) {
    return (
      <Box className="found-records-tab found-records-tab--empty" padding="x6">
        <Stack direction="vertical" spacing="x3" align="center">
          <Icon iconName={Icons.Search} size="large" />
          <Typography variant="body1" inactive>
            Запустите анализ для поиска фраз в диалогах
          </Typography>
          <Button variant="primary" onClick={onRunAnalysis}>
            Найти
          </Button>
        </Stack>
      </Box>
    );
  }

  // Loading
  if (isSearching) {
    return (
      <Box className="found-records-tab" padding="x6">
        <Stack direction="vertical" spacing="x4" align="center">
          <Progress shape="circle" cycled />
          <Typography variant="body2" inactive>
            Поиск фраз...
          </Typography>
        </Stack>
      </Box>
    );
  }

  // Error
  if (error) {
    return (
      <Box className="found-records-tab" padding="x4">
        <Typography variant="body2" style={{ color: 'var(--color-status-error, #d32f2f)' }}>
          Ошибка: {error}
        </Typography>
        <Button variant="secondary" onClick={onRunAnalysis} style={{ marginTop: '8px' }}>
          Повторить
        </Button>
      </Box>
    );
  }

  // Empty results
  if (searchResult && matchedSegments.length === 0) {
    return (
      <Box className="found-records-tab found-records-tab--empty" padding="x6">
        <Stack direction="vertical" spacing="x3" align="center">
          <Icon iconName={Icons.Search} size="large" />
          <Typography variant="body1" inactive>
            Фразы не найдены в загруженных диалогах
          </Typography>
        </Stack>
      </Box>
    );
  }

  // Loaded with results
  return (
    <Box className="found-records-tab" padding="x4">
      <Typography variant="body2" inactive style={{ marginBottom: '12px' }}>
        Найдено: {searchResult?.total_matches ?? 0} совпадений в {matchedSegments.length} сегментах
      </Typography>
      <Stack direction="vertical" spacing="x2">
        {matchedSegments.map((segment) => (
          <RecordCard
            key={segment.turn_index}
            segment={segment}
            matches={matchesByTurn.get(segment.turn_index) ?? []}
          />
        ))}
      </Stack>
    </Box>
  );
}
