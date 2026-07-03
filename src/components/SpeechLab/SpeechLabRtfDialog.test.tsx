/**
 * Tests for SpeechLabRtfDialog — Dialog for uploading RTF dialogue files.
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SpeechLabRtfDialog from './SpeechLabRtfDialog';

describe('SpeechLabRtfDialog', () => {
  const defaultProps = {
    open: true,
    fileName: null,
    uploading: false,
    error: null,
    onFileSelect: vi.fn(),
    onUpload: vi.fn().mockResolvedValue(undefined),
    onClose: vi.fn(),
  };

  it('renders dialog title when open', () => {
    render(<SpeechLabRtfDialog {...defaultProps} />);
    expect(screen.getByText('Загрузка диалога')).toBeInTheDocument();
  });

  it('renders file picker prompt when no file selected', () => {
    render(<SpeechLabRtfDialog {...defaultProps} />);
    expect(screen.getByText(/Нажмите или перетащите RTF-файл/)).toBeInTheDocument();
  });

  it('renders selected file name', () => {
    render(<SpeechLabRtfDialog {...defaultProps} fileName="dialog.rtf" />);
    expect(screen.getByText('dialog.rtf')).toBeInTheDocument();
  });

  it('disables upload button when no file is selected', () => {
    render(<SpeechLabRtfDialog {...defaultProps} />);
    const uploadBtn = screen.getByRole('button', { name: 'Загрузить' });
    expect(uploadBtn).toBeDisabled();
  });

  it('enables upload button when file is selected', () => {
    render(<SpeechLabRtfDialog {...defaultProps} fileName="test.rtf" />);
    const uploadBtn = screen.getByRole('button', { name: 'Загрузить' });
    expect(uploadBtn).not.toBeDisabled();
  });

  it('shows "Загрузка..." when uploading', () => {
    render(<SpeechLabRtfDialog {...defaultProps} fileName="test.rtf" uploading={true} />);
    expect(screen.getByText('Загрузка...')).toBeInTheDocument();
  });

  it('disables upload button when uploading', () => {
    render(<SpeechLabRtfDialog {...defaultProps} fileName="test.rtf" uploading={true} />);
    const uploadBtn = screen.getByRole('button', { name: /Загрузка/ });
    expect(uploadBtn).toBeDisabled();
  });

  it('renders error message when error is present', () => {
    render(<SpeechLabRtfDialog {...defaultProps} error="Файл слишком большой" />);
    expect(screen.getByText(/Файл слишком большой/)).toBeInTheDocument();
  });

  it('calls onClose when Cancel button is clicked', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<SpeechLabRtfDialog {...defaultProps} onClose={onClose} />);
    await user.click(screen.getByRole('button', { name: 'Отмена' }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('calls onUpload when Upload button is clicked', async () => {
    const user = userEvent.setup();
    const onUpload = vi.fn().mockResolvedValue(undefined);
    render(<SpeechLabRtfDialog {...defaultProps} fileName="test.rtf" onUpload={onUpload} />);
    await user.click(screen.getByRole('button', { name: 'Загрузить' }));
    expect(onUpload).toHaveBeenCalledOnce();
  });
});
