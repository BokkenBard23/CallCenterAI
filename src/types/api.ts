/**
 * TypeScript interfaces matching the actual backend API models.
 * Source of truth: backend/app/models.py
 *
 * CRITICAL: These types mirror the backend contract exactly.
 * Do NOT transform data from the API — pass as-is.
 */

import type { DisplayToken } from './speechlab';

// ═══════════════════════════════════════════════════════════
// RTF Upload Models
// ═══════════════════════════════════════════════════════════

export interface DialogueTurn {
  turn_index: number;
  speaker: string;
  text: string;
  timestamp: string | null;
  /** UI-2.6: turn start offset in seconds from dialogue start (null when RTF lacks timing). */
  start_offset?: number | null;
  /** UI-2.6: turn end offset in seconds from dialogue start (null when RTF lacks timing). */
  end_offset?: number | null;
}

export interface UploadRtfResponse {
  session_id: string;
  dialogue: DialogueTurn[] | null;
  turn_count: number;
  raw_text_length: number;
  error: string | null;
}

// ═══════════════════════════════════════════════════════════
// Dictionary Upload Models
// ═══════════════════════════════════════════════════════════

export interface PhraseGroupVisual {
  words: string[];
  is_or_group: boolean;
  is_exception: boolean;
}

// ═══════════════════════════════════════════════════════════
// ExtraLimitations (UI-2.6 time-gap limits from <ExtraLimitations>)
// Mirrors backend ExtraLimitation / ExtraLimitationLimit in models.py.
// ═══════════════════════════════════════════════════════════

/** Mirrors backend ExtraLimitationLimit. Optional member of ExtraLimitation.limits. */
export interface ExtraLimitationLimit {
  value: number;
  /** "Seconds" | "Words" | ... */
  value_type: string;
  /** "CLIENT" | "OPERATOR" | "ANY" */
  channel: string;
  enabled: boolean;
  /** "First" | "Last" — only for EventType=StartEnd */
  limit_type?: string | null;
  /** "Each" | "First" | ... — only for EventType=Parent */
  event_selector?: string | null;
  /** "Before" | "After" — only for EventType=Parent */
  search_direction?: string | null;
}

/** Mirrors backend ExtraLimitation. Optional on DictionaryCondition. */
export interface ExtraLimitation {
  /** "StartEnd" | "Parent" | "" */
  event_type: string;
  /** "OnlyInGaps" | "ExcludeGaps" | ... */
  search_specifier: string;
  settings: Record<string, unknown>;
  limits: ExtraLimitationLimit[];
}

/** Mirrors backend SavedState. Optional on DictionaryNode. */
export interface SavedState {
  total_found: number;
  last_update_time: string | null;
  execution_time: string | null;
  is_actual: boolean;
  is_cancelled: boolean;
}

/**
 * Mirrors backend AttributeSection. Optional on DictionaryNode.
 * Permissive shape — FE does not render attributes yet.
 */
export interface AttributeSection {
  [key: string]: unknown;
}

export interface DictionaryCondition {
  text: string;
  word_distance: number;
  word_count: number;
  channel_constraint: string;
  without_list: string[];
  /** Whether the condition uses exact (TERMINAL) match — quotes in XML, no morphology/reordering */
  is_exact: boolean;
  /** OR-groups for visualization */
  phrase_groups?: PhraseGroupVisual[];
  /** Nested phrase arrays after the main phrase */
  nested_phrases?: string[];
  /** Whether this condition is an exception (НЕ prefix) */
  is_exception?: boolean;
  /** Exception phrases (prefixed with НЕ) */
  exception_phrases?: string[];
  /** UI-2.6: real XML time-gap limits (NOT phrase-WITHOUT). Optional — FE may not render. */
  extra_limitations?: ExtraLimitation[];
}

export interface DictionaryNode {
  id: string;
  name: string;
  parent_name: string | null;
  conditions: DictionaryCondition[];
  children: DictionaryNode[];
  condition_count: number;
  has_children: boolean;
  children_count: number;
  /** UI-2.6: SavedState from XML (TotalFound, LastUpdateTime, ExecutionTime, IsActual, IsCancelled). Optional. */
  saved_state?: SavedState | null;
  /** UI-2.6: Attributes section (AttributeTokens). Optional. */
  attributes?: AttributeSection | null;
  /** UI-2.6: whether this node is a <SpeechLabRemainderRequest> catch-all. */
  is_remainder?: boolean;
  // NOTE: token_section, phrase_groups (internal), attribute_tree are NOT
  // exposed to FE — they are BE-internal. See backend/app/models.py.
}

