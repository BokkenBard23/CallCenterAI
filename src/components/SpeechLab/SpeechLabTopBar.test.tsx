/**
 * Tests for SpeechLabTopBar — RTF session status bar.
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SpeechLabTopBar from './SpeechLabTopBar';

describe('SpeechLabTopBar', () => {
  it('renders session loaded state with dialogue length', () => {
    render(<SpeechLabTopBar hasSession={true} dialogueLength={42} onOpenRtfDialog={vi.fn()} />);
    expect(screen.getByText(/Диалог загружен/)).toBeInTheDocument();
    expect(screen.getByText(/42 реплик/)).toBeInTheDocument();
  });

  it('renders no-session prompt', () => {
    render(<SpeechLabTopBar hasSession={false} dialogueLength={0} onOpenRtfDialog={vi.fn()} />);
    expect(screen.getByText(/Загрузите RTF-файл диалога для поиска совпадений/)).toBeInTheDocument();
  });

  it('shows "Загрузить диалог" button when no session', () => {
    render(<SpeechLabTopBar hasSession={false} dialogueLength={0} onOpenRtfDialog={vi.fn()} />);
    expect(screen.getByRole('button', { name: /Загрузить диалог/ })).toBeInTheDocument();
  });

  it('shows "Заменить диалог" button when session is active', () => {
    render(<SpeechLabTopBar hasSession={true} dialogueLength={5} onOpenRtfDialog={vi.fn()} />);
    expect(screen.getByRole('button', { name: /Заменить диалог/ })).toBeInTheDocument();
  });

  it('calls onOpenRtfDialog when button is clicked', async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    render(<SpeechLabTopBar hasSession={false} dialogueLength={0} onOpenRtfDialog={onOpen} />);
    await user.click(screen.getByRole('button'));
    expect(onOpen).toHaveBeenCalledOnce();
  });
});
