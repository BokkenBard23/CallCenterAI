import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import App from './App';

describe('App', () => {
  it('renders header', () => {
    render(<App />);
    expect(screen.getByTestId('Header')).toBeInTheDocument();
    expect(screen.getByRole('banner')).toBeInTheDocument();
  });

  it('renders theme toggle button', () => {
    render(<App />);
    expect(
      screen.getByRole('button', { name: 'Включить тёмную тему' }),
    ).toBeInTheDocument();
  });

  it('renders app root with data-theme', () => {
    render(<App />);
    const root = document.querySelector('.app-root');
    expect(root).toBeTruthy();
    expect(root?.getAttribute('data-theme')).toBe('light');
  });
});
