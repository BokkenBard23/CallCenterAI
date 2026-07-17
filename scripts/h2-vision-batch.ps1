# Run vision_analysis.py on all h2-*.png screenshots in parallel batches.
$ErrorActionPreference = "Continue"
$root = "<repo>"
$shotsDir = Join-Path $root "docs\specs\screenshots"
$backend = Join-Path $root "backend"
$python = Join-Path $backend ".venv\Scripts\python.exe"

$basePrompt = @"
Ты — визуальный аудитор Frontend. Проект: CallCenterAI (React + Beeline Design System v2.5).
Проверь этот скриншот по критериям:
1. Фоны: консистентность тёмной темы, нет ли разных оттенков
2. Выравнивание: элементы выровнены, отступы консистентны
3. Цвета: соответствие channel color-coding (OPERATOR=зелёный #43a047, CLIENT=синий #1e88e5, ANY=оранжевый #e08600)
4. Кнопки/иконки: не битые, правильные DS-варианты, иконки не рендерятся как строки
5. Пустые блоки: нет ли незаполненных областей
6. Ошибки: нет ли red-ошибок, пустых ответов API, белых экранов
7. A11y: виден ли focus-visible, контрастность текста
8. Layout: нет ли наложения, обрезания, склеенных tab-ов

Дополнительный контекст для скриншота: {CTX}

Опиши все недочёты подробно на русском.
"@

$contextMap = @{
  "h2-navbar-home"             = "Главная страница / с NavBar (5 табов: Главная, Результаты, SpeechLab, Словари, История). Активный: Главная. URL: /"
  "h2-navbar-results"          = "После клика по табу Результаты. Активный: Результаты. URL: /results"
  "h2-navbar-speechlab"        = "После клика по табу SpeechLab. URL: /speechlab"
  "h2-navbar-dictionary"       = "После клика по табу Словари. URL: /dictionary или /dictionary/:id"
  "h2-navbar-history"          = "После клика по табу История. URL: /history"
  "h2-navbar-back-home"        = "После клика по табу Главная. URL: /"
  "h2-dashboard-initial"       = "Dashboard hub: welcome heading 'Анализ диалогов', 4 feature cards (Upload/SpeechLab/Dictionary/History), Stepper Card, Recent analyses секция"
  "h2-dashboard-upload-cta"     = "После клика CTA на Upload card — должен быть скролл к Stepper"
  "h2-dashboard-speechlab-cta" = "После клика CTA на SpeechLab card — должен быть переход на /speechlab"
  "h2-dashboard-history-cta"   = "После клика CTA на History card — должен быть переход на /history"
  "h2-dashboard-recent"        = "Recent analyses секция — должны быть записи или empty state"
  "h2-breadcrumbs-results"     = "Страница /results с breadcrumbs 'Главная › Результаты'"
  "h2-breadcrumbs-speechlab"   = "Страница /speechlab с breadcrumbs 'Главная › SpeechLab'"
  "h2-breadcrumbs-dictionary"  = "Страница /dictionary/test-session-0001 с breadcrumbs 'Главная › Словари › ...'"
  "h2-breadcrumbs-history"     = "Страница /history с breadcrumbs 'Главная › История'"
  "h2-breadcrumbs-click-home"  = "После клика по 'Главная' в breadcrumbs — должен быть переход на /"
  "h2-speaker-labels"          = "Вкладка 'Выделенный текст' на /results. 'Сотрудник'=зелёный label, 'Клиент'=синий label, должны различаться"
  "h2-speaker-css-vars"        = "CSS vars check screenshot — operator=#43a047 зелёный, client=#1e88e5 синий"
  "h2-modal-ai-open"           = "На /dictionary/test-session-0001 после выбора leaf-узла и клика 'AI анализ' — должен быть открыт modal AI анализа"
  "h2-modal-mutex-test"        = "После открытия AI анализа — клик по 'Mining'. AI должен закрыться, Mining — открыться. Mutex test"
  "h2-modal-mutex-reverse"     = "После открытия Mining — клик по 'AI анализ'. Mining должен закрыться, AI анализ — открыться"
  "h2-tree-tooltip"            = "Hover на обрезанный узел дерева (с многоточием) — должен появиться tooltip с полным именем"
  "h2-dictionary-page-init"    = "DictionaryEditorPage /dictionary/test-session-0001 в начальном состоянии"
}

$files = Get-ChildItem $shotsDir -Filter "h2-*.png" | Sort-Object Name
Write-Host ("Found {0} screenshots" -f $files.Count)

# Build jobs
$jobs = @()
foreach ($f in $files) {
  $name = $f.BaseName
  $img = $f.FullName
  $out = Join-Path $shotsDir ("ai-analysis-{0}.md" -f $name)
  $ctx = if ($contextMap.ContainsKey($name)) { $contextMap[$name] } else { "" }
  $prompt = $basePrompt -replace [regex]::Escape("{CTX}"), $ctx

  $jobs += [pscustomobject]@{
    Name = $name
    Image = $img
    Output = $out
    Prompt = $prompt
  }
}

# Run in parallel batches of 4 to avoid overload
$batchSize = 4
$completed = 0
for ($i = 0; $i -lt $jobs.Count; $i += $batchSize) {
  $batch = $jobs[$i..([Math]::Min($i + $batchSize - 1, $jobs.Count - 1))]
  $procJobs = @()
  foreach ($job in $batch) {
    $tmpPrompt = Join-Path $env:TEMP ("h2-prompt-{0}.txt" -f $job.Name)
    $job.Prompt | Out-File -FilePath $tmpPrompt -Encoding utf8 -NoNewline
    $p = Start-Process -FilePath $python `
      -ArgumentList @("-m","app.services.vision_analysis","--image","`"$($job.Image)`"","--prompt","`"$($job.Prompt)`"","--output","`"$($job.Output)`"") `
      -WorkingDirectory $backend `
      -NoNewWindow -PassThru `
      -RedirectStandardOutput (Join-Path $env:TEMP ("h2-{0}.out" -f $job.Name)) `
      -RedirectStandardError  (Join-Path $env:TEMP ("h2-{0}.err" -f $job.Name))
    $procJobs += [pscustomobject]@{ Job = $job; Proc = $p }
    Write-Host ("  -> started {0}" -f $job.Name)
  }
  foreach ($pj in $procJobs) {
    if (-not $pj.Proc.WaitForExit(180000)) {
      Write-Host ("  !! timeout for {0}, killing" -f $pj.Job.Name)
      try { $pj.Proc.Kill() } catch {}
    }
    $completed++
    $exists = Test-Path $pj.Job.Output
    Write-Host ("  [{0}/{1}] done {2} (output={3})" -f $completed, $jobs.Count, $pj.Job.Name, $exists)
  }
}

Write-Host "ALL DONE"
