# Changelog

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
