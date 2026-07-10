# Changelog

## v1.21 — Jira-экспорт: retry на transient-сетевых ошибках + persisted state (фикс Этапа 8)
- Найдено на реальном повторном прогоне `--execute` против TPT: `ConnectionResetError` дважды оборвал создание Issue Link на живом сетевом соединении — без retry скрипт падал трейсбеком, а восстановление `key_by_placeholder` шло вручную парсингом текстового лога.
- `JiraClient._request()`: retry с экспоненциальным backoff (1с/2с/4с, до 4 попыток) только на transient-ошибках — `ConnectionResetError`/`urllib.error.URLError` (обрыв соединения) и HTTP 429/5xx. Логические 4xx (400/409 и т.п., например невалидный ADF) не ретраятся — повтор их не исправит, только задержит явную остановку. Каждая попытка логируется в stderr.
- `create_issue()`/`create_issue_link()` не идемпотентны: если Jira успела создать issue/link, а ответ не дошёл до клиента (обрыв после отправки, до получения ответа), retry рискует создать дубль — задокументировано комментарием в коде, не решается в этом проходе (требовало бы идемпотентных ключей на стороне Jira API, которых REST v3 не даёт).
- `execute_export()`: новый параметр `state_path` — после каждого успешного `create_issue()` весь `key_by_placeholder` (наш ID → реальный Jira-ключ) перезаписывается в JSON-файл на диске, не только печатается в лог. CLI: `--state-file` (по умолчанию `<plan>.jira-export-state.json` рядом с `--plan`).
- Не сделано намеренно (отложено, не в этом проходе): `--resume-from` для полноценного resume по `state_path` вместо пересоздания с нуля — ручная процедура (read-only GET-сверка реального состояния + точечное досоздание через `create_issue_link()`), уже отработанная на TPT, для разовых прогонов достаточна.
- `--selftest`: новый мок-`opener` (`_FlakyOpener`/`_FakeResponse`) кидает `ConnectionResetError` на заданном числе первых вызовов — проверяет, что (a) retry действительно ждёт и повторяет попытку, (b) issue создаётся один раз, а не дублируется при успехе со 2-й/3-й попытки, (c) на исчерпании всех попыток `JiraApiError` поднимается наверх, а не проглатывается молча. `time.sleep` подменяется на no-op на время этого блока, чтобы не удлинять `--selftest` реальным ожиданием backoff.
- Маппинг Epic/Issue/Subtask/Link, `--execute`/`--confirm`/dry-run логика не менялись — фикс сетевого уровня, не архитектуры Этапа 8.
- `docs/principles.md`, `schema/milestones_wbs.yaml` и `tasks/M*_tasks.yaml` не изменялись.

## v1.20 — Jira-экспорт: description в ADF-формате (фикс Этапа 8)
- Найдено при первом реальном запуске `--execute` против живого Jira Cloud-проекта (не в `--selftest`, который шёл только через `FakeJiraClient`): Jira Cloud REST API v3 отклоняет `description` как обычную строку (`HTTP 400 — "Wartość pola nie jest prawidłową treścią Atlassian Document Format (ADF)"`), требуется Atlassian Document Format.
- Добавлена `text_to_adf()` — оборачивает текст в `{"type": "doc", "version": 1, "content": [...]}`, каждая строка исходного текста -> отдельный параграф (`{"type": "paragraph", "content": [{"type": "text", "text": line}]}`), пустая строка -> пустой параграф (пропуски в исходном тексте не схлопываются). `execute_export()` теперь передаёт через неё `description` для Epic/Issue/Subtask вместо голой строки.
- Известное ограничение (не скрыто): risk-таблица Epic (Markdown-таблица из `render_risks()`, Этап 7.5) не разбирается в настоящую ADF-таблицу — остаётся построчным текстом с `|` внутри параграфов, читаемым, но без табличного форматирования в Jira. Полноценный Markdown→ADF-парсер (в т.ч. ADF-таблицы) — отдельная, более объёмная задача, если понадобится табличный вид; не реализован в этом проходе.
- `--selftest`: добавлена прямая проверка `text_to_adf()` на многострочном input (в т.ч. пустые строки и фрагмент risk-таблицы — подтверждает построчное сохранение без потери содержимого); проверка Sprint-в-description для `execute()`-ветки обновлена под ADF-структуру вместо голой строки.
- `resolve_issue_types()`: issuetype Epic теперь распознаётся и по локализованному имени `Epik` (польская локализация Jira, обнаружено на живом проекте TPT), не только по `Epic`.
- `schema/milestones_wbs.yaml` и `tasks/M*_tasks.yaml` не изменялись.

