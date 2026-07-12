import httpx
import ssl
import base64
import json
import sys
import os

sys.path.insert(0, '.')
from app.config import settings

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

screenshots = [
    ("fe-audit-upload-page.png", "Это главная страница загрузки RTF-файла диалога для анализа. Проверь визуальные проблемы: 1) Иконки на кнопках — рендерятся ли они как иконки или как текст (строки)? 2) Наложение текста 3) Обрезание текста 4) Общая композиция и читаемость 5) DS-compliance. Ответь на русском, кратко но точно."),
    ("fe-audit-dictionary-page.png", "Это страница Редактора словарей с открытым Sidesheet 'Mining'. Проверь визуальные проблемы: 1) Иконки на кнопках — рендерятся ли как иконки или как текст (строки)? Есть ли наложение EN+RU? 2) Кнопки вверху (AI анализ, Подсказать фразы, Дубликаты, Валидация, Статистика, Экспорт XML, Mining) — корректно ли отображаются? 3) Tabs в Mining Sidesheet — сколько видно? Есть ли обрезание? 4) Общая композиция 5) Любые визуальные баги. Ответь на русском, детально."),
    ("fe-audit-history-page.png", "Это страница истории анализов. Проверь визуальные проблемы: 1) Иконки на кнопках 2) Наложение текста 3) Обрезание 4) Композиция 5) Любые баги. Ответь на русском, кратко."),
]

for screenshot_name, prompt in screenshots:
    img_path = os.path.join("..", "docs", "specs", "screenshots", screenshot_name)
    if not os.path.exists(img_path):
        print(f"\n=== {screenshot_name} ===\nFILE NOT FOUND")
        continue

    with open(img_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    output_path = os.path.join("..", "docs", "specs", "screenshots", f"ai-{screenshot_name.replace('.png', '.md')}")

    payload = {
        "model": "gpt-5.4",
        "stream": False,
        "messages": [
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}}
            ]}
        ],
        "temperature": 0.3,
        "max_tokens": 4096,
    }

    models = ["gpt-5.4", "qwen-medium-dense", "qwen-medium"]
    
    for model in models:
        payload["model"] = model
        try:
            r = httpx.post(
                "https://api.ai.beeline.ru/api/v3/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {settings.beeline_api_key}", "Content-Type": "application/json"},
                verify=ctx,
                timeout=120.0,
            )
            if r.status_code != 200:
                print(f"  {model}: HTTP {r.status_code}, trying next...")
                continue
            
            data = r.json()
            choices = data.get("choices", [])
            if not choices:
                print(f"  {model}: empty choices, trying next...")
                continue
            
            content = choices[0].get("message", {}).get("content", "")
            if not content.strip():
                print(f"  {model}: empty content, trying next...")
                continue
            
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"\n=== {screenshot_name} ===\nModel: {model}\nSaved to: {output_path}\n")
            break
            
        except Exception as e:
            print(f"  {model}: error {e}, trying next...")
            continue
    else:
        print(f"\n=== {screenshot_name} ===\nALL MODELS FAILED")
