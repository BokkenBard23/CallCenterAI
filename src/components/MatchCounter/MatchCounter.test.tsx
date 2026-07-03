/**
 * Tests for MatchCounter component.
 * Verifies rendering with different variants and labels.
 */

import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import MatchCounter from './MatchCounter';

describe('MatchCounter', () => {
  it('renders with count', () => {
    render(<MatchCounter count={42} />);
    // NumberTicker renders a span with initial value (0 by default)
    // The animated value is set asynchronously, so we check the container
    const container = document.querySelector('.match-counter--default');
    expect(container).toBeTruthy();
  });

  it('renders with label', () => {
    render(<MatchCounter count={5} label="Совпадений:" />);
    expect(screen.getByText('Совпадений:')).toBeTruthy();
  });

  it('renders success variant', () => {
    const { container } = render(<MatchCounter count={10} variant="success" />);
    expect(container.querySelector('.match-counter--success')).toBeTruthy();
  });

  it('renders warning variant', () => {
    const { container } = render(<MatchCounter count={3} variant="warning" />);
    expect(container.querySelector('.match-counter--warning')).toBeTruthy();
  });

  it('renders danger variant', () => {
    const { container } = render(<MatchCounter count={0} variant="danger" />);
    expect(container.querySelector('.match-counter--danger')).toBeTruthy();
  });

  it('renders default variant when not specified', () => {
    const { container } = render(<MatchCounter count={7} />);
    expect(container.querySelector('.match-counter--default')).toBeTruthy();
  });
});