## v1.19 — Jira-экспорт (Этап 8)
- Добавлен `agent/jira_export.py` — экспорт смерженного и провалидированного плана (Этап 7.6) в уже существующий Jira-проект (проект не создаётся). Весь план -> 1 Epic; Milestone -> Label на каждой Issue/Subtask; WBS -> Issue, child Epic; Task -> Subtask под WBS-Issue (`description` = Interview/Verification checklist, Sprint = имя спринта); `depends_on`/`used_by` -> Issue Link `Blocks`; Риски/Deliverables -> секции текста в `description` Epic.
- Обязательное предусловие: перед маппингом скрипт запрашивает у целевого проекта реальные issuetypes (`GET /rest/api/3/project/{key}`) и подтверждает доступность Subtask. Если Subtask недоступен (team-managed проект) — не выбирает обходной путь молча, а останавливается явной ошибкой (`SubtaskUnavailableError`) с объяснением; плоская структура (WBS и Task — оба Issue, связаны Issue Link `Relates` по умолчанию) включается только по явному `--allow-flat-fallback`.
- Dry-run по умолчанию: только `GET`-запросы для определения схемы проекта + печать того, что было бы создано (Epic + N Issue + M Subtask + K Issue Link), без единого `POST`. Реальное создание — только `--execute` вместе с `--confirm` или интерактивным подтверждением в терминале (`confirm_execution()`); без него `--execute` не выполняет ничего.
- `depends_on` -> Issue Link `Blocks` напрямую; `used_by` создаёт связь только там, где пара ещё не покрыта `depends_on` с обратной стороны — `used_by` вторичен по построению (`sprint-mapping-rules.md`) и иногда указывает на WBS (агрегатор), а не Task, поэтому не дублируется бездумно в обе стороны.
- Риски/Deliverables в `description` Epic переиспользуют `render_risks()`/`render_deliverables()` из `generate_client_document.py` (Этап 7.5) целиком, включая уже применённый `clean_business_text()` — логика очистки текста риска не продублирована.
- Известное ограничение (v1, задокументировано, не скрыто): нативное поле Jira Sprint принимает ID существующего Sprint на Scrum-доске, а не текст — создание/сопоставление реальных Sprint через Agile REST API за рамками скрипта; имя спринта пишется первой строкой `description` Issue/Subtask вместо найденного `customfield_...`.
- Разорванные ссылки (`depends_on`/`used_by` на ID, отсутствующий в плане — например, следствие исключения задачи на Этапе 7.6) не приводят к падению и не пропускаются молча: попадают в `skipped_links` и явно печатаются в отчёте.
- `--selftest` — полностью офлайн через `FakeJiraClient` и фикстуры схемы проекта (без сетевых вызовов): маппинг Subtask-режима и плоского fallback, labels = Milestone ID, Sprint = имя (в т.ч. метка "Гиперподдержка"), остановка без Subtask/явный `--allow-flat-fallback`, совпадение счётчиков dry-run/`--execute`, видимость разорванной ссылки, гейт подтверждения перед `--execute`.
- `agent/examples/jira-project-schema.example.json` — офлайн-фикстура схемы company-managed Jira-проекта (в репозитории нет живого Jira-проекта для теста); `agent/examples/client-abc.jira-export.dryrun.log.txt` — dry-run лог на `client-abc.merged-plan.json` (39 Issue, 87 Subtask, 125 Issue Link, 1 пропущенная связь).
- `docs/agent-development-plan.md`: Этап 8 переведён в «готово», устаревшее описание маппинга (`Milestone → Epic`, `WBS → Label/Component`) заменено актуальной таблицей.
- `schema/milestones_wbs.yaml` и `tasks/M*_tasks.yaml` не изменялись.

