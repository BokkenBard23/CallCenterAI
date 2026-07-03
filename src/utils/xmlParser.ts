/**
 * SpeechLab XML preview parser — lightweight DOMParser for instant preview.
 *
 * This is a BROWSER-ONLY preview parser. The backend (xml_parser.py) is the
 * source of truth for all token processing. This parser provides immediate
 * visual feedback while the XML is being uploaded to the backend.
 *
 * Limitations:
 *   - Does NOT parse <ExtraLimitations> (WITHOUT list)
 *   - Does NOT validate cycles (backend does)
 *   - Does NOT build attribute_tree (AND/OR/NOT) — only simple attributes
 *   - Does NOT validate or normalize — backend is authoritative
 *   - Browser-only (uses DOMParser, not lxml)
 *
 * ~80 lines of core logic.
 */

import type {
  ChannelType,
  DisplayToken,
  DisplayTokenType,
  SpeechLabTreeNode,
  DecodedAttribute,
  SavedState,
} from '../types/speechlab';

// ═══════════════════════════════════════════════════════════
// Channel Resolution (matches backend resolve_phrase_channel)
// ═══════════════════════════════════════════════════════════

/**
 * Determine the channel for a group of WORD tokens.
 *
 * Rules (matches backend xml_parser.resolve_phrase_channel):
 *   - ANY in channels → ANY
 *   - Both CLIENT and OPERATOR → ANY
 *   - Only CLIENT → CLIENT
 *   - Only OPERATOR → OPERATOR
 *   - Empty set → ANY
 */
export function resolvePhraseChannel(channels: Set<ChannelType>): ChannelType {
  if (channels.size === 0) return 'ANY';
  if (channels.has('ANY')) return 'ANY';
  const hasClient = channels.has('CLIENT');
  const hasOperator = channels.has('OPERATOR');
  if (hasClient && hasOperator) return 'ANY';
  if (hasClient) return 'CLIENT';
  if (hasOperator) return 'OPERATOR';
  return 'ANY';
}

// ═══════════════════════════════════════════════════════════
// Internal Raw Token (from DOM parsing)
// ═══════════════════════════════════════════════════════════

interface RawToken {
  text: string;
  type: string; // 'WORD' | 'LEXEME' | 'TERMINAL' | 'WHITESPACE'
  channel: ChannelType;
  word_distance: number;
  is_error: boolean;
}

// ═══════════════════════════════════════════════════════════
// groupIntoDisplayTokens
// ═══════════════════════════════════════════════════════════

const LEXEME_KEYWORDS = new Set(['ИЛИ', 'OR', 'И', 'AND', 'НЕ', 'NOT']);

/**
 * Convert raw tokens into grouped DisplayTokens for UI rendering.
 *
 * Algorithm (matches backend group_into_display_tokens):
 *   1. Iterate rawTokens left to right.
 *   2. TERMINAL '"' → toggle in_quotes (exact phrase).
 *   3. TERMINAL '(' or ')' → flush + BRACKET token.
 *   4. WORD → accumulate into group.
 *   5. LEXEME keyword → flush + LEXEME token.
 *   6. WHITESPACE → skip.
 *   7. On flush: type=PHRASE if is_exact or multi-word, WORD if single word.
 */
