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
  QualityScoreRequest,
  QualityScoreResult,
  DictionaryNode,
  DictionaryCondition,
  NodeCreateRequest,
  NodeUpdateRequest,
  ConditionCreateRequest,
  ConditionUpdateRequest,
  ReorderRequest,
  AnalyzeAiRequest,
  SuggestPhrasesRequest,
  DictNameRequest,
  ExportXmlRequest,
  ConditionCreateResponse,
  DeleteResponse,
  ReorderResponse,
  SuggestPhrasesResponse,
  DictionaryAnalysisResult,
  DuplicateReport,
  DictionaryStats,
  ValidationResult,
  // Track B Mining (additive — frozen existing types untouched)
  IndexCorpusRequest,
  IndexCorpusResponse,
  MiningJobStatus,
  FindSimilarRequest,
  FindSimilarResponse,
  FindFNRequest,
  FindFNResponse,
  AuditRequest,
  AuditResponse,
  CancelMiningResponse,
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
  return request<HealthResponse>('/api/health', { signal });
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
  return request<ProvidersResponse>('/api/providers', { signal });
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
// Export (Excel / PDF)
// ═══════════════════════════════════════════════════════════

export async function exportExcel(
  sessionId: string,
  signal?: AbortSignal,
): Promise<Blob> {
  const url = `${API_BASE}/api/export/${sessionId}/excel`;
  const response = await fetch(url, { signal });
  if (!response.ok) {
    let body: unknown;
    try { body = await response.json(); } catch { /* ignore */ }
    throw new ApiError(
      (body as { detail?: string })?.detail ?? `HTTP ${response.status}`,
      response.status,
      body,
    );
  }
  return response.blob();
}

export async function exportPdf(
  sessionId: string,
  signal?: AbortSignal,
): Promise<Blob> {
  const url = `${API_BASE}/api/export/${sessionId}/pdf`;
  const response = await fetch(url, { signal });
  if (!response.ok) {
    let body: unknown;
    try { body = await response.json(); } catch { /* ignore */ }
    throw new ApiError(
      (body as { detail?: string })?.detail ?? `HTTP ${response.status}`,
      response.status,
      body,
    );
  }
  return response.blob();
}

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

// ═══════════════════════════════════════════════════════════
// Quality Scoring
// ═══════════════════════════════════════════════════════════

export async function getQualityScore(
  qualityRequest: QualityScoreRequest,
  signal?: AbortSignal,
): Promise<QualityScoreResult> {
  return request<QualityScoreResult>('/api/analysis/quality-score', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(qualityRequest),
    signal,
  });
}

// ═══════════════════════════════════════════════════════════
// Dictionary Editing & Analysis (UI-3)
// Endpoints under /api/dictionary/{session_id}/...
// See backend/app/routers/dictionary.py for the canonical contract.
// ═══════════════════════════════════════════════════════════

/**
 * GET /api/dictionary/{session_id}
 * Fetch all root dictionaries (with full subtrees) stored in a session.
 * Used by the DictionaryEditorPage to render the navigation tree on mount.
 */
export async function getDictionaryTree(
  sessionId: string,
  signal?: AbortSignal,
): Promise<DictionaryNode[]> {
  return request<DictionaryNode[]>(`/api/dictionary/${sessionId}`, {
    signal,
  });
}

/**
 * POST /api/dictionary/{session_id}/nodes
 * Add a new dictionary node (root dictionary when parent_name omitted).
 */
export async function addDictionaryNode(
  sessionId: string,
  body: NodeCreateRequest,
  signal?: AbortSignal,
): Promise<DictionaryNode> {
  return request<DictionaryNode>(`/api/dictionary/${sessionId}/nodes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });
}

/**
 * PATCH /api/dictionary/{session_id}/nodes/{node_id}
 * Update node metadata (name / saved_state / attributes).
 */
export async function updateDictionaryNode(
  sessionId: string,
  nodeId: string,
  body: NodeUpdateRequest,
  signal?: AbortSignal,
): Promise<DictionaryNode> {
  return request<DictionaryNode>(
    `/api/dictionary/${sessionId}/nodes/${encodeURIComponent(nodeId)}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    },
  );
}

/**
 * DELETE /api/dictionary/{session_id}/nodes/{node_id}
 * Remove a node (and its subtree). `dict_name` restricts search to one root.
 */