export interface DictionaryValidation {
  valid: boolean;
  warnings: string[];
  errors: string[];
}

export interface UploadDictionaryResponse {
  session_id: string;
  dictionary: DictionaryNode | null;
  validation: DictionaryValidation;
  error: string | null;
  /** Pre-computed display tokens for the root dictionary (from backend group_into_display_tokens) */
  display_tokens?: DisplayToken[] | null;
}

// ═══════════════════════════════════════════════════════════
// Analysis Models (FRONTEND CONTRACT — do NOT change)
// ═══════════════════════════════════════════════════════════

export interface TextSegment {
  turn_index: number;
  text: string;
  speaker: string;
}

export interface DictMatch {
  phrase_text: string;
  /** Actual matched text from the dialog (for highlighting) — may differ from phrase_text */
  matched_text: string;
  /** Character offset of match start in turn text (-1 = not computed) */
  matched_start: number;
  /** Character offset of match end in turn text (-1 = not computed) */
  matched_end: number;
  /** Dictionary name or hierarchy level identifier (e.g. "level_1", "Риск расторжения") */
  quarter: string;
  turn_index: number;
  speaker: string;
  match_type: string;
  word_distance_used: number;
  /** Dictionary position in cascade sequence (1-based) */
  cascade_order: number;
  /** Whether this match was exact (TERMINAL quotes in XML — no morphology, no reordering) */
  is_exact_match: boolean;
  /** Channel constraint from dictionary condition: CLIENT, OPERATOR, or ANY */
  channel_constraint?: string;
  /** Original word_distance from dictionary condition (0=adjacent, 1=1 gap, etc.) */
  word_distance?: number;
  /** UI-2.6: dictionary level (alias for word_distance_used hierarchy level). Optional — FE may not use it. */
  dict_level?: number;
  /** UI-2.6: whether this match is from a SpeechLabRemainderRequest catch-all node. */
  is_remainder?: boolean;
}

export interface SearchResult {
  segments: TextSegment[];
  total_matches: number;
  matches: DictMatch[];
  /** Match counts by hierarchy level, e.g. {"1": 2, "2": 1} */
  matches_by_level: Record<string, number>;
}

export interface AnalysisRequest {
  session_id: string;
  dictionary_ids?: string[];
  llm_provider: string;
  llm_model?: string;
  include_summary?: boolean;
  include_restructured?: boolean;
}

// ═══════════════════════════════════════════════════════════
// LLM Models
// ═══════════════════════════════════════════════════════════

export interface LLMResult {
  summary: string;
  /** Plain text restructured dialogue — may need parsing into speaker/text pairs */
  restructured_dialogue: string;
  topic: string;
  result: string;
  key_points: string[];
  /** "positive" | "neutral" | "negative" | "mixed" */
  client_sentiment: string;
  /** "resolved" | "unresolved" | "escalated" | "partial" */
  resolution: string;
  provider: string;
  model: string;
  raw_response?: unknown;
}

// ═══════════════════════════════════════════════════════════
// Analysis Response
// ═══════════════════════════════════════════════════════════

export interface AnalysisResponse {
  analysis_id: string;
  session_id: string;
  /** "pending" | "running" | "completed" | "failed" | "partial" */
  status: string;
  search_result: SearchResult | null;
  llm_result: LLMResult | null;
  error: string | null;
  warning: string | null;
}

// ═══════════════════════════════════════════════════════════
// Provider Models
// ═══════════════════════════════════════════════════════════

export interface ProviderInfo {
  id: string;
  name: string;
  models: string[];
  configured: boolean;
  available: boolean;
}

export interface ProvidersResponse {
  providers: ProviderInfo[];
}

// ═══════════════════════════════════════════════════════════
// Health Check
// ═══════════════════════════════════════════════════════════

export interface HealthResponse {
  status: string;
  version: string;
}

