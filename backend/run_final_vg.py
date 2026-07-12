"""Final visual gate — run vision_analysis.py on all 5 pages."""
import subprocess
import sys
import os
import time
from pathlib import Path

SCREENSHOTS_DIR = Path(r'docs/specs/screenshots/vg-final')
BACKEND_DIR = Path(r'<backend>')

PAGES = [
    ('vg-final-01-upload.png', 'Страница загрузки словаря (UploadPage). Проверь: 1) Иконки на кнопках — графика или текст? 2) Наложение текста? 3) Обрезание? 4) Композиция. Кратко на русском. Если багов нет — ОК.'),
    ('vg-final-02-history.png', 'Страница истории анализов (HistoryPage). Проверь: 1) Иконки на кнопках — графика или текст? 2) Наложение текста? 3) Обрезание? 4) Композиция. Кратко на русском. Если багов нет — ОК.'),
    ('vg-final-03-speechlab.png', 'Страница речевой лаборатории (SpeechLabPage). Проверь: 1) Иконки на кнопках — графика или текст? 2) Наложение текста? 3) Обрезание текста? 4) Композиция. Кратко на русском. Если багов нет — ОК.'),
    ('vg-final-04-results.png', 'Страница результатов анализа (ResultsPage). Проверь: 1) Иконки на кнопках — графика или текст? 2) Наложение текста? 3) Обрезание? 4) Композиция. Кратко на русском. Если багов нет — ОК.'),
    ('vg-final-05-dictionary-mining.png', 'Редактор словаря с открытым Mining Sidesheet (модальный overlay затемняет основной контент — это нормально). Проверь: 1) Иконки на кнопках в шапке и в Sidesheet — графика или текст? 2) Наложение текста? 3) Табы в Sidesheet: Похожие на фразы, False Negatives, LLM-аудит — видны? 4) Композиция. Кратко на русском. Если багов нет — ОК.'),
]

results = []

for img_name, prompt in PAGES:
    img_path = SCREENSHOTS_DIR / img_name
    output_path = SCREENSHOTS_DIR / f'ai-{img_name.replace(".png", ".md")}'
    
    print(f"\n{'='*60}")
    print(f"Analyzing: {img_name}")
    print(f"{'='*60}")
    
    cmd = [
        sys.executable, '-m', 'app.services.vision_analysis',
        '--image', str(img_path),
        '--prompt', prompt,
        '--output', str(output_path),
        '--json',
    ]
    
    start = time.time()
    proc = subprocess.run(
        cmd,
        cwd=str(BACKEND_DIR),
        capture_output=True,
        text=True,
        env={**os.environ, 'PYTHONPATH': '.', 'PYTHONIOENCODING': 'utf-8'},
        timeout=120,
    )
    elapsed = time.time() - start
    
    if proc.returncode == 0:
        # Parse JSON output from stderr (module prints JSON to stdout, info to stderr)
        import json
        try:
            data = json.loads(proc.stdout)
            model = data.get('model', '?')
            text = data.get('text', '')[:200]
            print(f"  Model: {model} ({elapsed:.1f}s)")
            print(f"  Result: {text}")
            results.append((img_name, model, 'OK', text))
        except json.JSONDecodeError:
            print(f"  Output: {proc.stdout[:200]}")
            results.append((img_name, '?', 'OK', proc.stdout[:200]))
    else:
        print(f"  FAILED (exit {proc.returncode}, {elapsed:.1f}s)")
        print(f"  stderr: {proc.stderr[:300]}")
        results.append((img_name, '-', 'FAIL', proc.stderr[:200]))

# Summary
print(f"\n\n{'='*60}")
print("SUMMARY")
print(f"{'='*60}")
for img, model, status, text in results:
    print(f"  {status:4s} {img:40s} [{model:15s}] {text[:80]}")