## v1.18 — Именование спринтов датами (Этап 5/6/7.5)
- `agent/assemble_plan.py`: каждый спринт в `sprint_plan.sprints` получает поле `name`, вычисленное из уже существующих данных (`start_date`, `sprint_length_weeks`), без нового поля во входной схеме — `Спринт {N} ({дата начала}–{дата конца})`, дата начала = `start_date + (N-1) × sprint_length_weeks`.
- Спринт, целиком зарезервированный под `T-9.3.2` (`support_monitoring`, `reserve_exclusive`), получает в скобках дополнительную метку — название `WBS-9.3` из `schema/milestones_wbs.yaml` ("Гиперподдержка" в шаблоне v1): `Спринт 5 (2026-09-28–2026-10-11, Гиперподдержка)`.
- Проверено и намеренно НЕ сделано: `remediation` (T-7.3.1) метку не получает — эта Task участвует в обычном жадном распределении и делит спринт с другими Task на общих основаниях (не эксклюзивная резервация, как у `support_monitoring`), подписывать весь спринт её именем было бы неточно.
- `agent/sprint-mapping-rules.md`: добавлен раздел "Именование спринтов" с формулой и обоснованием решения по `remediation`.
- `agent/generate_client_document.py` (Этап 7.5): таблица плана показывает `name` спринта вместо голого номера, включая агрегированную строку-плейсхолдер интеграций (диапазон нескольких спринтов сворачивается в `Спринты N–M (дата начала N–дата конца M)`). CSV-таблица правок (`--corrections-output`) продолжает использовать голый номер в колонке `Спринт` — она должна оставаться простым редактируемым числом, сливаемым обратно через `merge-corrections.py` (Этап 7.6).
- `--selftest` во всех трёх скриптах обновлён и проходит чисто: формат имени спринта, единственный спринт с меткой "Гиперподдержка", отсутствие голых номеров в таблице плана.
- `agent/examples/client-abc.plan.json`, `client-abc.agreement.md`, `client-abc.corrections.csv`, `client-abc.validation-report.txt`, `client-abc.merged-plan.json`, `client-abc.merged-plan.validation-report.txt` пересчитаны и перегенерированы.
- `schema/milestones_wbs.yaml` и `tasks/M*_tasks.yaml` не изменялись.

## v1.17 — Приём правок и слияние с базовым планом (Этап 7.6)
- Добавлен `agent/merge-corrections.py` — принимает базовый JSON-план (Этап 6) и отредактированную CSV-таблицу правок (Этап 7.5) и сливает их по Task ID; результат слияния — вход для Этапа 8 (Jira-экспорт), не исходный JSON Этапа 6.
- Правила слияния: `Include=no` ИЛИ отсутствующая в таблице строка → Task исключается; непустые `Название`/`Спринт` → применяются к Task; строка без Task ID → новая custom Task, обязателен существующий WBS ID (новый WBS/Milestone через таблицу правок не вводится), `source.type: Internal Project Methodology` + `added_by: client_approval_process`.
- При исключении Task её ID вычищается из `dependencies`/`effort_estimates`/`sprint_plan.task_sprint`/`deliverables` (производные от `milestones` разделы), но `depends_on`/`used_by` оставшихся Task, ссылающиеся на исключённый ID, намеренно не переписываются — разрыв графа обязан всплыть находкой `integrity` в повторном прогоне `validate_plan.py`, а не потеряться молча. По той же логике у custom Task не выставляется `effort_estimates` — это ожидаемо даёт находку `cross_section`.
- Скрипт обязательно повторно прогоняет `validate_plan.py` (Этап 7) на смерженном плане и печатает журнал слияния вместе с отчётом валидатора.
- `--selftest`: неизменённая таблица не меняет план; `Include=no` и отсутствующая строка исключают Task одинаково; исключение Task с зависимыми даёт находку `integrity`; правки Название/Спринт применяются; новая custom Task в существующем WBS добавляется и даёт находку `cross_section` по `effort_estimates`; несуществующий WBS ID в новой строке отклоняется без создания нового WBS.
- Прогон на клиенте ABC (исключены `T-4.2.2`, `T-8.3.1`; изменены спринты `T-5.3.1`/`T-1.2.1`; добавлена custom Task `T-4.5-C1` в WBS-4.5): `agent/examples/client-abc.corrections.edited.csv` (вход), `agent/examples/client-abc.merged-plan.json` (результат), `agent/examples/client-abc.merged-plan.validation-report.txt` (журнал слияния + отчёт валидатора — показывает находку `integrity` от разрыва `T-4.2.1.used_by` и находку `cross_section` от отсутствующего `effort_estimates` у custom Task, ни одна не потеряна).
- `docs/agent-development-plan.md`: добавлен Этап 7.6 между 7.5 и 8, статус «готово»; в описании Этапа 8 уточнено, что вход — результат Этапа 7.6, а не сырой JSON Этапа 6.
- `schema/milestones_wbs.yaml` и `tasks/M*_tasks.yaml` не изменялись.

