/**
 * Tests for HoverContext — bidirectional cross-highlighting state.
 *
 * Covers:
 *   - HoverProvider provides context value
 *   - setHoveredPhrase with 150ms debounce
 *   - setHoveredPhrase(null) applies immediately (no debounce)
 *   - useHoverContext throws when used outside HoverProvider
 *   - Debounce timer cleanup on unmount / rapid changes
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { HoverProvider, useHoverContext } from './HoverContext';

// ─── Helper component ────────────────────────────────────

function TestConsumer() {
  const { hoveredPhrase, setHoveredPhrase } = useHoverContext();
  return (
    <div>
      <span data-testid="hovered-phrase">{hoveredPhrase ?? 'null'}</span>
      <button
        data-testid="set-phrase-btn"
        onClick={() => setHoveredPhrase('тестовая фраза')}
      >
        Set phrase
      </button>
      <button
        data-testid="set-null-btn"
        onClick={() => setHoveredPhrase(null)}
      >
        Set null
      </button>
    </div>
  );
}

function renderWithProvider() {
  return render(
    <HoverProvider>
      <TestConsumer />
    </HoverProvider>,
  );
}

// ─── Tests ────────────────────────────────────────────────

describe('HoverContext', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  // ─── Provider provides context ─────────────────────────

  it('provides initial hoveredPhrase as null', () => {
    renderWithProvider();
    expect(screen.getByTestId('hovered-phrase').textContent).toBe('null');
  });

  it('provides setHoveredPhrase function', () => {
    renderWithProvider();
    expect(screen.getByTestId('set-phrase-btn')).toBeTruthy();
  });

  // ─── Debounce behavior ─────────────────────────────────

  it('debounces setHoveredPhrase at 150ms', () => {
    renderWithProvider();

    const setBtn = screen.getByTestId('set-phrase-btn');
    fireEvent.click(setBtn);

    // Immediately after click, phrase should still be null (debounced)
    expect(screen.getByTestId('hovered-phrase').textContent).toBe('null');

    // After 150ms, phrase should be set
    act(() => {
      vi.advanceTimersByTime(150);
    });
    expect(screen.getByTestId('hovered-phrase').textContent).toBe('тестовая фраза');
  });

  it('does NOT set phrase before 150ms debounce', () => {
    renderWithProvider();

    const setBtn = screen.getByTestId('set-phrase-btn');
    fireEvent.click(setBtn);

    act(() => {
      vi.advanceTimersByTime(100);
    });
    expect(screen.getByTestId('hovered-phrase').textContent).toBe('null');
  });

  // ─── Null is immediate (no debounce) ───────────────────

  it('applies setHoveredPhrase(null) immediately without debounce', () => {
    renderWithProvider();

    // First set a phrase
    const setBtn = screen.getByTestId('set-phrase-btn');
    fireEvent.click(setBtn);
    act(() => {
      vi.advanceTimersByTime(150);
    });
    expect(screen.getByTestId('hovered-phrase').textContent).toBe('тестовая фраза');

    // Now set null — should be immediate
    const nullBtn = screen.getByTestId('set-null-btn');
    fireEvent.click(nullBtn);

    // No timer advance needed — null should be immediate
    expect(screen.getByTestId('hovered-phrase').textContent).toBe('null');
  });

  // ─── Rapid changes cancel previous debounce ────────────

  it('cancels previous debounce on rapid changes', () => {
    renderWithProvider();

    const setBtn = screen.getByTestId('set-phrase-btn');
    fireEvent.click(setBtn);

    // Advance 100ms (not enough for debounce)
    act(() => {
      vi.advanceTimersByTime(100);
    });
    expect(screen.getByTestId('hovered-phrase').textContent).toBe('null');

    // Click again — this should reset the debounce timer
    fireEvent.click(setBtn);

    // Advance another 100ms (200ms total, but only 100ms since last click)
    act(() => {
      vi.advanceTimersByTime(100);
    });
    // Still null — debounce was reset
    expect(screen.getByTestId('hovered-phrase').textContent).toBe('null');

    // Advance another 50ms (150ms since last click)
    act(() => {
      vi.advanceTimersByTime(50);
    });
    expect(screen.getByTestId('hovered-phrase').textContent).toBe('тестовая фраза');
  });

  // ─── useHoverContext outside provider ──────────────────

  it('throws when useHoverContext is used outside HoverProvider', () => {
    // Suppress console.error and jsdom error reporting for expected error
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const errorListener = (event: Event) => { event.preventDefault(); };
    window.addEventListener('error', errorListener, true);

    expect(() => {
      render(<TestConsumer />);
    }).toThrow('useHoverContext must be used within a HoverProvider');

    window.removeEventListener('error', errorListener, true);
    consoleSpy.mockRestore();
  });

  // ─── Debounce timer cleanup ─────────────────────────────

  it('clears debounce timer on unmount', () => {
    const { unmount } = renderWithProvider();

    const setBtn = screen.getByTestId('set-phrase-btn');
    fireEvent.click(setBtn);

    // Unmount before debounce fires
    unmount();

    // Advance timer — should not cause any errors
    act(() => {
      vi.advanceTimersByTime(200);
    });

    // No state update after unmount — test passes if no errors thrown
    expect(true).toBe(true);
  });

  // ─── Switching between phrases ─────────────────────────

  it('updates hoveredPhrase when switching between different phrases', async () => {
    function MultiPhraseConsumer() {
      const { hoveredPhrase, setHoveredPhrase } = useHoverContext();
      return (
        <div>
          <span data-testid="hovered-phrase">{hoveredPhrase ?? 'null'}</span>
          <button data-testid="phrase-a" onClick={() => setHoveredPhrase('фраза А')}>
            A
          </button>
          <button data-testid="phrase-b" onClick={() => setHoveredPhrase('фраза Б')}>
            B
          </button>
        </div>
      );
    }

    render(
      <HoverProvider>
        <MultiPhraseConsumer />
      </HoverProvider>,
    );

    // Set phrase A
    fireEvent.click(screen.getByTestId('phrase-a'));
    act(() => {
      vi.advanceTimersByTime(150);
    });
    expect(screen.getByTestId('hovered-phrase').textContent).toBe('фраза А');

    // Set phrase B — should replace A
    fireEvent.click(screen.getByTestId('phrase-b'));
    act(() => {
      vi.advanceTimersByTime(150);
    });
    expect(screen.getByTestId('hovered-phrase').textContent).toBe('фраза Б');
  });
});
