/**
 * AnalysisContext — React Context + useReducer for global app state.
 * Manages upload, provider selection, analysis results, and UI state.
 */

import React, {
  createContext,
  useContext,
  useReducer,
  type ReactNode,
} from 'react';
import type {
  DialogueTurn,
  UploadedDictionary,
  UploadStatus,
  AnalysisStatus,
  ProviderStatus,
  ViewMode,
  ProviderInfo,
  SearchResult,
  LLMResult,
  BatchAnalysisResponse,
} from '../types/api';

// ═══════════════════════════════════════════════════════════
// State
// ═══════════════════════════════════════════════════════════

export interface AnalysisState {
  // Upload
  sessionId: string | null;
  rtfFile: File | null;
  rtfUploadStatus: UploadStatus;
  rtfError: string | null;
  dialogue: DialogueTurn[] | null;

  dictionaries: UploadedDictionary[];
  dictionaryUploadStatus: UploadStatus;
  dictionaryError: string | null;

  // LLM
  providers: ProviderInfo[];
  selectedProvider: string | null;
  selectedModel: string | null;
  providerStatus: ProviderStatus;

  // Analysis
  analysisId: string | null;
  analysisStatus: AnalysisStatus;
  analysisError: string | null;
  searchResult: SearchResult | null;
  llmResult: LLMResult | null;
  /** True while LLM analysis is in progress (phase 2 of two-phase analysis) */
  llmLoading: boolean;

  // UI
  viewMode: ViewMode;
  hideNoMatch: boolean;

  // Batch
  batchId: string | null;
  batchStatus: BatchAnalysisResponse | null;
}

// eslint-disable-next-line react-refresh/only-export-components
export const initialState: AnalysisState = {
  sessionId: null,
  rtfFile: null,
  rtfUploadStatus: 'idle',
  rtfError: null,
  dialogue: null,

  dictionaries: [],
  dictionaryUploadStatus: 'idle',
  dictionaryError: null,

  providers: [],
  selectedProvider: null,
  selectedModel: null,
  providerStatus: 'loading',

  analysisId: null,
  analysisStatus: 'idle',
  analysisError: null,
  searchResult: null,
  llmResult: null,
  llmLoading: false,

  viewMode: 'summary',
  hideNoMatch: true,

  batchId: null,
  batchStatus: null,
};

// ═══════════════════════════════════════════════════════════
// Actions
// ═══════════════════════════════════════════════════════════

export type AnalysisAction =
  | { type: 'SET_SESSION_ID'; payload: string }
  | { type: 'SET_RTF_FILE'; payload: File | null }
  | { type: 'SET_RTF_UPLOAD_STATUS'; payload: UploadStatus }
  | { type: 'SET_RTF_ERROR'; payload: string | null }
  | { type: 'SET_DIALOGUE'; payload: DialogueTurn[] | null }
  | { type: 'ADD_DICTIONARY'; payload: UploadedDictionary }
  | { type: 'REMOVE_DICTIONARY'; payload: number }
  | { type: 'SET_DICTIONARY_UPLOAD_STATUS'; payload: UploadStatus }
  | { type: 'SET_DICTIONARY_ERROR'; payload: string | null }
  | { type: 'SET_PROVIDERS'; payload: ProviderInfo[] }
  | { type: 'SET_PROVIDER_STATUS'; payload: ProviderStatus }
  | { type: 'SET_SELECTED_PROVIDER'; payload: string | null }
  | { type: 'SET_SELECTED_MODEL'; payload: string | null }
  | { type: 'SET_ANALYSIS_ID'; payload: string | null }
  | { type: 'SET_ANALYSIS_STATUS'; payload: AnalysisStatus }
  | { type: 'SET_ANALYSIS_ERROR'; payload: string | null }
  | { type: 'SET_SEARCH_RESULT'; payload: SearchResult | null }
  | { type: 'SET_LLM_RESULT'; payload: LLMResult | null }
  | { type: 'SET_LLM_LOADING'; payload: boolean }
  | { type: 'SET_VIEW_MODE'; payload: ViewMode }
  | { type: 'SET_HIDE_NO_MATCH'; payload: boolean }
  | { type: 'SET_ANALYSIS_RESULTS'; payload: { searchResult: SearchResult | null; llmResult: LLMResult | null } }
  | { type: 'SET_BATCH_ID'; payload: string | null }
  | { type: 'SET_BATCH_STATUS'; payload: BatchAnalysisResponse | null }
  | { type: 'RESET_UPLOAD' };

