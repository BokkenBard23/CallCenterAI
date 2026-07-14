# Vision Gate — обязательный multimodal-анализ скриншотов

## Контекст

CDP (Chrome DevTools Protocol) и MCP-automation (chrome-devtools-mcp, playwright-mcp)
проверяют **DOM-измерения** (width, overflow, position), но **не видят** визуальное содержимое:
наложение текста, рендеринг иконок как текста, обрезание шрифтов, визуальные коллизии.

**Проблема:** ui-tester может вернуть `verdict: approved` с `PASS` по всем DOM-метрикам,
когда на экране реально сломан рендеринг (текст поверх текста, иконки как строки, склеенные tab-ы).

**Решение:** обязательный vision-анализ скриншотов через multimodal LLM API для **каждого**
visual gate с UI surface.

## Инструмент

### Backend module: `backend/app/services/vision_analysis.py`

Переиспользуемый async-модуль с fallback-цепочкой (на основе vision-бенчмарка
2026-07-12, см. `docs/specs/screenshots/vision-benchmark/VISION_BENCHMARK_RESULTS.md`):

```
gpt-5.4 → qwen-medium-dense → qwen-medium
```

**Бенчмарк (3 теста, 7 моделей):**

| Модель | Точность | Скорость | Параллелизм | Роль |
|--------|----------|----------|-------------|------|
| **gpt-5.4** | **100%** | 5.5s | **3 слота** | Primary — единственная модель без false positives |
| qwen-medium-dense | 67% | 3.6s | **6 слотов** | Fallback 1 — самая быстрая, 262K context |
| qwen-medium | 67% | 4.8s | **3 слота** | Fallback 2 — гарантированно доступна (Beeline infra) |
| claude-sonnet-4-5 | 67% | 6.4s | — | Не используется |
| claude-opus-4-6 | 67% | 6.7s | — | Не используется |
| gemini-2.5-pro | 67% | 12.8s | — | Не используется (самая медленная) |
| qwen-medium-preview | 67% | 4.7s | — | **НЕ ИСПОЛЬЗУЕТСЯ** — limited context (~47.8K tokens) |

**Параллелизм (batch mode):**
- `gpt-5.4` — 3 параллельных запроса (primary, лучшая точность)
- `qwen-medium-dense` — 6 параллельных запросов (fallback, самая быстрая)
- `qwen-medium` — 3 параллельных запроса (fallback, гарантированный recovery)
- Batch mode: `analyze_screenshots_batch()` с `asyncio.Semaphore(max_concurrent=3)` по умолчанию
- CLI: `--batch <dir> --max-concurrent 3` для параллельной обработки каталога скриншотов

- `gpt-5.4` может давать **Guardrails Exo** ошибки (intermittent).
- Модели `qwen-medium*` — direct Beeline infrastructure, **не** проходят через Guardrails,
  гарантированный last-resort fallback.
- Все модели используют один OpenAI-compatible endpoint `api.ai.beeline.ru/api/v3/chat/completions`.
- API key берётся из `backend/.env` (`BEELINE_API_KEY`).

⚠️ **ВАЖНО: Ограничение qwen-medium-preview**
- Заявлено: 262K токенов
- Фактически: ~47.8K токенов (проверено 2026-07-14)
- **НЕ использовать для long-context задач**
- Использовать `qwen-medium-dense` или `qwen-medium` вместо него

### CLI usage (для stage-агентов)

```bash
# Single screenshot
cd backend
PYTHONPATH=. PYTHONIOENCODING=utf-8 python -m app.services.vision_analysis \
  --image ../docs/specs/screenshots/some-screenshot.png \
  --prompt "Опиши визуальные проблемы: наложение текста, обрезание, рендеринг иконок." \
  --output ../docs/specs/screenshots/ai-analysis-some-screenshot.md

# Batch: 3 скриншота за раз (gpt-5.4 = 3 параллельных слота)
cd backend
PYTHONPATH=. PYTHONIOENCODING=utf-8 python -m app.services.vision_analysis \
  --batch ../docs/specs/screenshots/ \
  --prompt "Опиши визуальные проблемы: наложение текста, обрезание, рендеринг иконок." \
  --max-concurrent 3 \
  --output-dir ../docs/specs/screenshots/
# → создаёт ai-analysis-*.md для каждого .png в каталоге
```

### Python API (для backend integration)

```python
from app.services.vision_analysis import analyze_screenshot, analyze_screenshots_batch

# Single
result = await analyze_screenshot(
    image_path="docs/specs/screenshots/some.png",
    prompt="Опиши визуальные проблемы.",
)
print(result["text"])  # LLM response
print(result["model"])  # "gpt-5.4" (or fallback model)
print(result["attempts"])  # per-model attempt log

# Batch: 3+ screenshots in parallel (gpt-5.4 = 3 slots)
results = await analyze_screenshots_batch(
    images=[
        {"path": "screenshots/page1.png", "prompt": "Проверь UI"},
        {"path": "screenshots/page2.png", "prompt": "Проверь UI"},
        {"path": "screenshots/page3.png", "prompt": "Проверь UI"},
    ],
    max_concurrent=3,  # respects gpt-5.4 3-slot limit
)
# → [{"text": "...", "model": "gpt-5.4", "success": True}, ...]
```

