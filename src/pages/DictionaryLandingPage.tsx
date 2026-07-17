/**
 * DictionaryLandingPage — landing page for the /dictionary route (without
 * a sessionId parameter).
 *
 * BUG 5 FIX: The NavBar "Словари" tab and the dashboard "Редактор словарей"
 * card both navigate to `/dictionary`, but the only existing route was
 * `/dictionary/:sessionId`. Navigating to `/dictionary` without a session
 * id resulted in no matching route (blank page or fallback).
 *
 * This page:
 *   1. Checks if there's an active session in AnalysisContext (from a
 *      previous upload). If so, redirects to `/dictionary/:sessionId`.
 *   2. Otherwise, shows a prompt to upload a dictionary on the home page,
 *      with a CTA button that navigates to `/`.
 *
 * Route: /dictionary (no sessionId)
 */

import { useEffect, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Box,
  Button,
  Icon,
  Stack,
  Typography,
} from '@beeline/design-system-react';
import { Icons } from '@beeline/design-tokens/js/iconfont';

import { useAnalysisContext } from '../context/AnalysisContext';
import { PageBreadcrumbs } from '../components/PageBreadcrumbs';

export default function DictionaryLandingPage(): ReactNode {
  const navigate = useNavigate();
  const { state } = useAnalysisContext();

  // If there's an active session (from a previous upload), redirect to
  // the dictionary editor for that session.
  useEffect(() => {
    if (state.sessionId) {
      navigate(`/dictionary/${state.sessionId}`, { replace: true });
    }
  }, [state.sessionId, navigate]);

  // Don't render the prompt if we're about to redirect.
  if (state.sessionId) {
    return null;
  }

  return (
    <Box>
      <PageBreadcrumbs currentPage="Словари" />
      <Box padding="x6">
        <Stack direction="vertical" gap="x4" align="center">
          <Icon iconName={Icons.Book} size="large" />
          <Typography variant="h5">Редактор словарей</Typography>
          <Typography variant="body1" color="colorTextInactive">
            Для редактирования словаря загрузите RTF-диалог и XML-словарь на
            главной странице. После загрузки вы сможете редактировать дерево
            словаря, использовать AI-подсказки, искать дубликаты и валидировать
            условия.
          </Typography>
          <Button
            variant="contained"
            startIcon={<Icon iconName={Icons.Upload} />}
            onClick={() => navigate('/')}
          >
            Загрузить словарь
          </Button>
        </Stack>
      </Box>
    </Box>
  );
}