export async function deleteDictionaryNode(
  sessionId: string,
  nodeId: string,
  dictName?: string | null,
  signal?: AbortSignal,
): Promise<DeleteResponse> {
  const query = dictName ? `?dict_name=${encodeURIComponent(dictName)}` : '';
  return request<DeleteResponse>(
    `/api/dictionary/${sessionId}/nodes/${encodeURIComponent(nodeId)}${query}`,
    {
      method: 'DELETE',
      signal,
    },
  );
}

/**
 * POST /api/dictionary/{session_id}/nodes/{node_id}/conditions
 * Add a new condition to a node. Returns the created condition + its index.
 */
export async function addDictionaryCondition(
  sessionId: string,
  nodeId: string,
  body: ConditionCreateRequest,
  dictName?: string | null,
  signal?: AbortSignal,
): Promise<ConditionCreateResponse> {
  const query = dictName ? `?dict_name=${encodeURIComponent(dictName)}` : '';
  return request<ConditionCreateResponse>(
    `/api/dictionary/${sessionId}/nodes/${encodeURIComponent(nodeId)}/conditions${query}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    },
  );
}

/**
 * PATCH /api/dictionary/{session_id}/nodes/{node_id}/conditions/{condition_idx}
 * Update an existing condition (partial merge).
 */
export async function updateDictionaryCondition(
  sessionId: string,
  nodeId: string,
  conditionIdx: number,
  body: ConditionUpdateRequest,
  dictName?: string | null,
  signal?: AbortSignal,
): Promise<DictionaryCondition> {
  const query = dictName ? `?dict_name=${encodeURIComponent(dictName)}` : '';
  return request<DictionaryCondition>(
    `/api/dictionary/${sessionId}/nodes/${encodeURIComponent(nodeId)}/conditions/${conditionIdx}${query}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    },
  );
}

/**
 * DELETE /api/dictionary/{session_id}/nodes/{node_id}/conditions/{condition_idx}
 * Remove a condition by index.
 */
export async function deleteDictionaryCondition(
  sessionId: string,
  nodeId: string,
  conditionIdx: number,
  dictName?: string | null,
  signal?: AbortSignal,
): Promise<DeleteResponse> {
  const query = dictName ? `?dict_name=${encodeURIComponent(dictName)}` : '';
  return request<DeleteResponse>(
    `/api/dictionary/${sessionId}/nodes/${encodeURIComponent(nodeId)}/conditions/${conditionIdx}${query}`,
    {
      method: 'DELETE',
      signal,
    },
  );
}

/**
 * POST /api/dictionary/{session_id}/nodes/{node_id}/conditions/reorder
 * Reorder conditions. `new_order` is a list of old indices in new order.
 */
