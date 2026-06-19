/**
 * API client for the Dialog Analysis backend.
 * All endpoints are proxied via Vite dev server (/api → localhost:8000).
 *
 * CRITICAL: Data from the API is NOT transformed — passed as-is to the frontend.
 */

import type {
  UploadRtfResponse,
  UploadDictionaryResponse,
  AnalysisRequest,
  AnalysisResponse,
  BatchAnalysisResponse,
  ProvidersResponse,
  HealthResponse,
  EmbeddingIndexRequest,
  EmbeddingIndexResponse,
  SearchRequest,
  SearchResponse,
  VectorSearchResult,
  HybridSearchResult,
  EmbeddingStatusResponse,
  FeedbackRequest,
  FeedbackResponse,
} from '../types/api';

const API_BASE = '';

class ApiError extends Error {
  status: number;
  body?: unknown;

  constructor(message: string, status: number, body?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const url = `${API_BASE}${path}`;
  const response = await fetch(url, {
    ...options,
    signal: options.signal,
  });

  if (!response.ok) {
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      // ignore JSON parse errors for error responses
    }
    throw new ApiError(
      (body as { detail?: string })?.detail ?? `HTTP ${response.status}`,
      response.status,
      body,
    );
  }

  return response.json() as Promise<T>;
}

// ═══════════════════════════════════════════════════════════
// Health
// ═══════════════════════════════════════════════════════════

export async function checkHealth(
  signal?: AbortSignal,
): Promise<HealthResponse> {
  return request<HealthResponse>('/health', { signal });
}

// ═══════════════════════════════════════════════════════════
// Upload
// ═══════════════════════════════════════════════════════════

export async function uploadRtf(
  file: File,
  sessionId?: string | null,
  signal?: AbortSignal,
): Promise<UploadRtfResponse> {
  const formData = new FormData();
  formData.append('file', file);
  if (sessionId) {
    formData.append('session_id', sessionId);
  }
  return request<UploadRtfResponse>('/api/upload/rtf', {
    method: 'POST',
    body: formData,
    signal,
  });
}

export async function uploadDictionary(
  file: File,
  sessionId?: string | null,
  signal?: AbortSignal,
): Promise<UploadDictionaryResponse> {
  const formData = new FormData();
  formData.append('file', file);
  if (sessionId) {
    formData.append('session_id', sessionId);
  }
  return request<UploadDictionaryResponse>('/api/upload/dictionary', {
    method: 'POST',
    body: formData,
    signal,
  });
}

// ═══════════════════════════════════════════════════════════
// Analysis
// ═══════════════════════════════════════════════════════════

export async function analyze(
  analysisRequest: AnalysisRequest,
  signal?: AbortSignal,
): Promise<AnalysisResponse> {
  return request<AnalysisResponse>('/api/analysis/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(analysisRequest),
    signal,
  });
}

export async function getResults(
  analysisId: string,
  signal?: AbortSignal,
): Promise<AnalysisResponse> {
  return request<AnalysisResponse>(`/api/analysis/results/${analysisId}`, {
    signal,
  });
}

// ═══════════════════════════════════════════════════════════
// Providers
// ═══════════════════════════════════════════════════════════

export async function getProviders(
  signal?: AbortSignal,
): Promise<ProvidersResponse> {
  return request<ProvidersResponse>('/api/providers/', { signal });
}

export async function getProviderStatus(
  providerId: string,
  signal?: AbortSignal,
): Promise<{ id: string; available: boolean; models: string[]; error?: string }> {
  return request(`/api/providers/${providerId}/status`, { signal });
}

// ═══════════════════════════════════════════════════════════
// Batch Analysis
// ═══════════════════════════════════════════════════════════

export async function submitBatch(
  files: File[],
  sessionId: string,
  llmProvider: string,
  llmModel?: string | null,
  includeSummary?: boolean,
  includeRestructured?: boolean,
  dictionaryIds?: string[],
  signal?: AbortSignal,
): Promise<BatchAnalysisResponse> {
  const formData = new FormData();
  files.forEach((file) => formData.append('files', file));
  formData.append('session_id', sessionId);
  formData.append('llm_provider', llmProvider);
  if (llmModel) formData.append('llm_model', llmModel);
  if (includeSummary) formData.append('include_summary', 'true');
  if (includeRestructured) formData.append('include_restructured', 'true');
  if (dictionaryIds && dictionaryIds.length > 0) {
    formData.append('dictionary_ids', dictionaryIds.join(','));
  }

  return request<BatchAnalysisResponse>('/api/analysis/batch', {
    method: 'POST',
    body: formData,
    signal,
  });
}

export async function getBatchStatus(
  batchId: string,
  signal?: AbortSignal,
): Promise<BatchAnalysisResponse> {
  return request<BatchAnalysisResponse>(
    `/api/analysis/batch/${batchId}/status`,
    { signal },
  );
}

export async function getBatchResults(
  batchId: string,
  signal?: AbortSignal,
): Promise<BatchAnalysisResponse> {
  return request<BatchAnalysisResponse>(
    `/api/analysis/batch/${batchId}/results`,
    { signal },
  );
}

export { ApiError };

// ═══════════════════════════════════════════════════════════
// FRIDA Embeddings
// ═══════════════════════════════════════════════════════════

export async function indexDialogue(
  indexRequest: EmbeddingIndexRequest,
  signal?: AbortSignal,
): Promise<EmbeddingIndexResponse> {
  return request<EmbeddingIndexResponse>('/api/embeddings/index', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(indexRequest),
    signal,
  });
}

export async function searchSemantic(
  searchRequest: SearchRequest,
  signal?: AbortSignal,
): Promise<SearchResponse<VectorSearchResult>> {
  return request<SearchResponse<VectorSearchResult>>(
    '/api/embeddings/search/semantic',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(searchRequest),
      signal,
    },
  );
}

export async function searchHybrid(
  searchRequest: SearchRequest,
  signal?: AbortSignal,
): Promise<SearchResponse<HybridSearchResult>> {
  return request<SearchResponse<HybridSearchResult>>(
    '/api/embeddings/search/hybrid',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(searchRequest),
      signal,
    },
  );
}

export async function getEmbeddingStatus(
  signal?: AbortSignal,
): Promise<EmbeddingStatusResponse> {
  return request<EmbeddingStatusResponse>('/api/embeddings/status', {
    signal,
  });
}

// ═══════════════════════════════════════════════════════════
// Feedback
// ═══════════════════════════════════════════════════════════

export async function submitFeedback(
  feedbackRequest: FeedbackRequest,
  signal?: AbortSignal,
): Promise<FeedbackResponse> {
  return request<FeedbackResponse>('/api/feedback', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(feedbackRequest),
    signal,
  });
}