export function groupIntoDisplayTokens(rawTokens: RawToken[]): DisplayToken[] {
  const result: DisplayToken[] = [];
  let currentWords: string[] = [];
  let currentChannels: Set<ChannelType> = new Set();
  let currentDistances: number[] = [];
  let inQuotes = false;

  function flushGroup(): void {
    if (currentWords.length === 0) return;

    const text = currentWords.join(' ');
    const channel = resolvePhraseChannel(currentChannels);
    const wordDistance = currentDistances.length > 0 ? Math.max(...currentDistances) : 2;
    const isExact = inQuotes;

    let tokenType: DisplayTokenType;
    if (isExact) {
      tokenType = 'PHRASE';
    } else if (currentWords.length === 1) {
      tokenType = 'WORD';
    } else {
      tokenType = 'PHRASE';
    }

    result.push({
      text,
      type: tokenType,
      channel,
      word_distance: wordDistance,
      is_error: false,
      is_exact: isExact,
    });

    currentWords = [];
    currentChannels = new Set();
    currentDistances = [];
  }

  for (const tok of rawTokens) {
    if (tok.type === 'WHITESPACE') continue;

    if (tok.type === 'TERMINAL') {
      if (tok.text === '"') {
        if (inQuotes) {
          flushGroup();
          inQuotes = false;
        } else {
          inQuotes = true;
        }
      } else if (tok.text === '(' || tok.text === ')') {
        flushGroup();
        result.push({
          text: tok.text,
          type: 'BRACKET',
          channel: 'ANY',
          word_distance: 2,
          is_error: tok.is_error,
          is_exact: false,
        });
      } else {
        flushGroup();
        result.push({
          text: tok.text,
          type: 'BRACKET',
          channel: 'ANY',
          word_distance: 2,
          is_error: tok.is_error,
          is_exact: false,
        });
      }
      continue;
    }

    if (tok.type === 'LEXEME' && LEXEME_KEYWORDS.has(tok.text.toUpperCase())) {
      flushGroup();
      result.push({
        text: tok.text.toLowerCase(),
        type: 'LEXEME',
        channel: 'ANY',
        word_distance: 2,
        is_error: tok.is_error,
        is_exact: false,
      });
      inQuotes = false;
      continue;
    }

    if (tok.type === 'WORD') {
      currentWords.push(tok.text);
      if (tok.channel) {
        currentChannels.add(tok.channel);
      }
      if (tok.word_distance > 0) {
        currentDistances.push(tok.word_distance);
      }
      continue;
    }

    // LEXEME not in keywords — treat as LEXEME display token
    if (tok.type === 'LEXEME') {
      flushGroup();
      result.push({
        text: tok.text.toLowerCase(),
        type: 'LEXEME',
        channel: 'ANY',
        word_distance: 2,
        is_error: tok.is_error,
        is_exact: false,
      });
    }
  }

  flushGroup();
  return result;
}

// ═══════════════════════════════════════════════════════════
// DOM Element Helpers
// ═══════════════════════════════════════════════════════════

function getChildText(parent: Element, tag: string): string {
  const el = parent.querySelector(`:scope > ${tag}`);
  return el?.textContent?.trim() ?? '';
}

function parseTokensFromElement(container: Element): DisplayToken[] {
  const tokensEl = container.querySelector(':scope > Tokens');
  if (!tokensEl) return [];

  const rawTokens: RawToken[] = [];
  const tokenEls = tokensEl.querySelectorAll(':scope > Token');

  for (const tokEl of tokenEls) {
    const text = getChildText(tokEl, 'Text');
    const type = getChildText(tokEl, 'Type') || 'WORD';
    const isErr = getChildText(tokEl, 'IsError').toLowerCase() === 'true';

    // Parse Properties (attribute format or child element format)
    const propsEl = tokEl.querySelector(':scope > Properties');
    let channel: ChannelType = 'ANY';
    let wordDistance = 2;

    if (propsEl) {
      const chAttr = propsEl.getAttribute('Channel');
      const wdAttr = propsEl.getAttribute('WordDistance');
      const chText = getChildText(propsEl, 'Channel');
      const wdText = getChildText(propsEl, 'WordDistance');

      const channelStr = chAttr || chText;
      if (channelStr === 'CLIENT' || channelStr === 'OPERATOR' || channelStr === 'ANY') {
        channel = channelStr;
      }

      const wdStr = wdAttr || wdText;
      const wd = parseInt(wdStr, 10);
      if (!isNaN(wd) && wd > 0) {
        wordDistance = wd;
      }
    }

    rawTokens.push({ text, type, channel, word_distance: wordDistance, is_error: isErr });
  }

  return groupIntoDisplayTokens(rawTokens);
}

