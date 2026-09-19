/**
 * Tests for HighlightRenderer — core highlight algorithm.
 * Covers: plain text, single match, multiple matches, overlapping matches,
 * no matches, innermost color, level classes, accessibility attributes.
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import HighlightRenderer from './HighlightRenderer';
import type { DictMatch } from '../types/api';
import { HoverContextWrapper } from '../test/HoverContextWrapper';

// ─── Helpers ──────────────────────────────────────────────

function makeMatch(overrides: Partial<DictMatch> & { phrase_text: string }): DictMatch {
  return {
    matched_text: overrides.matched_text ?? overrides.phrase_text,
    matched_start: overrides.matched_start ?? -1,
    matched_end: overrides.matched_end ?? -1,
    turn_index: 0,
    speaker: 'Клиент',
    match_type: 'morph_bow',
    word_distance_used: 1,
    quarter: 'Словарь',
    cascade_order: 1,
    is_exact_match: true,
    channel_constraint: undefined,
    word_distance: undefined,
    ...overrides,
  };
}

/** Render with HoverContextWrapper so useHoverContext() works */
function renderWithHover(ui: React.ReactElement) {
  return render(ui, { wrapper: HoverContextWrapper });
}

// ─── Tests ────────────────────────────────────────────────

describe('HighlightRenderer', () => {
  it('renders plain text with no matches', () => {
    const { container } = renderWithHover(
      <HighlightRenderer
        text="Привет, мир!"
        matches={[]}
      />,
    );

    expect(container.querySelector('.segment-text')).toBeTruthy();
    // No highlight spans
    expect(container.querySelector('.highlight-match')).toBeNull();
  });

  it('renders a single highlighted match', () => {
    const text = 'Клиент хочет расторгнуть договор';
    const matches = [makeMatch({ phrase_text: 'расторгнуть договор', matched_text: 'расторгнуть договор', word_distance_used: 1 })];

    const { container } = renderWithHover(
      <HighlightRenderer text={text} matches={matches} />,
    );

    const highlight = container.querySelector('.highlight-match');
    expect(highlight).toBeTruthy();
    // DR-1: NO quotes in text display — quotes only in dictionary sidebar
    expect(highlight?.textContent).toBe('расторгнуть договор');
    expect(highlight?.classList.contains('highlight-depth-1')).toBe(true);
  });

  it('applies innermost level class for single match', () => {
    const text = 'Привет мир';
    const matches = [makeMatch({ phrase_text: 'мир', word_distance_used: 1, cascade_order: 2 })];

    const { container } = renderWithHover(
      <HighlightRenderer text={text} matches={matches} />,
    );

    const highlight = container.querySelector('.highlight-match');
    // Level comes from cascade_order → depth, not word_distance_used
    expect(highlight?.classList.contains('highlight-depth-2')).toBe(true);
  });

  it('renders multiple non-overlapping matches', () => {
    const text = 'клиент хочет расторгнуть и уйти';
    const matches = [
      makeMatch({ phrase_text: 'хочет', word_distance_used: 1, turn_index: 0 }),
      makeMatch({ phrase_text: 'уйти', word_distance_used: 2, turn_index: 0 }),
    ];

    const { container } = renderWithHover(
      <HighlightRenderer text={text} matches={matches} />,
    );

    const highlights = container.querySelectorAll('.highlight-match');
    expect(highlights).toHaveLength(2);
    // DR-1: NO quotes in text display — quotes only in dictionary sidebar
    expect(highlights[0].textContent).toBe('хочет');
    expect(highlights[1].textContent).toBe('уйти');
  });

  it('handles overlapping matches with different cascade_order levels', () => {
    const text = 'я хочу расторгнуть договор сейчас';
    const matches = [
      makeMatch({ phrase_text: 'расторгнуть договор', word_distance_used: 1, cascade_order: 1, turn_index: 0 }),
      makeMatch({ phrase_text: 'расторгнуть договор сейчас', word_distance_used: 2, cascade_order: 2, turn_index: 0 }),
    ];

    const { container } = renderWithHover(
      <HighlightRenderer text={text} matches={matches} />,
    );

    const highlights = container.querySelectorAll('.highlight-match');
    // Overlapping text splits into boundary chunks
    expect(highlights.length).toBeGreaterThanOrEqual(2);
  });

  it('ignores matches whose phrase is not in text', () => {
    const text = 'Привет мир';
    const matches = [makeMatch({ phrase_text: 'несуществующая фраза', word_distance_used: 1 })];

    const { container } = renderWithHover(
      <HighlightRenderer text={text} matches={matches} />,
    );

    expect(container.querySelector('.highlight-match')).toBeNull();
  });

  it('uses cascade_order for level class, not word_distance_used', () => {
    const text = 'тестовая фраза';
    const matches = [makeMatch({ phrase_text: 'фраза', word_distance_used: 5, cascade_order: 3, quarter: 'Неизвестный словарь' })];

    const { container } = renderWithHover(
      <HighlightRenderer text={text} matches={matches} />,
    );

    const highlight = container.querySelector('.highlight-match');
    expect(highlight).toBeTruthy();
    // Level comes from cascade_order (depth), not from word_distance_used
    expect(highlight?.classList.contains('highlight-depth-3')).toBe(true);
  });

  it('uses semantic <mark> element for highlighted text', () => {
    const text = 'важный текст';
    const matches = [makeMatch({ phrase_text: 'важный', word_distance_used: 1 })];

    renderWithHover(
      <HighlightRenderer text={text} matches={matches} />,
    );

    const mark = screen.getByRole('mark');
    expect(mark).toBeTruthy();
    // DR-1: NO quotes in text display
    expect(mark.textContent).toBe('важный');
  });

  it('adds aria-label with phrase and depth', () => {
    const text = 'важный текст';
    const matches = [makeMatch({ phrase_text: 'важный', word_distance_used: 1, cascade_order: 2 })];

    renderWithHover(
      <HighlightRenderer text={text} matches={matches} />,
    );

    const mark = screen.getByRole('mark');
    expect(mark.getAttribute('aria-label')).toContain('важный');
    expect(mark.getAttribute('aria-label')).toContain('глубина 2');
  });

  it('makes highlighted spans keyboard-focusable', () => {
    const text = 'фраза здесь';
    const matches = [makeMatch({ phrase_text: 'фраза', word_distance_used: 1 })];

    renderWithHover(
      <HighlightRenderer text={text} matches={matches} />,
    );

    const mark = screen.getByRole('mark');
    expect(mark.getAttribute('tabIndex')).toBe('0');
  });

  it('renders empty text without crashing', () => {
    const { container } = renderWithHover(
      <HighlightRenderer text="" matches={[]} />,
    );

    expect(container.querySelector('.segment-text')).toBeTruthy();
    expect(container.querySelector('.highlight-match')).toBeNull();
  });

  it('handles match at the beginning of text', () => {
    const text = 'стартовая фраза';
    const matches = [makeMatch({ phrase_text: 'стартовая', word_distance_used: 1 })];

    const { container } = renderWithHover(
      <HighlightRenderer text={text} matches={matches} />,
    );

    const highlight = container.querySelector('.highlight-match');
    // DR-1: NO quotes in text display
    expect(highlight?.textContent).toBe('стартовая');
  });

  it('handles match at the end of text', () => {
    const text = 'конечная фраза';
    const matches = [makeMatch({ phrase_text: 'фраза', word_distance_used: 1 })];

    const { container } = renderWithHover(
      <HighlightRenderer text={text} matches={matches} />,
    );

    const highlight = container.querySelector('.highlight-match');
    // DR-1: NO quotes in text display
    expect(highlight?.textContent).toBe('фраза');
  });

  it('matches only first occurrence of phrase', () => {
    const text = 'договор договор ещё договор';
    const matches = [makeMatch({ phrase_text: 'договор', matched_text: 'договор', word_distance_used: 1 })];

    const { container } = renderWithHover(
      <HighlightRenderer text={text} matches={matches} />,
    );

    const highlights = container.querySelectorAll('.highlight-match');
    // Only first "договор" should be highlighted
    expect(highlights).toHaveLength(1);
    // DR-1: NO quotes in text display
    expect(highlights[0].textContent).toBe('договор');
  });

  it('highlights matched_text when different from phrase_text (morph match)', () => {
    // "я я ничего не подключил хотел бы вернуть средства обратно"
    // "не подключил хотел" starts at char 11, ends at char 29 (exclusive end = 29)
    const text = 'я я ничего не подключил хотел бы вернуть средства обратно';
    const matches = [makeMatch({
      phrase_text: 'не хочу подключать',
      matched_text: 'не подключил хотел',
      matched_start: 11,
      matched_end: 29,
      word_distance_used: 1,
    })];

    const { container } = renderWithHover(
      <HighlightRenderer text={text} matches={matches} />,
    );

    const highlight = container.querySelector('.highlight-match');
    expect(highlight).toBeTruthy();
    // DR-1: NO quotes in text display — quotes only in dictionary sidebar
    expect(highlight?.textContent).toBe('не подключил хотел');
  });

  it('uses character offsets for exact positioning', () => {
    // "просто лёха уйду на другого оператора" (length=37)
    // "уйду на другого оператора" starts at char 12, ends at char 37
    const text = 'просто лёха уйду на другого оператора';
    const matches = [makeMatch({
      phrase_text: 'уйду другому оператору',
      matched_text: 'уйду на другого оператора',
      matched_start: 12,
      matched_end: 37,
      word_distance_used: 1,
    })];

    const { container } = renderWithHover(
      <HighlightRenderer text={text} matches={matches} />,
    );

    const highlight = container.querySelector('.highlight-match');
    expect(highlight).toBeTruthy();
    // DR-1: NO quotes in text display
    expect(highlight?.textContent).toBe('уйду на другого оператора');
  });

  it('does not add highlight-hovered class when no phrase is hovered', () => {
    const text = 'тестовая фраза';
    const matches = [makeMatch({ phrase_text: 'фраза', word_distance_used: 1 })];

    const { container } = renderWithHover(
      <HighlightRenderer text={text} matches={matches} />,
    );

    const highlight = container.querySelector('.highlight-match');
    expect(highlight).toBeTruthy();
    expect(highlight?.classList.contains('highlight-hovered')).toBe(false);
  });

  it('adds data-phrase attribute to mark elements', () => {
    const text = 'тестовая фраза';
    const matches = [makeMatch({ phrase_text: 'фраза', word_distance_used: 1 })];

    const { container } = renderWithHover(
      <HighlightRenderer text={text} matches={matches} />,
    );

    const mark = container.querySelector('mark');
    expect(mark).toBeTruthy();
    expect(mark?.getAttribute('data-phrase')).toBe('фраза');
  });

  // ═══════════════════════════════════════════════════════════
  // DR-1 / DR-2 / DR-3 tests (Chunk 1)
  // ═══════════════════════════════════════════════════════════

  it('DR-1: exact match has highlight-exact class (no quotes in text)', () => {
    const text = 'клиент хочет расторгнуть';
    const matches = [makeMatch({
      phrase_text: 'хочет',
      word_distance_used: 1,
      is_exact_match: true,
    })];

    const { container } = renderWithHover(
      <HighlightRenderer text={text} matches={matches} />,
    );

    const highlight = container.querySelector('.highlight-match');
    // DR-1: NO quotes in highlighted text — quotes only in dictionary sidebar
    expect(highlight?.textContent).toBe('хочет');
    expect(highlight?.classList.contains('highlight-exact')).toBe(true);
  });

  it('DR-1: does NOT wrap non-exact match in quotes', () => {
    const text = 'клиент хочет расторгнуть';
    const matches = [makeMatch({
      phrase_text: 'хочет',
      word_distance_used: 1,
      is_exact_match: false,
    })];

    const { container } = renderWithHover(
      <HighlightRenderer text={text} matches={matches} />,
    );

    const highlight = container.querySelector('.highlight-match');
    expect(highlight?.textContent).toBe('хочет');
    expect(highlight?.classList.contains('highlight-exact')).toBe(false);
  });

  it('IP-1.5 regression: overlapping exact + morph matches keep highlight-exact', () => {
    // Same phrase matched twice on the same turn: exact (quoted) and
    // morphological (unquoted). Both cover the identical span. The morph
    // match comes LAST in the array — before the 2026-09-19 fix it silently
    // replaced the exact match and dropped the DR-1 highlight-exact class.
    const text = 'Я хочу расторгнуть договор с вашей компанией.';
    const start = text.indexOf('расторгнуть');
    const end = start + 'расторгнуть договор'.length;
    const matches = [
      makeMatch({
        phrase_text: 'расторгнуть договор',
        matched_text: 'расторгнуть договор',
        matched_start: start,
        matched_end: end,
        is_exact_match: true,
        match_type: 'exact_bow',
      }),
      makeMatch({
        phrase_text: 'расторгнуть договор',
        matched_text: 'расторгнуть договор',
        matched_start: start,
        matched_end: end,
        is_exact_match: false,
        match_type: 'morph_bow',
      }),
    ];

    const { container } = renderWithHover(
      <HighlightRenderer text={text} matches={matches} />,
    );

    const highlight = container.querySelector('.highlight-match');
    expect(highlight).toBeTruthy();
    expect(highlight?.textContent).toBe('расторгнуть договор');
    expect(highlight?.classList.contains('highlight-exact')).toBe(true);
  });

  it('DR-2: applies fontWeight 600 when word_distance is 0', () => {
    const text = 'клиент хочет расторгнуть';
    const matches = [makeMatch({
      phrase_text: 'хочет',
      word_distance_used: 1,
      is_exact_match: false,
      word_distance: 0,
    })];

    const { container } = renderWithHover(
      <HighlightRenderer text={text} matches={matches} />,
    );

    const highlight = container.querySelector('.highlight-match');
    expect(highlight).toBeTruthy();
    expect((highlight as HTMLElement)?.style.fontWeight).toBe('600');
    expect(highlight?.classList.contains('highlight-adjacent')).toBe(true);
  });

  it('DR-2: does NOT apply bold when word_distance > 0', () => {
    const text = 'клиент хочет расторгнуть';
    const matches = [makeMatch({
      phrase_text: 'хочет',
      word_distance_used: 1,
      is_exact_match: false,
      word_distance: 2,
    })];

    const { container } = renderWithHover(
      <HighlightRenderer text={text} matches={matches} />,
    );

    const highlight = container.querySelector('.highlight-match');
    expect(highlight).toBeTruthy();
    expect((highlight as HTMLElement)?.style.fontWeight).toBeFalsy();
  });

  it('DR-3: applies CLIENT channel color', () => {
    const text = 'клиент хочет расторгнуть';
    const matches = [makeMatch({
      phrase_text: 'хочет',
      word_distance_used: 1,
      is_exact_match: false,
      channel_constraint: 'CLIENT',
    })];

    const { container } = renderWithHover(
      <HighlightRenderer text={text} matches={matches} />,
    );

    const highlight = container.querySelector('.highlight-match');
    expect(highlight).toBeTruthy();
    expect(highlight?.classList.contains('highlight-channel-client')).toBe(true);
    expect((highlight as HTMLElement)?.style.color).toContain('dict-channel-client');
  });

  it('DR-3: applies OPERATOR channel color', () => {
    const text = 'сотрудник хочет помочь';
    const matches = [makeMatch({
      phrase_text: 'хочет',
      word_distance_used: 1,
      is_exact_match: false,
      channel_constraint: 'OPERATOR',
    })];

    const { container } = renderWithHover(
      <HighlightRenderer text={text} matches={matches} />,
    );

    const highlight = container.querySelector('.highlight-match');
    expect(highlight?.classList.contains('highlight-channel-operator')).toBe(true);
  });

  it('DR-3: ANY channel does not apply special color class', () => {
    const text = 'клиент хочет расторгнуть';
    const matches = [makeMatch({
      phrase_text: 'хочет',
      word_distance_used: 1,
      is_exact_match: false,
      channel_constraint: 'ANY',
    })];

    const { container } = renderWithHover(
      <HighlightRenderer text={text} matches={matches} />,
    );

    const highlight = container.querySelector('.highlight-match');
    expect(highlight?.classList.contains('highlight-channel-client')).toBe(false);
    expect(highlight?.classList.contains('highlight-channel-operator')).toBe(false);
  });

  it('DR-1+DR-2+DR-3 combine: exact + adjacent + channel', () => {
    const text = 'клиент хочет расторгнуть';
    const matches = [makeMatch({
      phrase_text: 'хочет',
      word_distance_used: 1,
      is_exact_match: true,
      word_distance: 0,
      channel_constraint: 'CLIENT',
    })];

    const { container } = renderWithHover(
      <HighlightRenderer text={text} matches={matches} />,
    );

    const highlight = container.querySelector('.highlight-match');
    expect(highlight).toBeTruthy();
    // DR-1: NO quotes in text display
    expect(highlight?.textContent).toBe('хочет');
    expect(highlight?.classList.contains('highlight-exact')).toBe(true);
    // DR-2: bold
    expect((highlight as HTMLElement)?.style.fontWeight).toBe('600');
    expect(highlight?.classList.contains('highlight-adjacent')).toBe(true);
    // DR-3: channel color
    expect(highlight?.classList.contains('highlight-channel-client')).toBe(true);
  });
});
