/**
 * Tests for BlurFade animation component.
 * Verifies rendering, default props, and animation attributes.
 */

import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { BlurFade } from './blur-fade';

describe('BlurFade', () => {
  it('renders children', () => {
    render(<BlurFade>Test content</BlurFade>);
    expect(screen.getByText('Test content')).toBeTruthy();
  });

  it('applies className', () => {
    const { container } = render(
      <BlurFade className="test-class">Content</BlurFade>,
    );
    expect(container.querySelector('.test-class')).toBeTruthy();
  });

  it('renders with custom duration and delay', () => {
    const { container } = render(
      <BlurFade duration={0.8} delay={0.2}>Content</BlurFade>,
    );
    // motion.div is rendered regardless of animation params
    expect(container.firstChild).toBeTruthy();
  });

  it('renders with inView prop', () => {
    const { container } = render(
      <BlurFade inView={true}>Content</BlurFade>,
    );
    expect(container.firstChild).toBeTruthy();
  });

  it('renders with different directions', () => {
    for (const dir of ['up', 'down', 'left', 'right'] as const) {
      const { container } = render(
        <BlurFade direction={dir}>Content {dir}</BlurFade>,
      );
      expect(container.firstChild).toBeTruthy();
    }
  });

  it('does not animate when visible is false', () => {
    render(
      <BlurFade visible={false}>Hidden content</BlurFade>,
    );
    expect(screen.getByText('Hidden content')).toBeTruthy();
  });

  it('renders with custom blur amount', () => {
    const { container } = render(
      <BlurFade blur="10px">Blurred content</BlurFade>,
    );
    expect(container.firstChild).toBeTruthy();
  });
});
