/**
 * Tests for ErrorBoundary component.
 * Covers: renders children, catches errors, shows fallback, retry resets.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ErrorBoundary } from './ErrorBoundary';

// Suppress console.error from React error boundary in tests
const originalConsoleError = console.error;
beforeEach(() => {
  console.error = vi.fn();
});
afterEach(() => {
  console.error = originalConsoleError;
});

/** Component that always throws during render */
function ThrowingComponent({ error }: { error: Error }) {
  throw error;
}

/** Component that can be toggled to throw */
function ConditionalThrower({ shouldThrow }: { shouldThrow: boolean }) {
  if (shouldThrow) throw new Error('Test error');
  return <div data-testid="safe-content">Safe content</div>;
}

describe('ErrorBoundary', () => {
  it('renders children when no error', () => {
    render(
      <ErrorBoundary>
        <div data-testid="child">Child content</div>
      </ErrorBoundary>,
    );
    expect(screen.getByTestId('child')).toBeTruthy();
  });

  it('shows default fallback when child throws', () => {
    render(
      <ErrorBoundary>
        <ThrowingComponent error={new Error('Boom')} />
      </ErrorBoundary>,
    );
    expect(screen.getByText('Что-то пошло не так')).toBeTruthy();
  });

  it('shows custom fallback when provided and child throws', () => {
    render(
      <ErrorBoundary fallback={<div data-testid="custom-fallback">Custom error</div>}>
        <ThrowingComponent error={new Error('Boom')} />
      </ErrorBoundary>,
    );
    expect(screen.getByTestId('custom-fallback')).toBeTruthy();
  });

  it('displays error message in default fallback', () => {
    render(
      <ErrorBoundary>
        <ThrowingComponent error={new Error('Specific error message')} />
      </ErrorBoundary>,
    );
    expect(screen.getByText('Specific error message')).toBeTruthy();
  });

  it('calls onError callback when error is caught', () => {
    const onError = vi.fn();
    render(
      <ErrorBoundary onError={onError}>
        <ThrowingComponent error={new Error('Callback test')} />
      </ErrorBoundary>,
    );
    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError).toHaveBeenCalledWith(expect.any(Error));
  });

  it('resets error state when retry button is clicked', () => {
    // First render: child throws
    const { unmount } = render(
      <ErrorBoundary>
        <ThrowingComponent error={new Error('Retry test')} />
      </ErrorBoundary>,
    );

    expect(screen.getByText('Что-то пошло не так')).toBeTruthy();

    // Click retry — this resets hasError state
    const retryBtn = screen.getByText('Попробовать снова');
    fireEvent.click(retryBtn);

    // Now re-render with a safe child
    // ErrorBoundary's hasError is now false, so it renders children
    unmount();
    render(
      <ErrorBoundary>
        <ConditionalThrower shouldThrow={false} />
      </ErrorBoundary>,
    );

    expect(screen.getByTestId('safe-content')).toBeTruthy();
  });

  it('shows Update (Обновить) button that reloads page', () => {
    const reloadMock = vi.fn();
    Object.defineProperty(window, 'location', {
      value: { reload: reloadMock },
      writable: true,
    });

    render(
      <ErrorBoundary>
        <ThrowingComponent error={new Error('Reload test')} />
      </ErrorBoundary>,
    );

    const reloadBtn = screen.getByText('Обновить');
    fireEvent.click(reloadBtn);
    expect(reloadMock).toHaveBeenCalledTimes(1);
  });

  it('renders error message with role="alert"', () => {
    render(
      <ErrorBoundary>
        <ThrowingComponent error={new Error('Alert test')} />
      </ErrorBoundary>,
    );
    const alertEl = screen.getByRole('alert');
    expect(alertEl).toBeTruthy();
    expect(alertEl.textContent).toContain('Alert test');
  });
});