export async function reorderDictionaryConditions(
  sessionId: string,
  nodeId: string,
  body: ReorderRequest,
  dictName?: string | null,
  signal?: AbortSignal,
): Promise<ReorderResponse> {
  const query = dictName ? `?dict_name=${encodeURIComponent(dictName)}` : '';
  return request<ReorderResponse>(
    `/api/dictionary/${sessionId}/nodes/${encodeURIComponent(nodeId)}/conditions/reorder${query}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    },
  );
}

/**
 * POST /api/dictionary/{session_id}/analyze-ai
 * Run LLM dictionary analysis (summary / examples / recommendations).
 */
export async function analyzeDictionaryAi(
  sessionId: string,
  body: AnalyzeAiRequest,
  signal?: AbortSignal,
): Promise<DictionaryAnalysisResult> {
  return request<DictionaryAnalysisResult>(
    `/api/dictionary/${sessionId}/analyze-ai`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    },
  );
}

/**
 * POST /api/dictionary/{session_id}/suggest-phrases
 * Generate phrase suggestions via the LLM.
 */
export async function suggestDictionaryPhrases(
  sessionId: string,
  body: SuggestPhrasesRequest,
  signal?: AbortSignal,
): Promise<SuggestPhrasesResponse> {
  return request<SuggestPhrasesResponse>(
    `/api/dictionary/${sessionId}/suggest-phrases`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    },
  );
}

/**
 * POST /api/dictionary/{session_id}/duplicates
 * Detect full and soft duplicate conditions.
 */
export async function findDictionaryDuplicates(
  sessionId: string,
  body: DictNameRequest,
  signal?: AbortSignal,
): Promise<DuplicateReport> {
  return request<DuplicateReport>(
    `/api/dictionary/${sessionId}/duplicates`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    },
  );
}

/**
 * POST /api/dictionary/{session_id}/statistics
 * Compute aggregate statistics for the dictionary tree.
 */
export async function getDictionaryStatistics(
  sessionId: string,
  body: DictNameRequest,
  signal?: AbortSignal,
): Promise<DictionaryStats> {
  return request<DictionaryStats>(
    `/api/dictionary/${sessionId}/statistics`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    },
  );
}

/**
 * POST /api/dictionary/{session_id}/validate
 * Run structural validation on the dictionary.
 */
export async function validateDictionary(
  sessionId: string,
  body: DictNameRequest,
  signal?: AbortSignal,
): Promise<ValidationResult> {
  return request<ValidationResult>(
    `/api/dictionary/${sessionId}/validate`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    },
  );
}

/**
 * POST /api/dictionary/{session_id}/export-xml
 * Export the dictionary to canonical SmartLogger XML bytes.
 * Returns a Blob (StreamingResponse, application/xml) — NOT JSON.
 */
export async function exportDictionaryXml(
  sessionId: string,
  body: ExportXmlRequest,
  signal?: AbortSignal,
): Promise<Blob> {
  const url = `${API_BASE}/api/dictionary/${sessionId}/export-xml`;
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok) {
    let errorBody: unknown;
    try {
      errorBody = await response.json();
    } catch {
      // ignore JSON parse errors for error responses
    }
    throw new ApiError(
      (errorBody as { detail?: string })?.detail ?? `HTTP ${response.status}`,
      response.status,
      errorBody,
    );
  }
  return response.blob();
}

// ═══════════════════════════════════════════════════════════
// Mining (Track B) — offline corpus mining layer
// Endpoints under /api/mining/...
// See backend/app/routers/mining.py for the canonical contract.
// FROZEN: existing functions above are NOT modified. Only ADDITIVE.
// ═══════════════════════════════════════════════════════════

/**
 * POST /api/mining/index
 * Start long-running corpus indexing (returns 202 + job_id immediately).
 */
export async function indexCorpus(
  body: IndexCorpusRequest,
  signal?: AbortSignal,
): Promise<IndexCorpusResponse> {
  return request<IndexCorpusResponse>('/api/mining/index', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });
}

/**
 * GET /api/mining/status/{job_id}
 * Poll job status. Polling interval: 2s (see useMiningState).
 */
export async function getMiningStatus(
  jobId: string,
  signal?: AbortSignal,
): Promise<MiningJobStatus> {
  return request<MiningJobStatus>(`/api/mining/status/${encodeURIComponent(jobId)}`, {
    signal,
  });
}

/**
 * POST /api/mining/cancel/{job_id}
 * Cancel a long-running job. Backend stops at the next checkpoint.
 */
export async function cancelMining(
  jobId: string,
  signal?: AbortSignal,
): Promise<CancelMiningResponse> {
  return request<CancelMiningResponse>(
    `/api/mining/cancel/${encodeURIComponent(jobId)}`,
    {
      method: 'POST',
      signal,
    },
  );
}

/**
 * POST /api/mining/find_similar
 * Find top-k dialogues similar to a phrase group.
 * Synchronous (short-running) — returns FindSimilarResponse.
 */
export async function findSimilar(
  body: FindSimilarRequest,
  signal?: AbortSignal,
): Promise<FindSimilarResponse> {
  return request<FindSimilarResponse>('/api/mining/find_similar', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });
}

/**
 * POST /api/mining/find_fn
 * Find false-negative candidates with LLM confidence.
 * Long-running → returns 202 + job_id immediately; poll via /status.
 */
export async function findFalseNegatives(
  body: FindFNRequest,
  signal?: AbortSignal,
): Promise<FindFNResponse> {
  return request<FindFNResponse>('/api/mining/find_fn', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });
}

/**
 * POST /api/mining/audit
 * LLM audit of the dictionary (per PhraseGroup: recall, missed, recommendations).
 * Long-running → returns 202 + job_id immediately; poll via /status.
 */
export async function auditDictionary(
  body: AuditRequest,
  signal?: AbortSignal,
): Promise<AuditResponse> {
  return request<AuditResponse>('/api/mining/audit', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });
}
