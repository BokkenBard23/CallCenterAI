/**
 * RestructuredDialogue — renders restructured dialogue as chat bubbles.
 * Parses plain text restructured_dialogue into speaker/text pairs.
 */

import { useMemo } from 'react';
import { Box, Stack, Typography } from '@beeline/design-system-react';

interface RestructuredDialogueProps {
  text: string;
}

interface DialogueEntry {
  speaker: string;
  text: string;
}

/**
 * Parse restructured dialogue text into speaker/text pairs.
 * Supports formats like:
 *   "Клиент: Привет\nСотрудник: Здравствуйте"
 *   "[Клиент]: Привет\n[Сотрудник]: Здравствуйте"
 */
function parseDialogueText(text: string): DialogueEntry[] {
  const lines = text.split('\n').filter((line) => line.trim().length > 0);
  const entries: DialogueEntry[] = [];
  let currentSpeaker = '';
  let currentText = '';

  for (const line of lines) {
    // Try to match "Speaker: text" or "[Speaker]: text" patterns
    const match = line.match(/^\s*(?:\[([^\]]+)\]|([^:]+))\s*[:：]\s*(.*)$/);

    if (match) {
      // Save previous entry if exists
      if (currentSpeaker && currentText.trim()) {
        entries.push({ speaker: currentSpeaker, text: currentText.trim() });
      }
      currentSpeaker = (match[1] ?? match[2] ?? '').trim();
      currentText = match[3] ?? '';
    } else if (currentSpeaker) {
      // Continuation of current speaker's text
      currentText += '\n' + line;
    } else {
      // No speaker detected — treat entire line as text with unknown speaker
      entries.push({ speaker: '', text: line.trim() });
    }
  }

  // Don't forget the last entry
  if (currentSpeaker && currentText.trim()) {
    entries.push({ speaker: currentSpeaker, text: currentText.trim() });
  }

  // If parsing produced nothing, return the raw text as a single entry
  if (entries.length === 0 && text.trim()) {
    entries.push({ speaker: '', text: text.trim() });
  }

  return entries;
}

export default function RestructuredDialogue({ text }: RestructuredDialogueProps) {
  const entries = useMemo(() => parseDialogueText(text), [text]);

  return (
    <Stack direction="vertical" spacing="x2">
      <Typography variant="h6">Реорганизованный диалог</Typography>
      <Box
        display="flex"
        style={{ flexDirection: 'column', gap: '8px' } as never}
      >
        {entries.map((entry, idx) => (
          <div
            key={idx}
            className="dialogue-bubble"
            data-speaker={entry.speaker}
          >
            {entry.speaker && (
              <div className="dialogue-speaker-label">{entry.speaker}</div>
            )}
            <Typography variant="body2">{entry.text}</Typography>
          </div>
        ))}
      </Box>
    </Stack>
  );
}
