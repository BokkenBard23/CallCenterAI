/**
 * Tests for xmlParser.ts — SpeechLab XML preview parser.
 *
 * TDD order: resolvePhraseChannel → groupIntoDisplayTokens → parseFullXml
 */

import { describe, it, expect } from 'vitest';
import {
  resolvePhraseChannel,
  groupIntoDisplayTokens,
  parseFullXml,
} from './xmlParser';
import type { ChannelType } from '../types/speechlab';

// ═══════════════════════════════════════════════════════════
// resolvePhraseChannel
// ═══════════════════════════════════════════════════════════

describe('resolvePhraseChannel', () => {
  it('returns ANY for empty set', () => {
    expect(resolvePhraseChannel(new Set())).toBe('ANY');
  });

  it('returns ANY when ANY is present in the set', () => {
    expect(resolvePhraseChannel(new Set<ChannelType>(['ANY']))).toBe('ANY');
    expect(resolvePhraseChannel(new Set<ChannelType>(['ANY', 'CLIENT']))).toBe('ANY');
  });

  it('returns ANY when both CLIENT and OPERATOR are present', () => {
    expect(resolvePhraseChannel(new Set<ChannelType>(['CLIENT', 'OPERATOR']))).toBe('ANY');
  });

  it('returns CLIENT when only CLIENT is present', () => {
    expect(resolvePhraseChannel(new Set<ChannelType>(['CLIENT']))).toBe('CLIENT');
  });

  it('returns OPERATOR when only OPERATOR is present', () => {
    expect(resolvePhraseChannel(new Set<ChannelType>(['OPERATOR']))).toBe('OPERATOR');
  });
});

// ═══════════════════════════════════════════════════════════
// groupIntoDisplayTokens
// ═══════════════════════════════════════════════════════════