## Обязательные правила для stage-агентов

### ui-tester — ОБЯЗАТЕЛЬНЫЙ vision-анализ

1. **После** CDP/MCP DOM-проверок (width, overflow, position, console) — и **до** формирования
   вердикта — ui-tester обязан запустить vision-анализ **минимум одного скриншота на breakpoint**.

2. Vision-анализ проверяет:
   - Наложение текста (дублирование RU+EN, иконки как строки поверх подписей)
   - Обрезание текста за пределами кнопок/контейнеров
   - Склеивание tab-ов / некорректный рендеринг DS-компонентов
   - Визуальные коллизии (элементы поверх друг друга)
   - Отсутствие иконок (пустые места где должны быть icons)
   - Общая читаемость и композиция

3. Если vision-анализ находит **любой** visual bug, который CDP не обнаружил — вердикт
   **обязан** быть `rejected`, даже если все DOM-метрики PASS.

4. Vision-анализ **не заменяет** CDP/MCP — он дополняет. CDP проверяет размеры/overflow,
   vision проверяет содержимое/рендеринг.

5. Результат vision-анализа сохраняется:
   - Файл: `docs/specs/screenshots/ai-analysis-{screenshot-name}.md`
   - В `stage_result.visual_gate.screenshots_or_notes` — ссылка на файл анализа
   - В `pipeline-state.yaml` → `visual_gate.screenshots_or_notes` — краткое упоминание

### reviewer — проверка vision evidence

1. При review UI surface reviewer обязан проверить, что ui-tester приложил vision-анализ
   (файл `ai-analysis-*.md` в `docs/specs/screenshots/`).

2. Если vision-анализ отсутствует — это `visual_gate_met: false`, возвращать в `ui-tester`.

3. Если vision-анализ нашёл issues, но ui-tester вернул `approved` — это blocker, возвращать
   в `ui-tester` с пометкой `vision_analysis_discrepancy`.

### ui-coder — self-check перед handoff

1. После реализации UI и **до** запуска `npm run dev` → chrome-devtools-mcp цикла,
   ui-coder может (опционально, но рекомендуется) запустить vision-анализ на скриншоте
   из dev-сервера для раннего обнаружения проблем.

2. Это **не заменяет** ui-tester visual gate, но сокращает итерации.

## Fallback chain логика

```
1. gpt-5.4             → если Guardrails Exo →
2. qwen-medium-dense   → direct Beeline infra, NO Guardrails (самая быстрая: 3.6s, 262K context)
3. qwen-medium         → direct Beeline infra, NO Guardrails (гарантированный recovery, 262K context)
```

- Модуль автоматически переходит к следующей модели при ошибке.
- `gpt-5.4` — primary (100% точность в бенчмарке, единственная модель без false positives
  на тонких визуальных нюансах).
- Qwen модели — **гарантированный** recovery: они никогда не дают Guardrails Exo.
- **qwen-medium-preview НЕ используется** — имеет ограниченный контекст (~47.8K токенов).
- Лог попыток сохраняется в `result["attempts"]` для аудита.
- Бенчмарк: `docs/specs/screenshots/vision-benchmark/VISION_BENCHMARK_RESULTS.md`

## Обновление моделей (2026-07-27)

⚠️ **Qwen 3.5 35B и Qwen 3.6 35B выводятся из эксплуатации с 27 июля 2026**

Новая внутренняя модель **Qwen3.6 27B** уже доступна:
- `Qwen3.6-27B-textonly` — текстовая модель
- `coding-medium` — для кодирования
- `qwen-medium-dense` — с vision (262K context) ✅ **РЕКОМЕНДУЕТСЯ**
- `qwen-medium-dense-fast` — быстрый режим без рассуждений

Legacy коды (`universal-large`, `universal-medium`) автоматически перенаправят на новую модель.

## Detect Guardrails Exo

Модуль определяет Guardrails ошибки по паттернам:
- HTTP non-200 + "guardrails" / "exo" / "content_filter" / "content policy" в теле
- HTTP 200 + пустой content (для guardrails-моделей)
- HTTP 200 + guardrails-текст в content body

## Исключения (когда vision-анализ не нужен)

- `quality_profile: lean` БЕЗ UI surface (logic-only changes)
- `visual_gate.required: false` (явно указано в brief)
- `design_input: null` (no UI)
- Если `mobile_relevance: none` и тестируется только desktop — vision-анализ нужен только
  для desktop скриншота (не для 375/768)

## Артефакты

| Артефакт | Создатель | Потребитель |
|----------|-----------|-------------|
| `backend/app/services/vision_analysis.py` | coder (создан) | ui-tester, reviewer, ui-coder (через CLI) |
| `docs/specs/screenshots/ai-analysis-*.md` | ui-tester | reviewer, orchestrator |
| `pipeline-state.yaml` → `visual_gate.vision_analysis` | ui-tester | orchestrator, reviewer |

## Инвариант

**CDP PASS без vision-анализа ≠ visual gate PASS.**

Если visual gate `required: true` и есть UI surface, но vision-анализ не выполнен —
`visual_gate.status` обязан быть `blocked`, а не `passed`.