function analysisReducer(
  state: AnalysisState,
  action: AnalysisAction,
): AnalysisState {
  switch (action.type) {
    case 'SET_SESSION_ID':
      return { ...state, sessionId: action.payload };
    case 'SET_RTF_FILE':
      return { ...state, rtfFile: action.payload };
    case 'SET_RTF_UPLOAD_STATUS':
      return { ...state, rtfUploadStatus: action.payload };
    case 'SET_RTF_ERROR':
      return { ...state, rtfError: action.payload };
    case 'SET_DIALOGUE':
      return { ...state, dialogue: action.payload };
    case 'ADD_DICTIONARY':
      return {
        ...state,
        dictionaries: [...state.dictionaries, action.payload],
      };
    case 'REMOVE_DICTIONARY':
      return {
        ...state,
        dictionaries: state.dictionaries.filter((_, i) => i !== action.payload),
      };
    case 'SET_DICTIONARY_UPLOAD_STATUS':
      return { ...state, dictionaryUploadStatus: action.payload };
    case 'SET_DICTIONARY_ERROR':
      return { ...state, dictionaryError: action.payload };
    case 'SET_PROVIDERS':
      return { ...state, providers: action.payload };
    case 'SET_PROVIDER_STATUS':
      return { ...state, providerStatus: action.payload };
    case 'SET_SELECTED_PROVIDER':
      return { ...state, selectedProvider: action.payload, selectedModel: null };
    case 'SET_SELECTED_MODEL':
      return { ...state, selectedModel: action.payload };
    case 'SET_ANALYSIS_ID':
      return { ...state, analysisId: action.payload };
    case 'SET_ANALYSIS_STATUS':
      return { ...state, analysisStatus: action.payload };
    case 'SET_ANALYSIS_ERROR':
      return { ...state, analysisError: action.payload };
    case 'SET_SEARCH_RESULT':
      return { ...state, searchResult: action.payload };
    case 'SET_LLM_RESULT':
      return { ...state, llmResult: action.payload };
    case 'SET_LLM_LOADING':
      return { ...state, llmLoading: action.payload };
    case 'SET_VIEW_MODE':
      return { ...state, viewMode: action.payload };
    case 'SET_HIDE_NO_MATCH':
      return { ...state, hideNoMatch: action.payload };
    case 'SET_BATCH_ID':
      return { ...state, batchId: action.payload };
    case 'SET_BATCH_STATUS':
      return { ...state, batchStatus: action.payload };
    case 'SET_ANALYSIS_RESULTS':
      return {
        ...state,
        searchResult: action.payload.searchResult,
        llmResult: action.payload.llmResult,
      };
    case 'RESET_UPLOAD':
      return {
        ...state,
        sessionId: null,
        rtfFile: null,
        rtfUploadStatus: 'idle',
        rtfError: null,
        dialogue: null,
        dictionaries: [],
        dictionaryUploadStatus: 'idle',
        dictionaryError: null,
        analysisId: null,
        analysisStatus: 'idle',
        analysisError: null,
        searchResult: null,
        llmResult: null,
        batchId: null,
        batchStatus: null,
      };
    default:
      return state;
  }
}

// ═══════════════════════════════════════════════════════════
// Context
// ═══════════════════════════════════════════════════════════

interface AnalysisContextValue {
  state: AnalysisState;
  dispatch: React.Dispatch<AnalysisAction>;
}

const AnalysisContext = createContext<AnalysisContextValue | null>(null);

export function AnalysisProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(analysisReducer, initialState);

  return (
    <AnalysisContext.Provider value={{ state, dispatch }}>
      {children}
    </AnalysisContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAnalysisContext(): AnalysisContextValue {
  const context = useContext(AnalysisContext);
  if (!context) {
    throw new Error(
      'useAnalysisContext must be used within an AnalysisProvider',
    );
  }
  return context;
}