## v1.16 — CSV-таблица правок (расширение Этапа 7.5)
- `agent/generate_client_document.py`: добавлен второй артефакт — `--corrections-output` рендерит CSV-таблицу правок, по одной строке на каждую реальную Task плана (Task ID, WBS ID, Milestone ID, Название, Спринт, Include, Comment), `Include=yes` по умолчанию, `Comment` пуст. Это техническая рабочая таблица для консультанта/заказчика, не заменяет markdown-документ.
- В отличие от markdown-документа именованные интеграции (`T-6.4.2.1..N`) в CSV НЕ схлопнуты в плейсхолдер — таблица сливается обратно по настоящим Task ID (`agent/merge-corrections.py`, Этап 7.6), схлопывание там бы потеряло эту связь.
- CSV пишется в `utf-8-sig`, чтобы кириллица корректно открывалась в Excel, а не только в текстовых редакторах/git diff.
- `--selftest`: число строк совпадает с числом реальных Task плана (включая интеграции по отдельности), Include/Comment по умолчанию корректны, Спринт в CSV совпадает с `sprint_plan.task_sprint`.
- `agent/examples/client-abc.corrections.csv` — пример таблицы для клиента ABC.
- JSON-план (Этап 6), `schema/milestones_wbs.yaml` и `tasks/M*_tasks.yaml` не изменялись.

## v1.15 — Свернуть именованные интеграции в плейсхолдер (Этап 7.5)
- `agent/generate_client_document.py`: список интеграций формально фиксируется на интервью (T-1.3.1/T-1.3.2), а не на момент согласования плана — конкретные названия сервисов (Baselinker/DHL/PayU/...) больше не показываются в клиентском документе.
- Таблица плана: несколько сгенерированных `T-6.4.2.1..N` (`generated_from: T-6.4.2`) сворачиваются в одну строку `Настроить интеграцию [Компонент] согласно документации Comarch`; спринт — агрегированный (число или диапазон, если разошлись), зависимость — по общему `T-6.4.1` (у всех интеграций она одинакова).
- Зависимости других задач на конкретные интеграции (T-6.5.1 зависел от всех трёх по отдельности) схлопнуты в одно упоминание плейсхолдера — `human_refs()` дедуплицирует после подмены имени.
- Критерии завершения этапов: по одному пункту "интеграция X активна..." на каждую интеграцию (T-6.4.2.x) — схлопнуты в один обобщённый пункт; заодно нашёлся и закрыт смежный случай — чек-лист T-6.5.1 ссылался на слот голым кодом `T-6.4.2` в тексте, тоже схлопнут в тот же плейсхолдер.
- Риски: сверено — ни один текст риска не называет конкретный сервис, менять было нечего (только уже задокументированный инлайновый жаргон в R-2, не относится к названиям интеграций).
- `--selftest`: подтверждает, что Baselinker/DHL/PayU и голый код `T-6.4.2` не попадают в документ, плейсхолдер встречается ровно по одному разу в каждом месте (таблица, зависимости, критерии завершения).
- `agent/examples/client-abc.agreement.md` перегенерирован.
- JSON-план (Этап 6), `schema/milestones_wbs.yaml` и `tasks/M*_tasks.yaml` не изменялись — правка только рендеринга Этапа 7.5.