export interface UploadedDictionary {
  /**
   * Original File handle. Optional: SpeechLab upload flow performs the upload
   * via API in LeftPanel and discards the File afterwards — there is no File
   * to retain. UploadPage still passes the original File. The field is unused
   * downstream in production code beyond storage.
   */
  file?: File;
  response: UploadDictionaryResponse;
}

// ═══════════════════════════════════════════════════════════
// Batch Analysis Models (mirrors backend/app/models.py)
// ═══════════════════════════════════════════════════════════

export interface BatchItemStatus {
  filename: string;
  /** "pending" | "processing" | "completed" | "failed" */
  status: string;
  analysis_id: string | null;
  total_matches: number;
  matches_by_level: Record<string, number>;
  error: string | null;
}

export interface BatchAnalysisResponse {
  batch_id: string;
  session_id: string;
  total_files: number;
  /** "pending" | "processing" | "completed" | "partial" | "failed" */
  status: string;
  items: BatchItemStatus[];
  completed_count: number;
  failed_count: number;
  error: string | null;
}

// ═══════════════════════════════════════════════════════════
// History Models
// ═══════════════════════════════════════════════════════════

export interface HistoryEntry {
  id: string;
  analysisId: string;
  sessionId: string;
  date: string;
  fileName: string;
  dictionaryNames: string[];
  totalMatches: number;
  matchesByLevel: Record<string, number>;
  status: 'completed' | 'partial' | 'failed';
  searchResult?: SearchResult;
  llmResult?: LLMResult;
}

// ═══════════════════════════════════════════════════════════
// App State Types
// ═══════════════════════════════════════════════════════════

export type UploadStatus = 'idle' | 'uploading' | 'success' | 'error';
export type AnalysisStatus = 'idle' | 'analyzing' | 'completed' | 'error';
export type ProviderStatus = 'loading' | 'loaded' | 'error';
// N.MAJ.3 FIX (PHASE N audit): the 'structure' view mode was declared in
// the union but never implemented — ResultsPage renders only two tabs
// ("Сводка" and "Выделенный текст") and the activeTabIndex ternary mapped
// tabIndex=2 to 'structure' with no matching <Tab>. Removed from the union
// to prevent dead code paths. Tracked in TODO_AND_ROADMAP.md for future
// implementation if needed.
export type ViewMode = 'summary' | 'highlighted';

// ═══════════════════════════════════════════════════════════
// FRIDA Embeddings Models
// ═══════════════════════════════════════════════════════════

export interface EmbeddingIndexRequest {
  session_id: string;
  chunk_type?: string;
}

export interface EmbeddingIndexResponse {
  session_id: string;
  chunks_indexed: number;
  vectors_stored: number;
}

export interface SearchRequest {
  query: string;
  session_id?: string;
  top_k?: number;
  use_semantic?: boolean;
  use_ner?: boolean;
  include_llm_summary?: boolean;
}

export interface VectorSearchResult {
  chunk_id: string;
  text: string;
  dialogue_id: string;
  turn_index: number;
  speaker: string;
  score: number;
  chunk_type: string;
  entities: Array<{ text: string; type: string; normal?: string }>;
}

export interface HybridSearchResult {
  text: string;
  dialogue_id: string;
  turn_index: number;
  speaker: string;
  morph_score: number;
  semantic_score: number;
  ner_boost: number;
  matched_entities: string[];
  combined_score: number;
  source: 'morph' | 'semantic' | 'hybrid' | 'ner_boost';
}

export interface SearchResponse<TResult = HybridSearchResult> {
  results: TResult[];
  query: string;
  total: number;
}

export interface EmbeddingStatusResponse {
  frida_available: boolean;
  vectors_stored: number;
  unique_dialogues: number;
  index_size_bytes: number;
  nlp_provider: 'natasha' | 'deeppavlov' | 'none';
  natasha_available: boolean;
  deeppavlov_available: boolean;
}

/** Search type toggle for SemanticSearchPanel */
export type SearchType = 'semantic' | 'hybrid';

/** Search history entry stored in localStorage */
export interface SearchHistoryEntry {
  query: string;
  timestamp: string;
  resultCount: number;
  searchType: SearchType;
}

// ═══════════════════════════════════════════════════════════
// Feedback Models
// ═══════════════════════════════════════════════════════════

