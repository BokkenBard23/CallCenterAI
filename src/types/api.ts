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
  file: File;
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
