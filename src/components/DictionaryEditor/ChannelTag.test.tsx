import { render } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { ChannelTag } from './ChannelTag';

describe('ChannelTag', () => {
  it('renders ANY as neutral secondary badge with short label', () => {
    const { container } = render(<ChannelTag channel="ANY" />);
    expect(container.textContent).toContain('ANY');
  });

  it('renders CLIENT as success secondary badge', () => {
    const { container } = render(<ChannelTag channel="CLIENT" />);
    expect(container.textContent).toContain('CL');
  });

  it('renders OPERATOR as violet secondary badge', () => {
    const { container } = render(<ChannelTag channel="OPERATOR" />);
    expect(container.textContent).toContain('OP');
  });

  it('renders full label when full=true', () => {
    const { container } = render(<ChannelTag channel="CLIENT" full />);
    expect(container.textContent).toContain('CLIENT');
  });

  it('renders neutral dash for SYSTEM (hidden BE gap)', () => {
    const { container } = render(<ChannelTag channel="SYSTEM" />);
    expect(container.textContent).toContain('—');
  });

  it('renders neutral dash for unknown channel', () => {
    const { container } = render(<ChannelTag channel="UNKNOWN" />);
    expect(container.textContent).toContain('—');
  });
});