## v1.14 — Документ для согласования с заказчиком (Этап 7.5)
- Добавлен `agent/generate_client_document.py` — рендерит уже собранный и провалидированный план в клиентский Markdown-документ: шапка из `charter` (с явным пояснением про дату запуска vs. конец проекта), таблица Milestone → WBS → Task (спринт + зависимости названиями задач, не `T-ID`), критерии завершения этапов (агрегированные `verification_checklist`, без `interview_checklist`), только реально сработавшие для клиента риски (без `id`/`condition`/`source`), итоговая сводка со спринтами/длительностью/`sprint_plan.warning`.
- `clean_business_text()` вырезает скобочные технические уточнения (`WBS-ID`, `T-ID`, пути к файлам) из текста риска — безопасно, т.к. они всегда синтаксически необязательны; инлайновый жаргон внутри предложения не трогается (риск сломать грамматику мехакической правкой выше пользы; полноценная адаптация формулировок — за LLM-слоем Этапа 6).
- `--selftest`: все Task шаблона присутствуют в документе по названию, зависимости — названиями, структурные технические поля (`interview_checklist`, сырые `"url":`/`"basis":`, `id` риска) не просачиваются, ветки с `sprint_plan.warning` и с пустым `risks` проверены отдельно.
- `agent/examples/client-abc.agreement.md` — пример документа по клиенту ABC.
- `docs/agent-development-plan.md`: добавлен Этап 7.5 между 7 и 8, статус «в работе» (не «готово») — из-за известного ограничения на инлайновый жаргон в risk-текстах.
- `schema/milestones_wbs.yaml` и `tasks/M*_tasks.yaml` не изменялись.

## v1.13 — Регрессия по open-issues.md
- Прогнаны `agent/assemble_plan.py --selftest`, `agent/validate_plan.py --selftest` и валидатор (`integrity`/`source_url`/`source`/`checklist_shape`/`cross_section`) на пересобранном `agent/examples/client-abc.plan.json` — 0 находок по всем 5 проверкам, новых проблем не обнаружено.
- `open-issues.md`: каждому пункту присвоен явный статус. П.1 (сверка Task/чек-листов с документацией) — ОТКРЫТО, без изменений. П.2 (`effort-estimates.yaml` keyword-эвристика) — ЧАСТИЧНО: обход в `assemble_plan.py` стабилен и регрессионно проверен, сам справочник не менялся. П.3 (слот `T-6.4.2`) — ЗАКРЫТО: обработано на уровне генерации плана, подтверждено регрессией и валидатором.
- Ничего не блокирует переход к Этапу 8.
- `schema/milestones_wbs.yaml` и `tasks/M*_tasks.yaml` не изменялись.

## v1.12 — Закрыт open-issues.md п.1: used_by на Milestone ID → конкретный Task ID
- Все 16 случаев `used_by`, указывавшего на Milestone ID вместо Task/WBS ID (`tasks/M1..M9_tasks.yaml`), заменены на конкретного потребителя. Правило 7 (docs/principles.md): потребитель — конкретная Task, не milestone.
- Потребитель определялся по факту, не механической заменой: где есть прямой `depends_on` следующей задачи на исходную (T-2.4.3→T-3.1.1) или явная текстовая ссылка в `description` (T-2.2.2→T-3.1.2, T-2.3.2→T-3.2.1, T-4.1.3→T-9.1.1 через чек-лист "Lista czynności na start", T-4.2.2/T-4.4.2/T-4.5.3/T-6.5.1→T-7.1.1 через явный агрегатор "Свести результаты выполнения M2–M6") — эти решения подтверждены содержимым задач. Где ни то ни другое не нашлось (T-1.5.2→M2/M4/M5/M6, T-3.3.2→M4, T-5.6.1→M6, T-7.4.2→M8, T-8.3.1→M9), потребителем назначена первая Task целевого milestone/WBS без собственного `depends_on` (структурная точка входа) — за неимением более точного факта, не выдумано.
- WBS-уровневые `used_by` (например T-6.1.4 → WBS-6.5) не трогались — это не тот класс ошибки, они уже были валидны.
- `agent/validate_plan.py`: `--selftest` больше не ожидает 16 известных находок — теперь чистая регрессия (0 находок) на `agent/examples/client-abc.plan.json`. Подсказки в отчёте про "Milestone ID" избавлены от ссылки на закрытый пункт open-issues.md.
- `open-issues.md`: п.1 удалён (закрыт), остальные пункты перенумерованы (2→1, 3→2, 4→3); `agent/sprint-mapping-rules.md` и `agent/assemble_plan.py` — убраны комментарии-ссылки на закрытый пункт.
- `docs/agent-development-plan.md`: описание Этапа 7 обновлено — регрессия на реальном плане теперь 0 находок, а не 16; добавлена запись о закрытии.
- `agent/examples/client-abc.plan.json` и `agent/examples/client-abc.validation-report.txt` перегенерированы.
- `schema/milestones_wbs.yaml` не менялся; правки `tasks/M*_tasks.yaml` — только значения `used_by` (содержимое Task, не архитектура/структура YAML).

