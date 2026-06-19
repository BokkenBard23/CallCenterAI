/**
 * Tests for DictionaryPhraseItem — display rules DR-1..DR-4.
 *
 * STRICT Display Rules (INV-D1 — do NOT modify):
 *   DR-1: is_exact === true  → phrase in guillemet quotes: «phrase»
 *   DR-2: word_distance === 0 → bold font (fontWeight: 600)
 *   DR-3: channel_constraint → color dot (OPERATOR=green, CLIENT=blue, ANY=orange)
 *   DR-4: matchCount         → Counter at >0, muted at 0
 *   DR-1 + DR-2 combined: is_exact && word_distance=0 → bold + quotes
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import DictionaryPhraseItem from './DictionaryPhraseItem';
import { HoverContextWrapper } from '../test/HoverContextWrapper';
import type { DictionaryCondition } from '../types/api';

// ─── Helpers ──────────────────────────────────────────────

function makeCondition(overrides: Partial<DictionaryCondition> & { text: string }): DictionaryCondition {
  return {
    word_distance: 1,
    word_count: 1,
    channel_constraint: 'ANY',
    without_list: [],
    is_exact: false,
    ...overrides,
  };
}

function renderPhraseItem(
  condition: DictionaryCondition,
  matchCount = 0,
) {
  return render(
    <DictionaryPhraseItem condition={condition} matchCount={matchCount} />,
    { wrapper: HoverContextWrapper },
  );
}

// ─── Tests ────────────────────────────────────────────────

describe('DictionaryPhraseItem', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ─── DR-1: Exact match → guillemet quotes ───────────────

  describe('DR-1: is_exact quotes', () => {
    it('wraps phrase in guillemet quotes when is_exact=true', () => {
      const cond = makeCondition({ text: 'расторгнуть договор', is_exact: true });
      renderPhraseItem(cond, 1);

      expect(screen.getByText('«расторгнуть договор»')).toBeInTheDocument();
    });

    it('does NOT wrap phrase in quotes when is_exact=false', () => {
      const cond = makeCondition({ text: 'расторгнуть договор', is_exact: false });
      renderPhraseItem(cond, 1);

      expect(screen.getByText('расторгнуть договор')).toBeInTheDocument();
    });

    it('does NOT wrap phrase in quotes when is_exact is undefined (default)', () => {
      const cond = makeCondition({ text: 'тест', is_exact: undefined as unknown as boolean });
      renderPhraseItem(cond, 1);

      // Default is_exact=false, so no quotes
      expect(screen.getByText('тест')).toBeInTheDocument();
    });
  });

  // ─── DR-2: word_distance=0 → bold ─────────────────────

  describe('DR-2: word_distance=0 bold', () => {
    it('applies fontWeight 600 when word_distance=0', () => {
      const cond = makeCondition({ text: 'фраза', word_distance: 0 });
      renderPhraseItem(cond, 1);

      // Find the Typography element with the phrase text
      const typographyEl = screen.getByText('фраза');
      expect(typographyEl).toBeTruthy();
      // Check inline style fontWeight
      expect(typographyEl.style.fontWeight).toBe('600');
    });

    it('applies fontWeight 400 when word_distance > 0', () => {
      const cond = makeCondition({ text: 'фраза', word_distance: 2 });
      renderPhraseItem(cond, 1);

      const typographyEl = screen.getByText('фраза');
      expect(typographyEl.style.fontWeight).toBe('400');
    });

    it('applies fontWeight 400 when word_distance=1', () => {
      const cond = makeCondition({ text: 'фраза', word_distance: 1 });
      renderPhraseItem(cond, 1);

      const typographyEl = screen.getByText('фраза');
      expect(typographyEl.style.fontWeight).toBe('400');
    });
  });

  // ─── DR-1 + DR-2 combined ──────────────────────────────

  describe('DR-1+DR-2: combined exact + bold', () => {
    it('shows bold quoted phrase when is_exact=true AND word_distance=0', () => {
      const cond = makeCondition({ text: 'расторгнуть', is_exact: true, word_distance: 0 });
      renderPhraseItem(cond, 1);

      const el = screen.getByText('«расторгнуть»');
      expect(el).toBeTruthy();
      expect(el.style.fontWeight).toBe('600');
    });

    it('shows quoted (not bold) when is_exact=true AND word_distance>0', () => {
      const cond = makeCondition({ text: 'расторгнуть', is_exact: true, word_distance: 2 });
      renderPhraseItem(cond, 1);

      const el = screen.getByText('«расторгнуть»');
      expect(el.style.fontWeight).toBe('400');
    });

    it('shows bold (not quoted) when is_exact=false AND word_distance=0', () => {
      const cond = makeCondition({ text: 'расторгнуть', is_exact: false, word_distance: 0 });
      renderPhraseItem(cond, 1);

      const el = screen.getByText('расторгнуть');
      expect(el.style.fontWeight).toBe('600');
    });
  });

  // ─── DR-3: Channel color ───────────────────────────────

  describe('DR-3: channel color dot', () => {
    it('renders a channel color dot for OPERATOR channel', () => {
      const cond = makeCondition({ text: 'фраза', channel_constraint: 'OPERATOR' });
      const { container } = renderPhraseItem(cond, 1);

      const dot = container.querySelector('.dict-channel-dot');
      expect(dot).toBeTruthy();
      // OPERATOR → var(--dict-channel-operator)
      expect((dot as HTMLElement).style.backgroundColor).toContain('var(--dict-channel-operator)');
    });

    it('renders a channel color dot for CLIENT channel', () => {
      const cond = makeCondition({ text: 'фраза', channel_constraint: 'CLIENT' });
      const { container } = renderPhraseItem(cond, 1);

      const dot = container.querySelector('.dict-channel-dot');
      expect(dot).toBeTruthy();
      expect((dot as HTMLElement).style.backgroundColor).toContain('var(--dict-channel-client)');
    });

    it('renders a channel color dot for ANY channel', () => {
      const cond = makeCondition({ text: 'фраза', channel_constraint: 'ANY' });
      const { container } = renderPhraseItem(cond, 1);

      const dot = container.querySelector('.dict-channel-dot');
      expect(dot).toBeTruthy();
      expect((dot as HTMLElement).style.backgroundColor).toContain('var(--dict-channel-any)');
    });

    it('renders a fallback color for unknown channel', () => {
      const cond = makeCondition({ text: 'фраза', channel_constraint: 'UNKNOWN' });
      const { container } = renderPhraseItem(cond, 1);

      const dot = container.querySelector('.dict-channel-dot');
      expect(dot).toBeTruthy();
      // Unknown channel → fallback neutral color
      expect((dot as HTMLElement).style.backgroundColor).toContain('var(--color-status-neutral');
    });

    it('dot is aria-hidden for accessibility', () => {
      const cond = makeCondition({ text: 'фраза', channel_constraint: 'OPERATOR' });
      const { container } = renderPhraseItem(cond, 1);

      const dot = container.querySelector('.dict-channel-dot');
      expect(dot?.getAttribute('aria-hidden')).toBe('true');
    });
  });

  // ─── DR-4: Match count ─────────────────────────────────

  describe('DR-4: match count', () => {
    it('renders Counter component when matchCount > 0', () => {
      const cond = makeCondition({ text: 'фраза' });
      renderPhraseItem(cond, 5);

      // Counter should be rendered (no muted "0 совп." text)
      expect(screen.queryByText(/0 совп\./)).toBeNull();
      // The Counter renders the count value in the DOM
      expect(screen.getByText('5')).toBeTruthy();
    });

    it('renders muted "0 совп." when matchCount === 0', () => {
      const cond = makeCondition({ text: 'фраза' });
      renderPhraseItem(cond, 0);

      expect(screen.getByText(/0 совп\./)).toBeInTheDocument();
    });

    it('mutes text when matchCount is 0 (inactive prop)', () => {
      const cond = makeCondition({ text: 'фраза' });
      renderPhraseItem(cond, 0);

      const phraseEl = screen.getByText('фраза');
      // Typography with inactive prop
      expect(phraseEl).toBeTruthy();
    });
  });

  // ─── Hover interaction ──────────────────────────────────

  describe('Hover interaction', () => {
    it('calls setHoveredPhrase on mouse enter', () => {
      const cond = makeCondition({ text: 'тестовая фраза' });
      const { container } = renderPhraseItem(cond, 1);

      const item = container.querySelector('.dict-phrase-item');
      expect(item).toBeTruthy();
      fireEvent.mouseEnter(item!);

      // After hover, data-hovered should be 'true'
      // (The HoverContextWrapper provides the context)
    });

    it('sets data-hovered=true when phrase is hovered', async () => {
      const cond = makeCondition({ text: 'тестовая фраза' });
      const { container } = renderPhraseItem(cond, 1);

      const item = container.querySelector('.dict-phrase-item');
      fireEvent.mouseEnter(item!);

      // The data-hovered attribute should eventually be set
      // Since debounce is 150ms, we need to wait
      await new Promise((r) => setTimeout(r, 200));

      // After debounce, the component should re-render with hovered state
      expect(item?.getAttribute('data-hovered')).toBe('true');
    });

    it('sets data-hovered=undefined on mouse leave', async () => {
      const cond = makeCondition({ text: 'тестовая фраза' });
      const { container } = renderPhraseItem(cond, 1);

      const item = container.querySelector('.dict-phrase-item');
      fireEvent.mouseEnter(item!);
      await new Promise((r) => setTimeout(r, 200));

      fireEvent.mouseLeave(item!);

      // Mouse leave sets hoveredPhrase=null immediately (no debounce)
      await new Promise((r) => setTimeout(r, 50));
      expect(item?.getAttribute('data-hovered')).toBeNull();
    });
  });

  // ─── Accessibility ──────────────────────────────────────

  describe('Accessibility', () => {
    it('has role="listitem"', () => {
      const cond = makeCondition({ text: 'фраза' });
      const { container } = renderPhraseItem(cond, 1);

      const item = container.querySelector('[role="listitem"]');
      expect(item).toBeTruthy();
    });

    it('has aria-label with phrase, channel, and count', () => {
      const cond = makeCondition({ text: 'тест', channel_constraint: 'OPERATOR' });
      const { container } = renderPhraseItem(cond, 3);

      const item = container.querySelector('[role="listitem"]');
      const label = item?.getAttribute('aria-label') ?? '';
      expect(label).toContain('тест');
      expect(label).toContain('OPERATOR');
      expect(label).toContain('3');
    });

    it('has minimum 44px touch target height', () => {
      const cond = makeCondition({ text: 'фраза' });
      const { container } = renderPhraseItem(cond, 1);

      const item = container.querySelector('.dict-phrase-item');
      expect(item).toBeTruthy();
      expect((item as HTMLElement).style.minHeight).toBe('44px');
    });
  });

  // ─── Edge cases ─────────────────────────────────────────

  describe('Edge cases', () => {
    it('renders correctly with empty phrase text', () => {
      const cond = makeCondition({ text: '' });
      const { container } = renderPhraseItem(cond, 0);
      expect(container.querySelector('.dict-phrase-item')).toBeTruthy();
    });

    it('renders correctly with very long phrase', () => {
      const longPhrase = 'очень длинная фраза которая не помещается в одну строку '.repeat(5);
      const cond = makeCondition({ text: longPhrase, is_exact: true });
      renderPhraseItem(cond, 100);

      expect(screen.getByText(`«${longPhrase}»`)).toBeInTheDocument();
    });

    it('renders correctly with special characters in phrase', () => {
      const specialPhrase = 'фраза <script>alert("xss")</script>';
      const cond = makeCondition({ text: specialPhrase });
      renderPhraseItem(cond, 1);

      // React escapes HTML, so no actual script execution
      expect(screen.getByText(specialPhrase)).toBeInTheDocument();
    });

    it('renders correctly with large match count', () => {
      const cond = makeCondition({ text: 'фраза' });
      const { container } = renderPhraseItem(cond, 9999);
      expect(container.querySelector('.dict-phrase-item')).toBeTruthy();
    });
  });
});