describe('groupIntoDisplayTokens', () => {
  it('returns empty array for empty input', () => {
    expect(groupIntoDisplayTokens([])).toEqual([]);
  });

  // --- Single WORD token ---

  it('creates a WORD token for a single WORD input', () => {
    const result = groupIntoDisplayTokens([
      { text: 'привет', type: 'WORD', channel: 'CLIENT' as ChannelType, word_distance: 0, is_error: false },
    ]);
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({
      text: 'привет',
      type: 'WORD',
      channel: 'CLIENT',
      is_exact: false,
      is_error: false,
    });
  });

  // --- Multi-word PHRASE ---

  it('creates a PHRASE token for multiple consecutive WORDs', () => {
    const result = groupIntoDisplayTokens([
      { text: 'добрый', type: 'WORD', channel: 'ANY' as ChannelType, word_distance: 1, is_error: false },
      { text: 'день', type: 'WORD', channel: 'ANY' as ChannelType, word_distance: 2, is_error: false },
    ]);
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({
      text: 'добрый день',
      type: 'PHRASE',
      channel: 'ANY',
      is_exact: false,
    });
    expect(result[0].word_distance).toBe(2); // max of [1,2]
  });

  // --- Exact PHRASE in quotes ---

  it('creates an exact PHRASE token for words inside quotes', () => {
    const result = groupIntoDisplayTokens([
      { text: '"', type: 'TERMINAL', channel: 'ANY' as ChannelType, word_distance: 2, is_error: false },
      { text: 'расторжение', type: 'WORD', channel: 'OPERATOR' as ChannelType, word_distance: 0, is_error: false },
      { text: 'договора', type: 'WORD', channel: 'OPERATOR' as ChannelType, word_distance: 0, is_error: false },
      { text: '"', type: 'TERMINAL', channel: 'ANY' as ChannelType, word_distance: 2, is_error: false },
    ]);
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({
      text: 'расторжение договора',
      type: 'PHRASE',
      channel: 'OPERATOR',
      is_exact: true,
    });
  });

  // --- LEXEME keywords ---

  it('creates LEXEME token for ИЛИ keyword (lowercased)', () => {
    const result = groupIntoDisplayTokens([
      { text: 'ИЛИ', type: 'LEXEME', channel: 'ANY' as ChannelType, word_distance: 2, is_error: false },
    ]);
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({
      text: 'или',
      type: 'LEXEME',
      channel: 'ANY',
      is_exact: false,
    });
  });

  it('creates LEXEME token for OR keyword', () => {
    const result = groupIntoDisplayTokens([
      { text: 'OR', type: 'LEXEME', channel: 'ANY' as ChannelType, word_distance: 2, is_error: false },
    ]);
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({ text: 'or', type: 'LEXEME' });
  });

  it('creates LEXEME token for И keyword', () => {
    const result = groupIntoDisplayTokens([
      { text: 'И', type: 'LEXEME', channel: 'ANY' as ChannelType, word_distance: 2, is_error: false },
    ]);
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({ text: 'и', type: 'LEXEME' });
  });

  it('creates LEXEME token for AND keyword', () => {
    const result = groupIntoDisplayTokens([
      { text: 'AND', type: 'LEXEME', channel: 'ANY' as ChannelType, word_distance: 2, is_error: false },
    ]);
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({ text: 'and', type: 'LEXEME' });
  });

  it('creates LEXEME token for НЕ keyword', () => {
    const result = groupIntoDisplayTokens([
      { text: 'НЕ', type: 'LEXEME', channel: 'ANY' as ChannelType, word_distance: 2, is_error: false },
    ]);
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({ text: 'не', type: 'LEXEME' });
  });

  it('creates LEXEME token for NOT keyword', () => {
    const result = groupIntoDisplayTokens([
      { text: 'NOT', type: 'LEXEME', channel: 'ANY' as ChannelType, word_distance: 2, is_error: false },
    ]);
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({ text: 'not', type: 'LEXEME' });
  });

  // --- Non-keyword LEXEME ---

  it('creates LEXEME token for non-keyword lexeme (e.g. custom operator)', () => {
    const result = groupIntoDisplayTokens([
      { text: 'БЛИЖАЙШИЙ', type: 'LEXEME', channel: 'ANY' as ChannelType, word_distance: 2, is_error: false },
    ]);
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({ text: 'ближайший', type: 'LEXEME' });
  });

  // --- BRACKET tokens ---

  it('creates BRACKET token for parentheses', () => {
    const result = groupIntoDisplayTokens([
      { text: '(', type: 'TERMINAL', channel: 'ANY' as ChannelType, word_distance: 2, is_error: false },
      { text: ')', type: 'TERMINAL', channel: 'ANY' as ChannelType, word_distance: 2, is_error: false },
    ]);
    expect(result).toHaveLength(2);
    expect(result[0]).toMatchObject({ text: '(', type: 'BRACKET' });
    expect(result[1]).toMatchObject({ text: ')', type: 'BRACKET' });
  });

  // --- WHITESPACE skipped ---

  it('skips WHITESPACE tokens', () => {
    const result = groupIntoDisplayTokens([
      { text: ' ', type: 'WHITESPACE', channel: 'ANY' as ChannelType, word_distance: 2, is_error: false },
    ]);
    expect(result).toHaveLength(0);
  });

  // --- Error tokens ---

  it('propagates is_error on BRACKET tokens', () => {
    const result = groupIntoDisplayTokens([
      { text: '(', type: 'TERMINAL', channel: 'ANY' as ChannelType, word_distance: 2, is_error: true },
    ]);
    expect(result).toHaveLength(1);
    expect(result[0].is_error).toBe(true);
  });

  // --- Complex mixed sequence ---

  it('correctly groups a complex mixed sequence: WORD then LEXEME then WORD', () => {
    const result = groupIntoDisplayTokens([
      { text: 'риск', type: 'WORD', channel: 'OPERATOR' as ChannelType, word_distance: 1, is_error: false },
      { text: 'ИЛИ', type: 'LEXEME', channel: 'ANY' as ChannelType, word_distance: 2, is_error: false },
      { text: 'отказ', type: 'WORD', channel: 'CLIENT' as ChannelType, word_distance: 2, is_error: false },
    ]);
    // WORD flushed before LEXEME, then LEXEME, then WORD at end
    expect(result).toHaveLength(3);
    expect(result[0]).toMatchObject({ text: 'риск', type: 'WORD', channel: 'OPERATOR' });
    expect(result[1]).toMatchObject({ text: 'или', type: 'LEXEME' });
    expect(result[2]).toMatchObject({ text: 'отказ', type: 'WORD', channel: 'CLIENT' });
  });

  it('groups quoted phrase: opening quote joins with preceding words until close', () => {
    const result = groupIntoDisplayTokens([
      { text: '"', type: 'TERMINAL', channel: 'ANY' as ChannelType, word_distance: 2, is_error: false },
      { text: 'расторжение', type: 'WORD', channel: 'OPERATOR' as ChannelType, word_distance: 0, is_error: false },
      { text: 'договора', type: 'WORD', channel: 'OPERATOR' as ChannelType, word_distance: 0, is_error: false },
      { text: '"', type: 'TERMINAL', channel: 'ANY' as ChannelType, word_distance: 2, is_error: false },
      { text: 'И', type: 'LEXEME', channel: 'ANY' as ChannelType, word_distance: 2, is_error: false },
      { text: 'отказ', type: 'WORD', channel: 'CLIENT' as ChannelType, word_distance: 2, is_error: false },
    ]);
    // Close quote flushes, then LEXEME flushes, then WORD at end
    expect(result).toHaveLength(3);
    expect(result[0]).toMatchObject({ text: 'расторжение договора', type: 'PHRASE', is_exact: true });
    expect(result[1]).toMatchObject({ text: 'и', type: 'LEXEME' });
    expect(result[2]).toMatchObject({ text: 'отказ', type: 'WORD', channel: 'CLIENT' });
  });

  // --- Channel resolution within groups ---

  it('resolves channel to ANY when words have mixed CLIENT+OPERATOR channels', () => {
    const result = groupIntoDisplayTokens([
      { text: 'слово1', type: 'WORD', channel: 'CLIENT' as ChannelType, word_distance: 2, is_error: false },
      { text: 'слово2', type: 'WORD', channel: 'OPERATOR' as ChannelType, word_distance: 2, is_error: false },
    ]);
    expect(result).toHaveLength(1);
    expect(result[0].channel).toBe('ANY');
  });

  // --- word_distance default ---

  it('uses default word_distance=2 when no word_distance > 0 in group', () => {
    const result = groupIntoDisplayTokens([
      { text: 'тест', type: 'WORD', channel: 'ANY' as ChannelType, word_distance: 0, is_error: false },
    ]);
    expect(result[0].word_distance).toBe(2);
  });

  // --- Unclosed quotes ---

  it('handles unclosed quotes by treating remaining words as exact PHRASE', () => {
    const result = groupIntoDisplayTokens([
      { text: '"', type: 'TERMINAL', channel: 'ANY' as ChannelType, word_distance: 2, is_error: false },
      { text: 'незакрытая', type: 'WORD', channel: 'ANY' as ChannelType, word_distance: 0, is_error: false },
      { text: 'фраза', type: 'WORD', channel: 'ANY' as ChannelType, word_distance: 0, is_error: false },
    ]);
    expect(result).toHaveLength(1);
    expect(result[0].is_exact).toBe(true);
    expect(result[0].text).toBe('незакрытая фраза');
  });

  // --- Other TERMINAL tokens (not quote or bracket) ---

  it('treats unknown TERMINAL tokens as BRACKET', () => {
    const result = groupIntoDisplayTokens([
      { text: '[', type: 'TERMINAL', channel: 'ANY' as ChannelType, word_distance: 2, is_error: false },
    ]);
    expect(result).toHaveLength(1);
    expect(result[0].type).toBe('BRACKET');
  });
});