## v1.11 — Валидатор плана (Этап 7)
- Добавлен `agent/validate_plan.py` — линтер над выходом `assemble_plan.py`: `integrity` (ID в `depends_on`/`used_by` существуют), `source_url` (домен/раздел документации Comarch), `source` (нет Task без source, кроме `Internal Project Methodology`), `checklist_shape` (`interview_checklist`/`verification_checklist` — строго `list[str]`), `cross_section` (Task ⇔ `dependencies`/`effort_estimates`/`sprint_plan.task_sprint` без расхождений). Отчёт, не гейт — не блокирует вывод плана.
- `--selftest`: намеренная поломка каждой из 5 проверок на копии реального плана + regression на `agent/examples/client-abc.plan.json` (ожидается ровно 16 находок — уже задокументированная `open-issues.md` п.1 проблема, не новая).
- Найден и исправлен в `agent/assemble_plan.py` (`patch_stale_slot_dependencies`, не в шаблоне): `T-6.4.1.used_by` — та же проблема "ссылка на слот T-6.4.2", что раньше исправили только для `T-6.5.1.depends_on`. `open-issues.md` п.4 обновлён.
- `agent/examples/client-abc.plan.json` перегенерирован; добавлен `agent/examples/client-abc.validation-report.txt`.
- `docs/agent-development-plan.md`: статус Этапа 7 обновлён на «готово».
- `schema/milestones_wbs.yaml` и `tasks/M*_tasks.yaml` не изменялись.

## v1.10 — Исправлены непреднамеренные YAML-словари в чек-листах M2/M3/M5/M6/M7/M8
- Найдено при разборе `agent/examples/client-abc.plan.json`: 4 пункта `verification_checklist` в deliverables оказались вложенными словарями, а не строками. Причина — незакавыченный текст пункта чек-листа вида "Проверить, что X: Y, Z." парсится YAML как мэппинг `{"Проверить, что X": "Y, Z."}` из-за `": "` внутри строки.
- Сплошная проверка по всем `tasks/M1..M9_tasks.yaml` нашла ещё 5 таких же случаев в `interview_checklist`, не проявившихся в deliverables (deliverables агрегирует только `verification_checklist`).
- Исправлено во всех 9 случаях (`tasks/M2_tasks.yaml`: T-2.1.2, T-2.4.2; `tasks/M3_tasks.yaml`: T-3.1.1; `tasks/M5_tasks.yaml`: T-5.1.1; `tasks/M6_tasks.yaml`: T-6.3.1; `tasks/M7_tasks.yaml`: T-7.2.1, T-7.3.2; `tasks/M8_tasks.yaml`: T-8.1.1, T-8.1.2) — соответствующая строка обёрнута в кавычки, текст пункта не менялся ни на символ.
- Пример плана (`agent/examples/client-abc.plan.json`) перегенерирован — все элементы deliverables теперь строки.
- Это единственные затронутые файлы `tasks/M*_tasks.yaml` в этом проходе — правка синтаксическая (кавычки), не меняет содержание или структуру Task/WBS/Milestone.

## v1.9 — Сборка выходного пакета (Этап 6)
- Добавлен `agent/assemble_plan.py` — исполняемый Python-пайплайн (не описание, а код): Charter → Milestones → WBS → Tasks (+ вариативность WBS-6.4) → Dependencies → Оценки (`effort-estimates.yaml`) → Sprint-план (`sprint-mapping-rules.md`) → Риски (`risk-register.yaml`, включая R-7 по факту Sprint-плана) → Deliverables (агрегация `verification_checklist`).
- LLM подключается только последним шагом как enforced-контракт (`adapt_wording_with_llm`): разрешено менять только текстовые поля, попытка изменить структуру (id/depends_on/used_by/состав) отклоняется программно, а не только по описанию.
- `--selftest`: классификация всех реальных Task M1–M9 по `effort-estimates.yaml`, сверка с `examples` справочника, обе ветки WBS-6.4 (включая интеграцию вне `KNOWN_INTEGRATION_DOCS`), ветка дефицита времени (R-7), отказ LLM-контракта при попытке сломать структуру.
- Добавлен `agent/examples/client-abc.input.json` и результирующий `agent/examples/client-abc.plan.json` — прогон на примере клиента "ABC" из `agent/input-schema.json`.
- Найдено и обработано без изменения предыдущих артефактов (см. `open-issues.md`, п.3–4): 7 Task не классифицируются по keyword-эвристике `effort-estimates.yaml` (заведены точечные `MANUAL_TASK_TYPE_OVERRIDES` с обоснованием); `T-6.5.1.depends_on` ссылается на слот `T-6.4.2`, который пропадает при непустых `integrations` (обработано `patch_stale_slot_dependencies`).
- `docs/agent-development-plan.md`: статус Этапа 6 обновлён на «готово». Этап 8 (Jira-экспорт) в пайплайн не входит.
- `schema/milestones_wbs.yaml` и `tasks/M*_tasks.yaml` не изменялись.

