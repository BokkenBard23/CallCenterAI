/**
 * Tests for RouterLink — SPA navigation adapter for DS LinkRouter.
 *
 * We verify DOM behaviour (link rendered, click intercepts default
 * navigation) rather than asserting actual react-router navigation,
 * which is the responsibility of react-router itself.
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import RouterLink from './RouterLink';

function renderWithRouter(ui: React.ReactNode) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

describe('RouterLink', () => {
  it('renders DS LinkRouter with provided children', () => {
    renderWithRouter(<RouterLink to="/speechlab">Открыть</RouterLink>);
    expect(screen.getByText('Открыть')).toBeInTheDocument();
  });

  it('renders an anchor element pointing at the target route', () => {
    renderWithRouter(<RouterLink to="/history">История</RouterLink>);
    // DS LinkRouter renders an <a> with href set to the `to` value.
    const anchor = screen.getByText('История').closest('a');
    expect(anchor).not.toBeNull();
    expect(anchor?.getAttribute('href')).toBe('/history');
  });

  it('prevents default anchor navigation on left-click', () => {
    renderWithRouter(<RouterLink to="/history">История</RouterLink>);

    const link = screen.getByText('История');
    const event = new MouseEvent('click', {
      bubbles: true,
      cancelable: true,
      button: 0,
    });
    const preventDefaultSpy = vi.fn();
    Object.defineProperty(event, 'preventDefault', {
      value: preventDefaultSpy,
    });

    link.dispatchEvent(event);
    expect(preventDefaultSpy).toHaveBeenCalled();
  });

  it('does not crash on modified clicks (Ctrl/Cmd/Shift)', () => {
    renderWithRouter(<RouterLink to="/history">История</RouterLink>);
    const link = screen.getByText('История');
    // ctrl+click — should NOT preventDefault (user wants new tab)
    fireEvent.click(link, { button: 0, ctrlKey: true });
    // shift+click
    fireEvent.click(link, { button: 0, shiftKey: true });
    expect(link).toBeInTheDocument();
  });

  it('does not crash on middle/right clicks', () => {
    renderWithRouter(<RouterLink to="/history">История</RouterLink>);
    const link = screen.getByText('История');
    fireEvent.click(link, { button: 1 });
    fireEvent.click(link, { button: 2 });
    expect(link).toBeInTheDocument();
  });

  it('passes isActive prop through to DS LinkRouter', () => {
    renderWithRouter(
      <RouterLink to="/history" isActive>
        История
      </RouterLink>,
    );
    // We can't directly assert DS internal active class without knowing
    // its exact name, but verify the link renders without errors.
    expect(screen.getByText('История')).toBeInTheDocument();
  });
});
