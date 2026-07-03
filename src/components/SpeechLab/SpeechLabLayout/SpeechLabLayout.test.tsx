/**
 * Tests for SpeechLabLayout — 3-panel resizable layout (react-resizable-panels).
 *
 * Wave UI-1: Updated for react-resizable-panels (Group/Panel/Separator).
 * Mocks localStorage for useDefaultLayout persistence.
 * Covers: panel rendering, tabs, initial state, match count.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import SpeechLabLayout from './SpeechLabLayout';
import type { SpeechLabTreeNode } from '../../../types/speechlab';

// Mock localStorage for useDefaultLayout
const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => {
      store[key] = value;
    },
    removeItem: (key: string) => {
      delete store[key];
    },
    clear: () => {
      store = {};
    },
  };
})();

Object.defineProperty(window, 'localStorage', {
  value: localStorageMock,
});

function makeNode(
  overrides: Partial<SpeechLabTreeNode> & { id: string; name: string },
): SpeechLabTreeNode {
  return {
    has_children: false,
    children_count: 0,
    is_remainder: false,
    display_tokens: [],
    children: [],
    ...overrides,
  };
}

const defaultProps = {
  treeNodes: [makeNode({ id: '1', name: 'Словарь 1' })],
  selectedNode: null,
  selectedNodeId: null,
  onSelectNode: () => {},
  onDictionaryUploaded: () => {},
  sessionId: 'test-session',
  searchResult: null,
  isSearching: false,
  searchError: null,
  onRunAnalysis: () => {},
  segments: [],
};

describe('SpeechLabLayout', () => {
  beforeEach(() => {
    localStorageMock.clear();
  });

  it('renders left panel with dictionary tree', () => {
    render(<SpeechLabLayout {...defaultProps} />);
    expect(screen.getByText('Словарь')).toBeInTheDocument();
  });

  it('renders tabs for Query and Found Records', () => {
    render(<SpeechLabLayout {...defaultProps} />);
    expect(screen.getByText('Запрос')).toBeInTheDocument();
    expect(screen.getByText('Найденные записи')).toBeInTheDocument();
  });

  it('renders resizable separator between panels', () => {
    const { container } = render(<SpeechLabLayout {...defaultProps} />);
    // react-resizable-panels renders separators with data-separator attribute
    const separators = container.querySelectorAll('[data-separator]');
    expect(separators.length).toBeGreaterThanOrEqual(1);
  });

  it('renders "Выберите словарь" in query tab when no node selected', () => {
    render(<SpeechLabLayout {...defaultProps} />);
    expect(screen.getByText('Выберите словарь в дереве')).toBeInTheDocument();
  });

  it('shows match count in tab label when search has results', () => {
    const searchResult = {
      segments: [],
      total_matches: 5,
      matches: [],
      matches_by_level: {},
    };
    render(<SpeechLabLayout {...defaultProps} searchResult={searchResult} />);
    expect(screen.getByText('Найденные записи (5)')).toBeInTheDocument();
  });

  it('renders import button in left panel', () => {
    render(<SpeechLabLayout {...defaultProps} />);
    expect(screen.getByText('Импорт XML')).toBeInTheDocument();
  });

  it('renders search field in left panel', () => {
    render(<SpeechLabLayout {...defaultProps} />);
    expect(screen.getByPlaceholderText('Поиск по словарю')).toBeInTheDocument();
  });
});
