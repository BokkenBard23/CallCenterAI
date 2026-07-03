/**
 * QueryTab — right panel tab showing selected SpeechLabTreeNode details:
 *   - Header (node name)
 *   - Attributes section (DecodedAttribute[])
 *   - Keywords section (KeywordsDisplay with DisplayToken[])
 *   - Additional section (ExpansionPanel with extra details)
 *
 * From design-spec-chunk-3:
 *   - Stack vertical with Dividers between sections
 *   - Empty state: "Выберите словарь в дереве"
 *   - Attributes hidden if empty
 */

import {
  Box,
  Divider,
  ExpansionPanel,
  Icon,
  Stack,
  Typography,
} from '@beeline/design-system-react';
import { Icons } from '@beeline/design-tokens/js/iconfont';

import type { SpeechLabTreeNode, DecodedAttribute } from '../../../types/speechlab';
import KeywordsDisplay from '../KeywordsDisplay/KeywordsDisplay';

import './QueryTab.scss';

interface QueryTabProps {
  /** Currently selected node, or null if nothing selected */
  selectedNode: SpeechLabTreeNode | null;
}

/** Render attributes section */
function AttributesSection({ attributes }: { attributes: DecodedAttribute[] }) {
  if (attributes.length === 0) return null;

  return (
    <Box className="query-tab__section">
      <Typography variant="body1" style={{ fontWeight: 600, marginBottom: '8px' }}>
        Атрибуты записи
      </Typography>
      <Stack direction="vertical" spacing="x1">
        {attributes.map((attr, idx) => (
          <Stack key={`${attr.key}-${idx}`} direction="horizontal" spacing="x2" align="center">
            <Icon iconName={Icons.InfoCircled} size="small" />
            <Typography variant="body2">{attr.human_readable}</Typography>
          </Stack>
        ))}
      </Stack>
    </Box>
  );
}

/** Additional section: word_distance, without_list, nested_phrases, is_exception */
function AdditionalSection({ node }: { node: SpeechLabTreeNode }) {
  const details: Array<{ label: string; value: string; icon?: typeof Icons[keyof typeof Icons] }> = [];

  // Check for additional info from display tokens
  const hasExactPhrase = node.display_tokens.some(
    (t) => t.type === 'PHRASE' && t.is_exact
  );
  if (hasExactPhrase) {
    details.push({
      label: 'Точное совпадение',
      value: 'Фраза в кавычках — точный порядок слов',
      icon: Icons.Check,
    });
  }

  // Word distance from tokens
  const maxDistance = Math.max(...node.display_tokens.map((t) => t.word_distance), 0);
  if (maxDistance > 0) {
    details.push({
      label: 'Расстояние между словами',
      value: `до ${maxDistance} слов`,
    });
  }

  // Error tokens
  const errorTokens = node.display_tokens.filter((t) => t.is_error);
  if (errorTokens.length > 0) {
    details.push({
      label: 'Ошибки',
      value: `${errorTokens.length} токен(а) с ошибками`,
      icon: Icons.WarningCircled,
    });
  }

  if (details.length === 0) return null;

  return (
    <Box className="query-tab__section">
      <ExpansionPanel title="Дополнительно">
        <Stack direction="vertical" spacing="x2">
          {details.map((detail, idx) => (
            <Stack key={idx} direction="horizontal" spacing="x2" align="center">
              {detail.icon && <Icon iconName={detail.icon} size="small" />}
              <Typography variant="body2">
                {detail.label}: {detail.value}
              </Typography>
            </Stack>
          ))}
        </Stack>
      </ExpansionPanel>
    </Box>
  );
}

export default function QueryTab({ selectedNode }: QueryTabProps) {
  // No selection state
  if (!selectedNode) {
    return (
      <Box className="query-tab query-tab--empty" padding="x6">
        <Stack direction="vertical" spacing="x3" align="center">
          <Icon iconName={Icons.InfoCircled} size="large" />
          <Typography variant="body1" inactive>
            Выберите словарь в дереве
          </Typography>
        </Stack>
      </Box>
    );
  }

  const hasAttributes = selectedNode.attributes && selectedNode.attributes.length > 0;

  return (
    <Box className="query-tab" padding="x4">
      <Stack direction="vertical" spacing="x4">
        {/* Header — node name */}
        <Typography variant="h6">{selectedNode.name}</Typography>

        <Divider />

        {/* Attributes section (hidden if empty) */}
        {hasAttributes && selectedNode.attributes && (
          <>
            <AttributesSection attributes={selectedNode.attributes} />
            <Divider />
          </>
        )}

        {/* Keywords section */}
        <Box className="query-tab__section">
          <Typography variant="body1" style={{ fontWeight: 600, marginBottom: '8px' }}>
            Ключевые слова
          </Typography>
          <KeywordsDisplay tokens={selectedNode.display_tokens} />
        </Box>

        <Divider />

        {/* Additional section */}
        <AdditionalSection node={selectedNode} />
      </Stack>
    </Box>
  );
}