function parseSavedStateFromElement(parent: Element): SavedState | undefined {
  const ssEl = parent.querySelector(':scope > SavedState');
  if (!ssEl) return undefined;

  return {
    total_found: parseInt(getChildText(ssEl, 'TotalFound') || '0', 10),
    last_update_time: getChildText(ssEl, 'LastUpdateTime'),
    execution_time: getChildText(ssEl, 'ExecutionTime'),
    is_actual: getChildText(ssEl, 'IsActual').toLowerCase() !== 'false',
    is_cancelled: getChildText(ssEl, 'IsCancelled').toLowerCase() === 'true',
  };
}

function parseSimpleAttributes(parent: Element): DecodedAttribute[] {
  const attrs: DecodedAttribute[] = [];
  const atContainer = parent.querySelector(':scope > Attributes > AttributeTokens');
  if (!atContainer) return attrs;

  const atEls = atContainer.querySelectorAll(':scope > AttributeToken');
  for (const atEl of atEls) {
    const type = getChildText(atEl, 'Type');
    if (type !== 'ATTRIBUTE') continue;

    const saEl = atEl.querySelector(':scope > SearchAttribute');
    if (!saEl) continue;

    const key = getChildText(saEl, 'Key');
    const value = getChildText(saEl, 'Value');
    if (key) {
      attrs.push({
        key,
        raw_value: value,
        human_readable: `${key}: ${value}`,
      });
    }
  }
  return attrs;
}

function parseRequestElement(el: Element): SpeechLabTreeNode {
  const id = getChildText(el, 'Id') || crypto.randomUUID().slice(0, 12);
  const name = getChildText(el, 'Name') || 'Unnamed';
  const savedState = parseSavedStateFromElement(el);
  const displayTokens = parseTokensFromElement(el);
  const attributes = parseSimpleAttributes(el);

  const children: SpeechLabTreeNode[] = [];
  const requestsEl = el.querySelector(':scope > Requests');
  if (requestsEl) {
    for (const childEl of requestsEl.children) {
      const localName = childEl.localName;
      if (localName === 'SpeechLabRequest' || localName === 'SpeechLabRemainderRequest') {
        const childNode = parseRequestElement(childEl);
        if (localName === 'SpeechLabRemainderRequest') {
          childNode.is_remainder = true;
        }
        children.push(childNode);
      }
    }
  }

  return {
    id,
    name,
    has_children: children.length > 0,
    children_count: children.length,
    is_remainder: el.localName === 'SpeechLabRemainderRequest',
    saved_state: savedState,
    display_tokens: displayTokens,
    children,
    attributes: attributes.length > 0 ? attributes : undefined,
  };
}

// ═══════════════════════════════════════════════════════════
// Main Entry Point
// ═══════════════════════════════════════════════════════════

/**
 * Parse an XML string into SpeechLabTreeNode[] for instant preview.
 *
 * Uses browser DOMParser. Backend is the source of truth —
 * this provides immediate visual feedback during file import.
 *
 * @param xmlString - Raw XML string from the file
 * @returns Array of SpeechLabTreeNode (root-level dictionaries)
 * @throws Error if XML is malformed
 */
export function parseFullXml(xmlString: string): SpeechLabTreeNode[] {
  const parser = new DOMParser();
  const doc = parser.parseFromString(xmlString, 'text/xml');

  // Check for parse errors
  const parseError = doc.querySelector('parsererror');
  if (parseError) {
    throw new Error(`XML parse error: ${parseError.textContent ?? 'unknown error'}`);
  }

  // Find root SpeechLabRequest elements
  const root = doc.documentElement;
  const results: SpeechLabTreeNode[] = [];

  // The root itself might be a SpeechLabRequest
  if (root.localName === 'SpeechLabRequest' || root.localName === 'SpeechLabRemainderRequest') {
    results.push(parseRequestElement(root));
  } else {
    // Otherwise look for SpeechLabRequest children
    const requests = root.querySelectorAll(':scope > SpeechLabRequest, :scope > SpeechLabRemainderRequest');
    for (const req of requests) {
      results.push(parseRequestElement(req));
    }
  }

  return results;
}
