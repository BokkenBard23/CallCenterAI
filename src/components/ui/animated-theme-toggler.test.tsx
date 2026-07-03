/**
 * AnimatedThemeToggler tests — WCAG a11y, View Transitions fallback, theme switching.
 */

import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

import { AnimatedThemeToggler } from './animated-theme-toggler';

describe('AnimatedThemeToggler', () => {
  it('renders with correct aria-label for light theme', () => {
    render(
      <AnimatedThemeToggler theme="light" onThemeChange={() => {}} />,
    );
    expect(
      screen.getByRole('button', { name: 'Включить тёмную тему' }),
    ).toBeInTheDocument();
  });

  it('renders with correct aria-label for dark theme', () => {
    render(
      <AnimatedThemeToggler theme="dark" onThemeChange={() => {}} />,
    );
    expect(
      screen.getByRole('button', { name: 'Включить светлую тему' }),
    ).toBeInTheDocument();
  });

  it('calls onThemeChange on click', () => {
    const handleChange = vi.fn();
    render(
      <AnimatedThemeToggler theme="light" onThemeChange={handleChange} />,
    );
    const button = screen.getByRole('button', { name: 'Включить тёмную тему' });
    fireEvent.click(button);
    expect(handleChange).toHaveBeenCalledTimes(1);
  });

  it('uses fallback (instant toggle) when View Transitions API is not available', () => {
    // jsdom does not support startViewTransition, so this tests the fallback path
    const handleChange = vi.fn();
    render(
      <AnimatedThemeToggler theme="light" onThemeChange={handleChange} />,
    );
    const button = screen.getByRole('button', { name: 'Включить тёмную тему' });
    fireEvent.click(button);
    expect(handleChange).toHaveBeenCalledTimes(1);
  });

  it('is a button element (accessible)', () => {
    render(
      <AnimatedThemeToggler theme="light" onThemeChange={() => {}} />,
    );
    const button = screen.getByRole('button');
    expect(button.tagName).toBe('BUTTON');
  });
});