// ═══════════════════════════════════════════════════════════
// parseFullXml
// ═══════════════════════════════════════════════════════════

describe('parseFullXml', () => {
  it('throws on malformed XML', () => {
    expect(() => parseFullXml('<not closed')).toThrow(/XML parse error/);
  });

  it('parses a minimal SpeechLabRequest with name and id', () => {
    const xml = `
      <SpeechLabRequest>
        <Id>dict-001</Id>
        <Name>Тестовый словарь</Name>
      </SpeechLabRequest>
    `;
    const result = parseFullXml(xml);
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({
      id: 'dict-001',
      name: 'Тестовый словарь',
      has_children: false,
      children_count: 0,
      is_remainder: false,
      children: [],
      display_tokens: [],
    });
  });

  it('parses nested SpeechLabRequest children', () => {
    const xml = `
      <SpeechLabRequest>
        <Id>root-1</Id>
        <Name>Корень</Name>
        <Requests>
          <SpeechLabRequest>
            <Id>child-1</Id>
            <Name>Потомок 1</Name>
          </SpeechLabRequest>
          <SpeechLabRequest>
            <Id>child-2</Id>
            <Name>Потомок 2</Name>
          </SpeechLabRequest>
        </Requests>
      </SpeechLabRequest>
    `;
    const result = parseFullXml(xml);
    expect(result).toHaveLength(1);
    expect(result[0].children).toHaveLength(2);
    expect(result[0].has_children).toBe(true);
    expect(result[0].children_count).toBe(2);
    expect(result[0].children[0]).toMatchObject({ id: 'child-1', name: 'Потомок 1' });
    expect(result[0].children[1]).toMatchObject({ id: 'child-2', name: 'Потомок 2' });
  });

  it('parses SpeechLabRemainderRequest and marks is_remainder=true', () => {
    const xml = `
      <SpeechLabRequest>
        <Id>root-1</Id>
        <Name>Корень</Name>
        <Requests>
          <SpeechLabRemainderRequest>
            <Id>rem-1</Id>
            <Name>Остаток</Name>
          </SpeechLabRemainderRequest>
        </Requests>
      </SpeechLabRequest>
    `;
    const result = parseFullXml(xml);
    expect(result[0].children).toHaveLength(1);
    expect(result[0].children[0].is_remainder).toBe(true);
  });

  it('parses SavedState from XML', () => {
    const xml = `
      <SpeechLabRequest>
        <Id>s1</Id>
        <Name>С сохранением</Name>
        <SavedState>
          <TotalFound>42</TotalFound>
          <LastUpdateTime>2026-01-01T00:00:00Z</LastUpdateTime>
          <ExecutionTime>1.5s</ExecutionTime>
          <IsActual>true</IsActual>
          <IsCancelled>false</IsCancelled>
        </SavedState>
      </SpeechLabRequest>
    `;
    const result = parseFullXml(xml);
    expect(result[0].saved_state).toMatchObject({
      total_found: 42,
      last_update_time: '2026-01-01T00:00:00Z',
      execution_time: '1.5s',
      is_actual: true,
      is_cancelled: false,
    });
  });

  it('parses simple attributes from XML', () => {
    const xml = `
      <SpeechLabRequest>
        <Id>a1</Id>
        <Name>С атрибутами</Name>
        <Attributes>
          <AttributeTokens>
            <AttributeToken>
              <Type>ATTRIBUTE</Type>
              <SearchAttribute>
                <Key>Регион</Key>
                <Value>Москва</Value>
              </SearchAttribute>
            </AttributeToken>
          </AttributeTokens>
        </Attributes>
      </SpeechLabRequest>
    `;
    const result = parseFullXml(xml);
    expect(result[0].attributes).toHaveLength(1);
    expect(result[0].attributes![0]).toMatchObject({
      key: 'Регион',
      raw_value: 'Москва',
      human_readable: 'Регион: Москва',
    });
  });

  it('ignores non-ATTRIBUTE type tokens in attributes', () => {
    const xml = `
      <SpeechLabRequest>
        <Id>a2</Id>
        <Name>Фильтр атрибутов</Name>
        <Attributes>
          <AttributeTokens>
            <AttributeToken>
              <Type>PHRASE</Type>
              <SearchAttribute>
                <Key>Ключ</Key>
                <Value>Значение</Value>
              </SearchAttribute>
            </AttributeToken>
          </AttributeTokens>
        </Attributes>
      </SpeechLabRequest>
    `;
    const result = parseFullXml(xml);
    expect(result[0].attributes).toBeUndefined();
  });

  it('parses Tokens from XML into display_tokens', () => {
    const xml = `
      <SpeechLabRequest>
        <Id>t1</Id>
        <Name>С токенами</Name>
        <Tokens>
          <Token>
            <Text>привет</Text>
            <Type>WORD</Type>
            <IsError>false</IsError>
            <Properties Channel="CLIENT" WordDistance="0"/>
          </Token>
        </Tokens>
      </SpeechLabRequest>
    `;
    const result = parseFullXml(xml);
    expect(result[0].display_tokens).toHaveLength(1);
    expect(result[0].display_tokens[0]).toMatchObject({
      text: 'привет',
      type: 'WORD',
      channel: 'CLIENT',
      is_exact: false,
      is_error: false,
    });
  });

  it('handles wrapper root element with SpeechLabRequest children', () => {
    const xml = `
      <Dictionaries>
        <SpeechLabRequest>
          <Id>d1</Id>
          <Name>Словарь 1</Name>
        </SpeechLabRequest>
        <SpeechLabRequest>
          <Id>d2</Id>
          <Name>Словарь 2</Name>
        </SpeechLabRequest>
      </Dictionaries>
    `;
    const result = parseFullXml(xml);
    expect(result).toHaveLength(2);
    expect(result[0].name).toBe('Словарь 1');
    expect(result[1].name).toBe('Словарь 2');
  });

  it('generates UUID when Id is missing', () => {
    const xml = `
      <SpeechLabRequest>
        <Name>Без ID</Name>
      </SpeechLabRequest>
    `;
    const result = parseFullXml(xml);
    expect(result[0].id).toBeTruthy();
    expect(result[0].id.length).toBeGreaterThan(0);
  });

  it('defaults name to "Unnamed" when Name is missing', () => {
    const xml = `
      <SpeechLabRequest>
        <Id>x1</Id>
      </SpeechLabRequest>
    `;
    const result = parseFullXml(xml);
    expect(result[0].name).toBe('Unnamed');
  });

  it('parses IsActual=false correctly in SavedState', () => {
    const xml = `
      <SpeechLabRequest>
        <Id>ss2</Id>
        <Name>Неактуальный</Name>
        <SavedState>
          <TotalFound>0</TotalFound>
          <LastUpdateTime></LastUpdateTime>
          <ExecutionTime></ExecutionTime>
          <IsActual>false</IsActual>
          <IsCancelled>true</IsCancelled>
        </SavedState>
      </SpeechLabRequest>
    `;
    const result = parseFullXml(xml);
    expect(result[0].saved_state!.is_actual).toBe(false);
    expect(result[0].saved_state!.is_cancelled).toBe(true);
  });

  it('parses Token Properties as child elements (not attributes)', () => {
    const xml = `
      <SpeechLabRequest>
        <Id>tp1</Id>
        <Name>Props as elements</Name>
        <Tokens>
          <Token>
            <Text>тест</Text>
            <Type>WORD</Type>
            <IsError>false</IsError>
            <Properties>
              <Channel>OPERATOR</Channel>
              <WordDistance>3</WordDistance>
            </Properties>
          </Token>
        </Tokens>
      </SpeechLabRequest>
    `;
    const result = parseFullXml(xml);
    expect(result[0].display_tokens[0]).toMatchObject({
      text: 'тест',
      channel: 'OPERATOR',
      word_distance: 3,
    });
  });
});