export interface FeedbackRequest {
  session_id: string;
  phrase_text: string;
  matched_text: string;
  turn_index: number;
  feedback_text: string;
  channel_constraint?: string;
  word_distance?: number;
  is_exact?: boolean;
}

export interface FeedbackResponse {
  feedback_id: string;
  status: string;
  timestamp: string;
}

// ═══════════════════════════════════════════════════════════
// Quality Scoring Models (mirrors backend/app/models.py)
// ═══════════════════════════════════════════════════════════

/** Quality level enum — matches backend QualityLevel */
export type QualityLevel = 'high' | 'medium' | 'low';

/** Quality category enum — matches backend QualityCategory (12 categories) */
export type QualityCategory =
  | 'communication_skills'
  | 'problem_solving'
  | 'product_knowledge'
  | 'responsiveness'
  | 'professionalism'
  | 'empathy'
  | 'accuracy'
  | 'efficiency'
  | 'follow_up_procedures'
  | 'conflict_resolution'
  | 'compliance'
  | 'customer_education';

/** Russian labels for quality categories */
export const QUALITY_CATEGORY_LABELS: Record<QualityCategory, string> = {
  communication_skills: 'Навыки общения',
  problem_solving: 'Решение проблем',
  product_knowledge: 'Знание продукта',
  responsiveness: 'Отзывчивость',
  professionalism: 'Профессионализм',
  empathy: 'Эмпатия',
  accuracy: 'Точность',
  efficiency: 'Эффективность',
  follow_up_procedures: 'Порядок последующих действий',
  conflict_resolution: 'Разрешение конфликтов',
  compliance: 'Соблюдение стандартов',
  customer_education: 'Обучение клиента',
};

/** All 12 quality categories in stable order for radar chart */
export const QUALITY_CATEGORIES: QualityCategory[] = [
  'communication_skills',
  'problem_solving',
  'product_knowledge',
  'responsiveness',
  'professionalism',
  'empathy',
  'accuracy',
  'efficiency',
  'follow_up_procedures',
  'conflict_resolution',
  'compliance',
  'customer_education',
];

/** Score for a single quality category */
export interface CategoryScore {
  category: QualityCategory;
  level: QualityLevel;
  score: number;
  justification: string;
}

/** Full quality scoring result */
export interface QualityScoreResult {
  session_id: string;
  categories: CategoryScore[];
  overall_score: number;
  overall_level: QualityLevel;
  strengths: string[];
  weaknesses: string[];
  recommendations: string[];
  provider: string;
  model: string;
}

/** Request body for quality scoring */
export interface QualityScoreRequest {
  session_id: string;
  provider_id?: string;
}

// ═══════════════════════════════════════════════════════════
// Dictionary Editing & Analysis (UI-3)
// Mirrors backend DTOs from:
//   - backend/app/routers/dictionary.py (request/response DTOs)
//   - backend/app/services/dict_utils.py (DuplicateReport, DictionaryStats, ValidationResult)
//   - backend/app/services/dictionary_ai.py (DictionarySuggestion, DictionaryAnalysisResult)
// ═══════════════════════════════════════════════════════════

/** Body for POST /nodes. */
export interface NodeCreateRequest {
  name: string;
  parent_name?: string | null;
}

/** Body for PATCH /nodes/{node_id}. All fields optional. */
export interface NodeUpdateRequest {
  name?: string;
  saved_state?: SavedState | null;
  attributes?: AttributeSection | null;
}

/** Body for POST /nodes/{node_id}/conditions. */
export interface ConditionCreateRequest {
  text: string;
  word_distance?: number;
  channel_constraint?: string;
  is_exact?: boolean;
  is_exception?: boolean;
  phrase_groups?: PhraseGroupVisual[];
  open_brackets?: number;
  close_brackets?: number;
  /** Operator preceding this condition: "" | "И" | "ИЛИ" | "НЕ" | "И НЕ" | "ИЛИ НЕ". */
  logic_operator?: string;
}

/** Body for PATCH /nodes/{node_id}/conditions/{idx}. All fields optional. */
export type ConditionUpdateRequest = Partial<ConditionCreateRequest>;

/** Body for POST /nodes/{node_id}/conditions/reorder. */
export interface ReorderRequest {
  /** Old condition indices in the desired new order. Must be a permutation of range(n). */
  new_order: number[];
}

