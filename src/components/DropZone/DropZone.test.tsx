/**
 * Tests for DropZone — drag-and-drop file upload component.
 * Covers: renders correctly, keyboard fallback, file acceptance.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { DropZone } from './DropZone';

describe('DropZone', () => {
  const defaultProps = {
    accept: '.rtf',
    onFilesSelected: vi.fn(),
    idleLabel: 'Нажмите или перетащите RTF-файл',
    idleSubLabel: 'Формат .rtf, один файл',
    dragLabel: 'Отпустите файл для загрузки',
    ariaLabel: 'Загрузить RTF-файл',
  };

  it('renders idle label text', () => {
    render(<DropZone {...defaultProps} />);
    expect(screen.getByText('Нажмите или перетащите RTF-файл')).toBeTruthy();
  });

  it('renders sub-label text', () => {
    render(<DropZone {...defaultProps} />);
    expect(screen.getByText('Формат .rtf, один файл')).toBeTruthy();
  });

  it('renders with correct aria-label', () => {
    render(<DropZone {...defaultProps} />);
    expect(screen.getByLabelText('Загрузить RTF-файл')).toBeTruthy();
  });

  it('opens file picker on click', () => {
    render(<DropZone {...defaultProps} />);
    const zone = screen.getByLabelText('Загрузить RTF-файл');
    // Click should not throw
    fireEvent.click(zone);
  });

  it('opens file picker on Enter key', () => {
    render(<DropZone {...defaultProps} />);
    const zone = screen.getByLabelText('Загрузить RTF-файл');
    fireEvent.keyDown(zone, { key: 'Enter' });
  });

  it('opens file picker on Space key', () => {
    render(<DropZone {...defaultProps} />);
    const zone = screen.getByLabelText('Загрузить RTF-файл');
    fireEvent.keyDown(zone, { key: ' ' });
  });

  it('renders hidden file input with correct accept', () => {
    render(<DropZone {...defaultProps} inputTestId="rtf-input" />);
    const input = document.querySelector('[data-testid="rtf-input"]') as HTMLInputElement;
    expect(input).toBeTruthy();
    expect(input.accept).toBe('.rtf');
  });

  it('calls onFilesSelected when file is selected via input', () => {
    const onFilesSelected = vi.fn();
    render(
      <DropZone {...defaultProps} onFilesSelected={onFilesSelected} inputTestId="test-input" />,
    );

    const input = document.querySelector('[data-testid="test-input"]') as HTMLInputElement;
    const file = new File(['test'], 'dialog.rtf', { type: 'application/rtf' });
    fireEvent.change(input, { target: { files: [file] } });

    expect(onFilesSelected).toHaveBeenCalledTimes(1);
    // Should receive File[] with the uploaded file
    const calledWith = onFilesSelected.mock.calls[0][0] as File[];
    expect(calledWith.length).toBe(1);
    expect(calledWith[0].name).toBe('dialog.rtf');
  });

  it('accepts .xml files when configured', () => {
    const onFilesSelected = vi.fn();
    render(
      <DropZone
        {...defaultProps}
        accept=".xml"
        onFilesSelected={onFilesSelected}
        inputTestId="xml-input"
        ariaLabel="Загрузить XML-файлы"
        multiple
      />,
    );

    const input = document.querySelector('[data-testid="xml-input"]') as HTMLInputElement;
    expect(input.accept).toBe('.xml');
    expect(input.multiple).toBe(true);
  });

  it('is disabled when disabled prop is true', () => {
    render(<DropZone {...defaultProps} disabled />);
    const zone = screen.getByLabelText('Загрузить RTF-файл');
    expect(zone.getAttribute('aria-disabled')).toBe('true');
  });

  it('handles drag enter event', () => {
    render(<DropZone {...defaultProps} />);
    const zone = screen.getByLabelText('Загрузить RTF-файл');

    // Create a drag enter event
    fireEvent.dragEnter(zone, {
      dataTransfer: { files: [] },
      preventDefault: vi.fn(),
      stopPropagation: vi.fn(),
    });

    // After drag enter, the label should change to drag label
    expect(screen.getByText('Отпустите файл для загрузки')).toBeTruthy();
  });

  it('returns to idle state after drag leave', () => {
    render(<DropZone {...defaultProps} />);
    const zone = screen.getByLabelText('Загрузить RTF-файл');

    // Enter drag state
    fireEvent.dragEnter(zone, {
      dataTransfer: { files: [] },
      preventDefault: vi.fn(),
      stopPropagation: vi.fn(),
    });
    expect(screen.getByText('Отпустите файл для загрузки')).toBeTruthy();

    // Leave drag state
    fireEvent.dragLeave(zone, {
      dataTransfer: { files: [] },
      preventDefault: vi.fn(),
      stopPropagation: vi.fn(),
      relatedTarget: null,
      currentTarget: zone,
    });

    // Should return to idle label
    expect(screen.getByText('Нажмите или перетащите RTF-файл')).toBeTruthy();
  });

  it('handles drop event and calls onFilesSelected', () => {
    const onFilesSelected = vi.fn();
    render(<DropZone {...defaultProps} onFilesSelected={onFilesSelected} />);

    const zone = screen.getByLabelText('Загрузить RTF-файл');
    const file = new File(['test'], 'dialog.rtf', { type: 'application/rtf' });

    // First enter drag state
    fireEvent.dragEnter(zone, {
      dataTransfer: { files: [file] },
      preventDefault: vi.fn(),
      stopPropagation: vi.fn(),
    });

    // Then drop
    fireEvent.drop(zone, {
      dataTransfer: { files: [file] },
      preventDefault: vi.fn(),
      stopPropagation: vi.fn(),
    });

    expect(onFilesSelected).toHaveBeenCalledTimes(1);
  });

  it('does not call onFilesSelected for non-matching file types on drop', () => {
    const onFilesSelected = vi.fn();
    render(<DropZone {...defaultProps} onFilesSelected={onFilesSelected} />);

    const zone = screen.getByLabelText('Загрузить RTF-файл');
    const file = new File(['test'], 'document.pdf', { type: 'application/pdf' });

    fireEvent.dragEnter(zone, {
      dataTransfer: { files: [file] },
      preventDefault: vi.fn(),
      stopPropagation: vi.fn(),
    });

    fireEvent.drop(zone, {
      dataTransfer: { files: [file] },
      preventDefault: vi.fn(),
      stopPropagation: vi.fn(),
    });

    expect(onFilesSelected).not.toHaveBeenCalled();
  });
});