## v1.8 — R-7 привязан к результату Sprint-плана; порядок сборки Этапа 6
- `agent/risk-register.yaml`, R-7: условие заменено с эвристики "разрыв start_date/target_launch_date < 8 недель" на прямую ссылку на флаг "не укладывается в срок" из `agent/sprint-mapping-rules.md` (`total_sprints_used > available_sprints`, шаг 5 алгоритма); в `v2_proposals` убран пункт про эту замену — она выполнена.
- `docs/agent-development-plan.md`, Этап 6: порядок сборки исправлен — Sprint-план (Этап 5) теперь идёт перед Рисками (Этап 4), а не после Deliverables, т.к. R-7 зависит от готового Sprint-плана.
- `schema/milestones_wbs.yaml` и `tasks/M*_tasks.yaml` не изменялись.

## v1.7 — Правило Milestone → Sprint (Этап 5)
- Добавлен `agent/sprint-mapping-rules.md` — единый граф зависимостей по `depends_on` через все M1–M9 (включая межмилестоновые связи), топологический порядок с тай-брейком по шаблону, жадное распределение по спринтам с трудоёмкостью из `agent/effort-estimates.yaml`.
- Контракт с `effort-estimates.yaml`: правило классифицирует Task по типу (эвристика Этапа 3) и берёт среднюю точку диапазона `base_estimate_hours`; для `remediation` (диапазон не задан в справочнике) введена отдельная константа-резерв `remediation_buffer_hours`; для `support_monitoring` (T-9.3.2, недельная нагрузка, а не оценка на Task) — отдельная обработка как нагрузки периода гиперподдержки после запуска.
- `target_launch_date` соответствует запуску (WBS-9.2); WBS-9.3/9.4 распределяются после него и не участвуют в проверке "укладывается/не укладывается в срок" — это ожидаемое продолжение работ, а не дефицит времени.
- Длительность спринта (2 недели), рабочие часы в день (8) и capacity на спринт (1 консультант) зафиксированы как константы v1 в самом правиле — соответствующих полей в `input-schema.json` нет, добавление новых полей не выполнялось без согласования.
- Если расчётный объём не укладывается в срок — генерация не блокируется, формируется явное предупреждение с фактическими числами для решения консультанта/PM.
- Номера спринтов не фиксируются в шаблоне — вычисляются агентом per-проект.
- `docs/agent-development-plan.md`: статус Этапа 5 обновлён на «готово».
- `schema/milestones_wbs.yaml` и `tasks/M*_tasks.yaml` не изменялись.

## v1.6 — Реестр рисков (Этап 4)
- Добавлен `agent/risk-register.yaml` — 7 рисков, выведенных из фактических
  ограничений и зависимостей в M1–M9 и `selection-rules.md`, каждый с
  проверяемым `condition` на полях `agent/input-schema.json` (`erp.version`,
  `integrations`, `features`, `users_count`, `start_date`/`target_launch_date`)
  и `related_wbs`. Риски без проверяемого condition (например, объём каталога
  товаров — поле для этого в input-schema.json пока нет) не включены,
  добавление такого поля вынесено в `v2_proposals`.
- `docs/agent-development-plan.md`: статус Этапа 4 обновлён на «готово».
- `tasks/M*_tasks.yaml` и `schema/milestones_wbs.yaml` не менялись.

## v1.5 — План разработки агента и справочник трудозатрат (Этап 3)
- Добавлен `docs/agent-development-plan.md`: 8 этапов разработки
  агента-планировщика со статусами (Этап 1 и Этап 2 — готово, Этап 3 — готово,
  Этапы 4–8 — не начаты).
