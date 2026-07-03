/**
 * Tests for TypingAnimation component.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import { TypingAnimation } from './typing-animation';

// Mock motion/react
vi.mock('motion/react', () => ({
  motion: {
    span: ({ children, ...props }: React.PropsWithChildren<Record<string, unknown>>) => <span {...props}>{children}</span>,
    div: ({ children, ...props }: React.PropsWithChildren<Record<string, unknown>>) => <div {...props}>{children}</div>,
  },
  AnimatePresence: ({ children }: React.PropsWithChildren) => <>{children}</>,
}));

describe('TypingAnimation', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders the component without crashing', () => {
    const { container } = render(<TypingAnimation text="Hello" speed={0} />);
    // Should render a span element (the wrapper)
    expect(container.querySelector('span')).toBeInTheDocument();
  });

  it('displays text progressively with timer', () => {
    render(<TypingAnimation text="Hi" speed={50} startOnView={false} />);

    // Initially no characters shown (displayedLength starts at 0)
    // Advance timers to trigger first character
    act(() => {
      vi.advanceTimersByTime(100);
    });

    // After advancing timers, at least the first char should be typed
    expect(screen.getByText(/H/)).toBeInTheDocument();
  });

  it('calls onComplete when typing finishes', () => {
    const onComplete = vi.fn();
    render(<TypingAnimation text="Hi" speed={0} startOnView={false} onComplete={onComplete} />);

    act(() => {
      vi.advanceTimersByTime(100);
    });

    expect(onComplete).toHaveBeenCalled();
  });

  it('handles empty text', () => {
    const onComplete = vi.fn();
    render(<TypingAnimation text="" speed={0} startOnView={false} onComplete={onComplete} />);

    act(() => {
      vi.advanceTimersByTime(100);
    });

    expect(onComplete).toHaveBeenCalled();
  });

  it('accepts className prop', () => {
    const { container } = render(<TypingAnimation text="Test" className="custom-class" />);
    expect(container.querySelector('.custom-class')).toBeInTheDocument();
  });
});
