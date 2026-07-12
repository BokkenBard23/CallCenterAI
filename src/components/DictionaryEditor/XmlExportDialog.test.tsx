import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { XmlExportDialog } from './XmlExportDialog';

describe('XmlExportDialog', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    // Mock URL.createObjectURL / revokeObjectURL (jsdom lacks them).
    if (!('createObjectURL' in URL)) {
      (URL as unknown as { createObjectURL: () => string }).createObjectURL = () => 'blob:mock';
      (URL as unknown as { revokeObjectURL: () => void }).revokeObjectURL = () => undefined;
    }
    // jsdom throws "Not implemented: navigation" on <a>.click() — stub it.
    HTMLAnchorElement.prototype.click = vi.fn();
  });

  it('renders nothing visible when closed', () => {
    render(
      <XmlExportDialog
        open={false}
        onClose={() => undefined}
        sessionId="s1"
        rootDictNames={['Dict1']}
      />,
    );
    expect(screen.queryByText('Экспорт XML')).toBeNull();
  });

  it('renders title and dict options when open', () => {
    render(
      <XmlExportDialog
        open
        onClose={() => undefined}
        sessionId="s1"
        rootDictNames={['Dict1', 'Dict2']}
      />,
    );
    expect(screen.getByText('Экспорт XML')).toBeInTheDocument();
    expect(screen.getByText('Форматированный XML')).toBeInTheDocument();
  });

  it('export button disabled when dictName is empty', () => {
    render(
      <XmlExportDialog
        open
        onClose={() => undefined}
        sessionId="s1"
        rootDictNames={[]}
        defaultDictName={null}
      />,
    );
    const exportBtn = screen.getByText('Экспортировать');
    expect(exportBtn).toBeDisabled();
  });

  it('triggers exportXml on click and calls onClose after success', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(new Blob(['<x/>'], { type: 'application/xml' }), { status: 200 }),
    );
    vi.stubGlobal('fetch', fetchMock);
    const onClose = vi.fn();

    render(
      <XmlExportDialog
        open
        onClose={onClose}
        sessionId="s1"
        rootDictNames={['Dict1']}
        defaultDictName="Dict1"
      />,
    );
    const exportBtn = screen.getByText('Экспортировать');
    await fireEvent.click(exportBtn);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/dictionary/s1/export-xml',
      expect.objectContaining({ method: 'POST' }),
    );
    // Dialog auto-closes on success.
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it('renders error InlineAlert when export fails', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'fail' }), { status: 500 }),
    );
    vi.stubGlobal('fetch', fetchMock);

    render(
      <XmlExportDialog
        open
        onClose={() => undefined}
        sessionId="s1"
        rootDictNames={['Dict1']}
        defaultDictName="Dict1"
      />,
    );
    await fireEvent.click(screen.getByText('Экспортировать'));
    // InlineAlert danger renders on error.
    await screen.findByText('Ошибка экспорта');
  });
});