/** Body for POST /analyze-ai. */
export interface AnalyzeAiRequest {
  dict_name?: string | null;
  provider_id?: string | null;
}

/** Body for POST /suggest-phrases. */
export interface SuggestPhrasesRequest {
  dict_name?: string | null;
  provider_id?: string | null;
  count?: number;
}

/** Body for endpoints that only need a dict_name (duplicates/stats/validate). */
export interface DictNameRequest {
  dict_name?: string | null;
}

/** Body for POST /export-xml. */
export interface ExportXmlRequest {
  dict_name?: string | null;
  pretty?: boolean;
}

// --- Response shapes ---

/** Response for POST /conditions. */
export interface ConditionCreateResponse {
  condition: DictionaryCondition;
  index: number;
}

/** Response for DELETE endpoints. */
export interface DeleteResponse {
  deleted: boolean;
  node_name?: string | null;
  condition_idx?: number | null;
}

/** Response for POST /conditions/reorder. */
export interface ReorderResponse {
  conditions: DictionaryCondition[];
}

/** Response for POST /suggest-phrases. */
export interface SuggestPhrasesResponse {
  suggestions: DictionarySuggestion[];
}

/** Mirrors backend DictionarySuggestion (dictionary_ai.py). */
export interface DictionarySuggestion {
  phrase: string;
  /** "ANY" | "OPERATOR" | "CLIENT" */
  channel: string;
  distance: number;
}

/** Mirrors backend DictionaryAnalysisResult (dictionary_ai.py). */
export interface DictionaryAnalysisResult {
  summary: string;
  examples: string[];
  recommendations: string[];
  raw_response: string;
}

/** Mirrors backend DupPair (dict_utils.py). */
export interface DupPair {
  row_a: number;
  row_b: number;
  /** Normalised phrase text (or shared key). */
  phrase: string;
  is_exact_a: boolean;
  is_exact_b: boolean;
}

/** Mirrors backend DuplicateReport (dict_utils.py). */
export interface DuplicateReport {
  /** Identical phrases including is_exact flag (true duplicates). */
  full: DupPair[];
  /** Same word set but differ in quoting, channel, or word distance. */
  soft: DupPair[];
}

/** Mirrors backend WordFreq (dict_utils.py). */
export interface WordFreq {
  word: string;
  count: number;
}

/** Mirrors backend DictionaryStats (dict_utils.py). */
export interface DictionaryStats {
  total_conditions: number;
  total_words: number;
  unique_words: number;
  operators_count: Record<string, number>;
  brackets_count: number;
  channels_distribution: Record<string, number>;
}

/** Mirrors backend ValidationIssue (dict_utils.py). */
export interface ValidationIssue {
  /** Row index (-1 = global). */
  row: number;
  /** "error" | "warning" */
  severity: string;
  message: string;
}

/** Mirrors backend ValidationResult (dict_utils.py). */
export interface ValidationResult {
  errors: ValidationIssue[];
  warnings: ValidationIssue[];
}

// ═══════════════════════════════════════════════════════════
// Mining (Track B) — offline corpus mining layer
// Mirrors backend/app/models.py mining models (B.1 Backend).
// See docs/specs/spec.md → API контракт → Request/Response schemas.
// FROZEN: existing types above are NOT modified. Only ADDITIVE.
// ═══════════════════════════════════════════════════════════

/** LLM confidence label for false-negative candidates (mirror ConfidenceLabel enum). */
export type ConfidenceLabel = 'relevant' | 'irrelevant' | 'uncertain';

/** Mining job lifecycle status (mirror backend Literal). */
export type MiningJobStatusKind =
  | 'pending'
  | 'running'
  | 'completed'
  | 'failed'
  | 'partial'
  | 'cancelled';

/** Body for POST /mining/index. */
export interface IndexCorpusRequest {
  /** Existing session with the loaded dictionary. */
  session_id: string;
  /** Absolute path to RTF directory (browser-limited via webkitdirectory; UI sends file list, BE resolves path). */
  directory_path: string;
  /** Root DictionaryNode.name to mine against. */
  dictionary_id: string;
}