- Добавлен `agent/effort-estimates.yaml` — справочник базовых оценок
  трудозатрат по 10 типам задач (выведены из фактических Task в M1–M9:
  interview, negotiation, configuration, content_data_preparation,
  verification, synthesis_reporting, remediation, approval_signoff,
  session_delivery, support_monitoring), с обоснованием оценок и правилом
  подбора типа задачи по ключевым словам (явного поля `task_type` в схеме
  Task пока нет — вынесено в `v2_proposals`).
- `tasks/M*_tasks.yaml` и `schema/milestones_wbs.yaml` не менялись.

## v1.4 — Приведение M7 в схеме к фактическому содержанию задач
- Подтверждено (владельцем шаблона): «Презентация и приёмка проекта» — правильное
  название M7, а не «Тестирование и приемка» из предыдущей версии схемы.
- `schema/milestones_wbs.yaml`: Milestone M7 переименован в «Презентация и приёмка
  проекта»; WBS-7.1 → «Подготовка к презентации проекта», WBS-7.2 → «Презентация
  решения заказчику», WBS-7.3 → «Обработка замечаний, выявленных на презентации»
  (описания обновлены соответственно). WBS-7.4 не изменился.
- `docs/source-map.md`: обновлена колонка Milestone и названия WBS-7.1–7.3 для M7.
- Пункт 2 из `open-issues.md` (расхождение M7 между схемой и задачами) закрыт как решённый.

## v1.3 — Сквозная проверка согласованности шаблона
- Проведена сквозная сверка репозитория: `schema/milestones_wbs.yaml` против всех
  `tasks/M1..M9_tasks.yaml`, `docs/source-map.md`, `docs/principles.md`,
  `docs/selection-rules.md` и `open-issues.md`.
- Подтверждено: покрытие WBS полное (каждый WBS-узел схемы имеет соответствующий
  набор Task в `tasks/`), `source-map.md` точно отражает фактические `source.url` из
  задач, во всех задачах с `source.type: Official Comarch Documentation` указан URL.
- Обнаружено и исправлено: пункт 1 в `open-issues.md` ("used_by указывает на
  Milestone/WBS ID вместо Task ID") учитывал только 10 из 28 фактических случаев.
  Список пересобран полностью по всем девяти файлам задач.
- Обнаружено и зафиксировано как новый пункт в `open-issues.md` (не исправлено в этом
  проходе, так как затрагивает структуру, а не точечное содержание): Milestone M7 и
  его WBS-7.1–7.3 в `tasks/M7_tasks.yaml` («Презентация и приёмка проекта») по смыслу
  расходятся с `schema/milestones_wbs.yaml` («Тестирование и приемка» /
  «Функциональное тестирование» и т.д.) — задачи реализуют демонстрацию сценария
  заказа заказчику, а не функциональное тестирование, предусмотренное схемой.

## v1.2 — Source Map и коррекция источников M1
- Собран `docs/source-map.md` — таблица WBS → фактические ссылки на документацию Comarch, сгенерирована из реальных `source.url` в задачах.
- Обнаружено: 7 задач M1 (WBS-1.1–1.4) были помечены `Official Comarch Documentation` без указания URL — Comarch не описывает процесс интервью/анализа требований, это консалтинговая работа.
- Все 9 задач WBS-1.1–1.4 (включая синтезирующие Task, например "Подготовить перечень функциональных требований") переведены в `source.type: Internal Project Methodology` — соответствует уже принятой классификации WBS-1.5.
- Незакрытых `❌ Missing URL` в шаблоне не осталось.

## v1.1 — Этап 0: исправление ошибок
- Исправлена ошибка отступов YAML в `schema/milestones_wbs.yaml` (`project.description`/`project.objective`), файл не парсился.
- Убраны пустые узлы `tasks:`, `dependencies:`, `risks:` из `schema/milestones_wbs.yaml` (контент живёт в `tasks/M*_tasks.yaml`).
- Обновлена устаревшая ссылка на документацию Comarch ERP Optima в `tasks/M9_tasks.yaml` (T-9.1.2, T-9.2.1): архивная версия `2024_5` → актуальная `2026`.
- Добавлен `docs/principles.md` с зафиксированными правилами WBS/Task, чек-листов и иерархией источников.

## v1.0
- Базовый шаблон: Milestones M1–M9, WBS, задачи по M1–M9 с checklist'ами и ссылками на документацию Comarch.
