/**
 * useMiningState — custom polling hook for Track B MiningPanel.
 *
 * NOT TanStack Query (rejected in 6 prior UI audits). Uses useRef + setInterval
 * polling with AbortController for cancellation on unmount.
 *
 * Manages 3 long-running jobs (index, find_fn, audit) + 1 synchronous call
 * (find_similar). Each long-running job returns job_id immediately (202);
 * client polls GET /mining/status/{job_id} every 2s until terminal state
 * (completed | failed | partial | cancelled).
 *
 * Frozen invariants preserved: does NOT touch xml_parser/search/morph_matcher.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  auditDictionary,
  cancelMining,
  findFalseNegatives,
  findSimilar,
  getMiningStatus,
  indexCorpus,
} from '../api/client';
import type {
  AuditResponse,
  FNCandidate,
  FindFNResponse,
  FindSimilarResponse,
  IndexCorpusResponse,
  MiningJobStatus,
  PhraseGroupAudit,
} from '../types/api';

const POLL_INTERVAL_MS = 2000;
const TERMINAL_STATES = new Set(['completed', 'failed', 'partial', 'cancelled']);


export interface UseMiningState {
  // Jobs
  indexJob: MiningJobStatus | null;
  fnJob: MiningJobStatus | null;
  auditJob: MiningJobStatus | null;

  // Synchronous results
  similarResults: FindSimilarResponse | null;
  fnCandidates: FNCandidate[] | null;
  auditResults: PhraseGroupAudit[] | null;

  // Partial flags (LLM rate limited)
  fnPartial: boolean;
  auditPartial: boolean;

  // Loading flags
  loadingSimilar: boolean;
  loadingFN: boolean;
  loadingAudit: boolean;
  cancelling: boolean;

  // Errors
  errors: {
    index: string | null;
    findSimilar: string | null;
    findFN: string | null;
    audit: string | null;
  };

  // Actions
  indexCorpus: (directoryPath: string, dictionaryId: string) => Promise<void>;
  findSimilar: (phraseGroupId: string, topK?: number) => Promise<void>;
  findFalseNegatives: (dictionaryId: string, threshold?: number) => Promise<void>;
  auditDictionary: (dictionaryId: string) => Promise<void>;
  cancelJob: (jobId: string) => Promise<void>;
}

export function useMiningState(sessionId: string): UseMiningState {
  const [indexJob, setIndexJob] = useState<MiningJobStatus | null>(null);
  const [fnJob, setFnJob] = useState<MiningJobStatus | null>(null);
  const [auditJob, setAuditJob] = useState<MiningJobStatus | null>(null);
  const [similarResults, setSimilarResults] = useState<FindSimilarResponse | null>(null);
  const [fnCandidates, setFnCandidates] = useState<FNCandidate[] | null>(null);
  const [auditResults, setAuditResults] = useState<PhraseGroupAudit[] | null>(null);
  const [fnPartial, setFnPartial] = useState(false);
  const [auditPartial, setAuditPartial] = useState(false);
  const [loadingSimilar, setLoadingSimilar] = useState(false);
  const [loadingFN, setLoadingFN] = useState(false);
  const [loadingAudit, setLoadingAudit] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [errors, setErrors] = useState<UseMiningState['errors']>({
    index: null,
    findSimilar: null,
    findFN: null,
    audit: null,
  });

  // Track active job_ids for polling. Using refs so polling loop reads latest.
  const indexJobIdRef = useRef<string | null>(null);
  const fnJobIdRef = useRef<string | null>(null);
  const auditJobIdRef = useRef<string | null>(null);
  const mountedRef = useRef(true);
  const abortControllersRef = useRef<Map<string, AbortController>>(new Map());

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      abortControllersRef.current.forEach((ac) => ac.abort());
      abortControllersRef.current.clear();
    };
  }, []);

  const getOrCreateController = useCallback((key: string): AbortController => {
    const existing = abortControllersRef.current.get(key);
    if (existing) return existing;
    const ac = new AbortController();
    abortControllersRef.current.set(key, ac);
    return ac;
  }, []);

  const abortController = useCallback((key: string) => {
    const ac = abortControllersRef.current.get(key);
    if (ac) {
      ac.abort();
      abortControllersRef.current.delete(key);
    }
  }, []);

  const setError = useCallback((key: keyof UseMiningState['errors'], msg: string | null) => {
    if (!mountedRef.current) return;
    setErrors((prev) => ({ ...prev, [key]: msg }));
  }, []);

  // ---- Polling loop ----
  const pollJob = useCallback(
    async (jobId: string, kind: 'index' | 'fn' | 'audit'): Promise<void> => {
      const controllerKey = `${kind}:${jobId}`;
      while (mountedRef.current) {
        try {
          const signal = getOrCreateController(controllerKey).signal;
          const status: MiningJobStatus = await getMiningStatus(jobId, signal);

          if (!mountedRef.current) return;

          if (kind === 'index') setIndexJob(status);
          else if (kind === 'fn') setFnJob(status);
          else if (kind === 'audit') setAuditJob(status);

          if (TERMINAL_STATES.has(status.status)) {
            // Extract results for fn/audit from the status.result payload.
            if (kind === 'fn') {
              const r = status.result as { candidates?: FNCandidate[] } | null | undefined;
              setFnCandidates(r?.candidates ?? null);
              setFnPartial(status.status === 'partial');
            } else if (kind === 'audit') {
              const r = status.result as { phrase_groups?: PhraseGroupAudit[] } | null | undefined;
              setAuditResults(r?.phrase_groups ?? null);
              setAuditPartial(status.status === 'partial');
            }
            abortController(controllerKey);
            return;
          }

          // Non-terminal — wait then poll again.
          await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
        } catch (err) {
          if (!mountedRef.current) return;
          if (err instanceof DOMException && err.name === 'AbortError') return;
          const msg = err instanceof Error ? err.message : String(err);
          setError(
            kind === 'index' ? 'index' : kind === 'fn' ? 'findFN' : 'audit',
            `Polling failed: ${msg}`,
          );
          abortController(controllerKey);
          return;
        }
      }
    },
    [getOrCreateController, abortController, setError],
  );

  // ---- Actions ----

  const doIndex = useCallback(
    async (directoryPath: string, dictionaryId: string): Promise<void> => {
      setError('index', null);
      setLoadingFN(false);
      try {
        const res: IndexCorpusResponse = await indexCorpus({
          session_id: sessionId,
          directory_path: directoryPath,
          dictionary_id: dictionaryId,
        });
        if (!mountedRef.current) return;
        indexJobIdRef.current = res.job_id;
        // Seed an initial job object so UI shows pending immediately.
        setIndexJob({
          job_id: res.job_id,
          status: res.status,
          progress: 0,
          processed_dialogues: 0,
          total_dialogues: res.total_dialogues,
          checkpoint_at: null,
          started_at: new Date().toISOString(),
          completed_at: null,
          error: null,
          warning: null,
        });
        await pollJob(res.job_id, 'index');
      } catch (err) {
        if (!mountedRef.current) return;
        const msg = err instanceof Error ? err.message : String(err);
        setError('index', `Indexing failed: ${msg}`);
      }
    },
    [pollJob, sessionId, setError],
  );

  const doFindSimilar = useCallback(
    async (phraseGroupId: string, topK = 20): Promise<void> => {
      const jobId = indexJobIdRef.current;
      if (!jobId) {
        setError('findSimilar', 'Сначала проиндексируйте корпус.');
        return;
      }
      setError('findSimilar', null);
      setLoadingSimilar(true);
      try {
        const res: FindSimilarResponse = await findSimilar({
          session_id: sessionId,
          job_id: jobId,
          phrase_group_id: phraseGroupId,
          top_k: topK,
        });
        if (!mountedRef.current) return;
        setSimilarResults(res);
      } catch (err) {
        if (!mountedRef.current) return;
        const msg = err instanceof Error ? err.message : String(err);
        setError('findSimilar', `find_similar failed: ${msg}`);
      } finally {
        if (mountedRef.current) setLoadingSimilar(false);
      }
    },
    [sessionId, setError],
  );

  const doFindFalseNegatives = useCallback(
    async (dictionaryId: string, threshold = 0.7): Promise<void> => {
      const jobId = indexJobIdRef.current;
      if (!jobId) {
        setError('findFN', 'Сначала проиндексируйте корпус.');
        return;
      }
      setError('findFN', null);
      setLoadingFN(true);
      try {
        const res: FindFNResponse = await findFalseNegatives({
          session_id: sessionId,
          job_id: jobId,
          dictionary_id: dictionaryId,
          threshold,
        });
        if (!mountedRef.current) return;
        fnJobIdRef.current = res.job_id;
        // Seed pending job.
        setFnJob({
          job_id: res.job_id,
          status: 'running',
          progress: 0,
          processed_dialogues: 0,
          total_dialogues: res.total,
          checkpoint_at: null,
          started_at: new Date().toISOString(),
          completed_at: null,
          error: null,
          warning: null,
        });
        await pollJob(res.job_id, 'fn');
      } catch (err) {
        if (!mountedRef.current) return;
        const msg = err instanceof Error ? err.message : String(err);
        setError('findFN', `find_fn failed: ${msg}`);
      } finally {
        if (mountedRef.current) setLoadingFN(false);
      }
    },
    [pollJob, sessionId, setError],
  );

  const doAudit = useCallback(
    async (dictionaryId: string): Promise<void> => {
      const jobId = indexJobIdRef.current;
      if (!jobId) {
        setError('audit', 'Сначала проиндексируйте корпус.');
        return;
      }
      setError('audit', null);
      setLoadingAudit(true);
      try {
        const res: AuditResponse = await auditDictionary({
          session_id: sessionId,
          job_id: jobId,
          dictionary_id: dictionaryId,
        });
        if (!mountedRef.current) return;
        auditJobIdRef.current = res.job_id;
        setAuditJob({
          job_id: res.job_id,
          status: 'running',
          progress: 0,
          processed_dialogues: 0,
          total_dialogues: 0,
          checkpoint_at: null,
          started_at: new Date().toISOString(),
          completed_at: null,
          error: null,
          warning: null,
        });
        await pollJob(res.job_id, 'audit');
      } catch (err) {
        if (!mountedRef.current) return;
        const msg = err instanceof Error ? err.message : String(err);
        setError('audit', `audit failed: ${msg}`);
      } finally {
        if (mountedRef.current) setLoadingAudit(false);
      }
    },
    [pollJob, sessionId, setError],
  );

  const doCancel = useCallback(
    async (jobId: string): Promise<void> => {
      setCancelling(true);
      try {
        await cancelMining(jobId);
        // Abort any active polling for this job across all kinds.
        abortController(`index:${jobId}`);
        abortController(`fn:${jobId}`);
        abortController(`audit:${jobId}`);
      } catch (err) {
        if (!mountedRef.current) return;
        const msg = err instanceof Error ? err.message : String(err);
        setError('index', `cancel failed: ${msg}`);
      } finally {
        if (mountedRef.current) setCancelling(false);
      }
    },
    [abortController, setError],
  );

  return {
    indexJob,
    fnJob,
    auditJob,
    similarResults,
    fnCandidates,
    auditResults,
    fnPartial,
    auditPartial,
    loadingSimilar,
    loadingFN,
    loadingAudit,
    cancelling,
    errors,
    indexCorpus: doIndex,
    findSimilar: doFindSimilar,
    findFalseNegatives: doFindFalseNegatives,
    auditDictionary: doAudit,
    cancelJob: doCancel,
  };
}
