/**
 * Accessibility tests for App — skip-nav, ARIA landmarks, focus management.
 */

import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';

import App from './App';

describe('App — Accessibility (Chunk 5)', () => {
  it('renders skip-to-content link', () => {
    render(<App />);
    const skipLink = screen.getByText('Перейти к основному содержимому');
    expect(skipLink).toBeInTheDocument();
    expect(skipLink.tagName).toBe('A');
    expect(skipLink).toHaveAttribute('href', '#main-content');
  });

  it('renders main landmark with role="main"', () => {
    render(<App />);
    const main = screen.getByRole('main');
    expect(main).toBeInTheDocument();
    expect(main).toHaveAttribute('id', 'main-content');
  });

  it('main landmark has aria-label', () => {
    render(<App />);
    const main = screen.getByRole('main');
    expect(main).toHaveAttribute('aria-label', 'Основное содержимое приложения');
  });

  it('main landmark is focusable (tabIndex=-1) for skip-nav', () => {
    render(<App />);
    const main = screen.getByRole('main');
    expect(main).toHaveAttribute('tabindex', '-1');
  });

  it('renders banner landmark (Header)', () => {
    render(<App />);
    expect(screen.getByRole('banner')).toBeInTheDocument();
  });

  it('skip-nav link has correct CSS class', () => {
    render(<App />);
    const skipLink = screen.getByText('Перейти к основному содержимому');
    expect(skipLink).toHaveClass('skip-nav');
  });

  it('app root has data-theme attribute', () => {
    render(<App />);
    const root = document.querySelector('.app-root');
    expect(root).toBeTruthy();
    expect(root?.getAttribute('data-theme')).toBe('light');
  });
});