/** Response for POST /mining/index (202 Accepted). */
export interface IndexCorpusResponse {
  job_id: string;
  status: 'pending' | 'running';
  total_dialogues: number;
  message: string;
}

/** GET /mining/status/{job_id} response — polling payload. */
export interface MiningJobStatus {
  job_id: string;
  status: MiningJobStatusKind;
  /** 0.0–1.0 progress fraction. */
  progress: number;
  processed_dialogues: number;
  total_dialogues: number;
  /** ISO-8601 last checkpoint timestamp. */
  checkpoint_at: string | null;
  started_at: string;
  completed_at: string | null;
  error: string | null;
  /** Set when status=partial (LLM rate limited). */
  warning: string | null;
  /**
   * Result payload when status=completed/partial.
   * Discriminated by job kind: FindFNJobResult for find_fn, AuditJobResult for audit.
   * Indexing jobs do not populate this.
   */
  result?: FindFNJobResult | AuditJobResult | null;
}

/** Top-k similar dialogue row (mirror backend SimilarDialogue). */
export interface SimilarDialogue {
  dialogue_id: string;
  file_path: string;
  /** First N characters of the dialogue text. */
  snippet: string;
  /** Cosine similarity 0–1. */
  score: number;
  /** "CLIENT" | "OPERATOR" | "ANY". */
  channel: string;
  turn_count: number;
}

/** Body for POST /mining/find_similar. */
export interface FindSimilarRequest {
  session_id: string;
  /** Completed indexing job_id. */
  job_id: string;
  /** PhraseGroup id (or phrase text fallback). */
  phrase_group_id: string;
  top_k?: number;
}

/** Response for POST /mining/find_similar. */
export interface FindSimilarResponse {
  phrase_group_id: string;
  total: number;
  dialogues: SimilarDialogue[];
}

/** False-negative candidate row (mirror backend FNCandidate). */
export interface FNCandidate {
  dialogue_id: string;
  file_path: string;
  snippet: string;
  /** Vector similarity 0–1. */
  score: number;
  llm_label: ConfidenceLabel;
  /** LLM confidence 0–1. */
  llm_score: number;
  /** One-sentence LLM justification. */
  llm_reason: string;
  /** LLM-proposed phrase for click-to-add (nullable). */
  proposed_phrase: string | null;
}

/** Body for POST /mining/find_fn. */
export interface FindFNRequest {
  session_id: string;
  job_id: string;
  dictionary_id: string;
  /** Min vector similarity for FN candidate. */
  threshold?: number;
}

/** Response for POST /mining/find_fn (synchronous short version). */
export interface FindFNResponse {
  job_id: string;
  dictionary_id: string;
  total: number;
  candidates: FNCandidate[];
  partial: boolean;
}

/** Job result payload nested in MiningJobStatus for find_fn jobs (status=completed). */
export interface FindFNJobResult {
  candidates: FNCandidate[];
}

/** Audit recommendation (mirror backend AuditRecommendation). */
export interface AuditRecommendation {
  type: 'add_phrase' | 'remove_phrase' | 'adjust_word_distance' | 'add_exception';
  phrase: string;
  reason: string;
  /** Set for adjust_word_distance. */
  word_distance?: number | null;
}

/** Per-PhraseGroup audit block (mirror backend PhraseGroupAudit). */
export interface PhraseGroupAudit {
  phrase_group_id: string;
  /** Joined phrase text for the group. */
  phrase_text: string;
  /** Coverage recall 0–1. */
  recall: number;
  /** Count of relevant dialogues the group misses. */
  missed_count: number;
  recommendations: AuditRecommendation[];
  /** Markdown explanation from LLM. */
  llm_explanation: string;
}

/** Body for POST /mining/audit. */
export interface AuditRequest {
  session_id: string;
  job_id: string;
  dictionary_id: string;
}

/** Response for POST /mining/audit (synchronous short version). */
export interface AuditResponse {
  job_id: string;
  dictionary_id: string;
  phrase_groups: PhraseGroupAudit[];
  partial: boolean;
}

/** Job result payload nested in MiningJobStatus for audit jobs (status=completed). */
export interface AuditJobResult {
  phrase_groups: PhraseGroupAudit[];
}

/** Response for POST /mining/cancel/{job_id}. */
export interface CancelMiningResponse {
  status: 'cancelled';
}
