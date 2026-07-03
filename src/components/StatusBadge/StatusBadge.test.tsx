/**
 * Tests for StatusBadge — DS Badge wrapper for analysis status.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { StatusBadge } from './StatusBadge';
import type { AnalysisItemStatus } from './StatusBadge';

// Mock the DS Badge — we just verify it renders without crash
vi.mock('@beeline/design-system-react', () => ({
  Badge: ({ children, semantic, icon }: { children: React.ReactNode; semantic?: string; icon?: string }) => (
    <span data-testid="mock-badge" data-semantic={semantic} data-icon={icon}>
      {children}
    </span>
  ),
}));

describe('StatusBadge', () => {
  const cases: Array<[AnalysisItemStatus, string]> = [
    ['pending', 'Ожидание'],
    ['processing', 'Обработка'],
    ['completed', 'Завершён'],
    ['failed', 'Ошибка'],
  ];

  it.each(cases)('renders correct label for status "%s"', (status, expectedLabel) => {
    render(<StatusBadge status={status} />);
    expect(screen.getByText(expectedLabel)).toBeInTheDocument();
  });

  it('maps pending to warning semantic', () => {
    render(<StatusBadge status="pending" />);
    const badge = screen.getByTestId('mock-badge');
    expect(badge).toHaveAttribute('data-semantic', 'warning');
  });

  it('maps processing to info semantic', () => {
    render(<StatusBadge status="processing" />);
    const badge = screen.getByTestId('mock-badge');
    expect(badge).toHaveAttribute('data-semantic', 'info');
  });

  it('maps completed to success semantic', () => {
    render(<StatusBadge status="completed" />);
    const badge = screen.getByTestId('mock-badge');
    expect(badge).toHaveAttribute('data-semantic', 'success');
  });

  it('maps failed to danger semantic', () => {
    render(<StatusBadge status="failed" />);
    const badge = screen.getByTestId('mock-badge');
    expect(badge).toHaveAttribute('data-semantic', 'danger');
  });

  it('passes dataTestId to Badge', () => {
    render(<StatusBadge status="completed" dataTestId="test-status" />);
    const badge = screen.getByTestId('mock-badge');
    expect(badge).toBeInTheDocument();
  });
});
