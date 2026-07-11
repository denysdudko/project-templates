# Changelog

## v3.2 — Отменена реализация "Sprint algorithm redesign" (WBS-atomic greedy packing), schema/sprint_plan.yaml — фиксированный шаблон
Этап 5 уже был переведён на чтение готового шаблона вместо вычисления
(см. v3.0) — эта запись фиксирует явную отмену любой попытки вернуть
WBS-atomic greedy-упаковку и заменяет содержимое `schema/sprint_plan.yaml`
новой ручной разбивкой по спринтам, утверждённой отдельно от кода.

- **`schema/sprint_plan.yaml` переписан** — 4 спринта вместо прежних 4-х
  (число совпадает, группировка WBS и `duration_weeks` — другие):
  спринт 1 (1 нед., M1: `WBS-1.1`–`WBS-1.5`), спринт 2 (1 нед., M2–M4:
  `WBS-2.1`–`WBS-4.5`), спринт 3 (2 нед., M5–M6: `WBS-5.1`–`WBS-6.5`),
  спринт 4 (2 нед., M7–M9 кроме гиперподдержки: `WBS-7.1`–`WBS-9.2` +
  `WBS-9.4`). Все 38 WBS `schema/milestones_wbs.yaml` покрыты ровно один
  раз, без дублей/пропусков (регрессия — `assemble_plan.py --selftest`).
- **`agent/assemble_plan.py` не изменён.** Проверено явно: код уже не
  содержит ни графа зависимостей WBS, ни greedy-упаковки, ни расчёта
  длительности спринта от `effort-estimates.yaml` — Этап 5 с v3.0 только
  читает `schema/sprint_plan.yaml` (`wbs_sprint_number_by_wbs`), проверяет
  полноту/отсутствие дублей и считает даты спринтов последовательно от
  `charter.start_date`. Никакой реализации WBS-atomic greedy packing по
  этой версии не начиналось и, соответственно, откатывать было нечего —
  прежняя попытка (см. v2.0) была полностью удалена в v3.0.
- **R-7 и sprint fit-check не изменились**: сравнение
  `weeks_used_until_launch` (сумма `duration_weeks` до спринта WBS-9.2)
  с `available_weeks` (`target_launch_date`) — та же логика, что и раньше;
  меняются только входные даты (из нового шаблона), не сам расчёт.
- **`agent/sprint-mapping-rules.md`**: раздел "Калибровка под конкретный
  проект" переписан в "Изменение шаблона" — `schema/sprint_plan.yaml`
  зафиксирован как единый утверждённый шаблон для всех клиентов, а не
  отправная точка, которую консультант перекраивает под каждый проект;
  пересмотр самого шаблона — редкое осознанное решение, не штатный шаг.
- **Регрессия**: `client-abc.plan.json` пересобран под новые даты/группировку
  спринтов (ожидаемо — шаблон сведён по-другому), связанные артефакты
  (`client-abc.validation-report.txt`, `client-abc.jira-export.dryrun.log.txt`)
  пересобраны следом. `assemble_plan.py --selftest`: все 38 WBS покрыты
  ровно один раз, регресс на Этапах 6–8 не появился.

## v3.1 — Гиперподдержка вынесена из WBS-9.3 в отдельный Epic "Поддержка"
Гиперподдержка (согласование периода, мониторинг журнала синхронизации,
завершение периода) больше не описывается WBS/Task шаблона — она ведётся
отдельным Epic в Jira, создаваемым `jira_export.py` **всегда** при
экспорте (без флага, независимо от конкретного плана).

- **`schema/milestones_wbs.yaml`**: `WBS-9.3` (Гиперподдержка) удалён из
  Milestone M9. `WBS-9.4` (Завершение проекта) не изменился.
- **`tasks/M9_tasks.yaml`**: `T-9.3.1`/`T-9.3.2`/`T-9.3.3` удалены.
  `T-9.2.2.used_by` теперь указывает на `WBS-9.4` (было `WBS-9.3`);
  `T-9.4.1.depends_on` теперь указывает на `T-9.2.2` (было `T-9.3.3`);
  описание и `verification_checklist` `T-9.4.1` больше не упоминают
  результаты гиперподдержки (ссылались на удалённую `T-9.3.3`).
- **`agent/effort-estimates.yaml`**: `T-9.3.3` убран из `examples`
  `approval_signoff`; тип `support_monitoring` удалён целиком (его
  единственный пример, `T-9.3.2`, был единственной задачей этого типа в
  шаблоне — тип стал бы орфанным). Комментарий про WBS-контекстную
  эвристику классификации (пример на WBS-9.3) переписан без ссылки на
  удалённый WBS.
- **`schema/sprint_plan.yaml`**: запись `WBS-9.3` (спринт 4) удалена;
  `WBS-9.4` переномерован в спринт 4 (было 5) — пустого спринта-заглушки
  не остаётся.
- **`agent/assemble_plan.py`**: убраны `HYPERCARE_WBS_ID`, метка
  "Гиперподдержка" в имени спринта (`sprint_name()` больше не принимает
  `label`), override `T-9.3.1` в `MANUAL_TASK_TYPE_OVERRIDES` (пример в
  комментарии заменён на `T-8.1.1`), ветка `support_monitoring` в
  `effort_for_task()` (тип удалён из справочника), неиспользуемая
  `find_wbs_name()`. `charter.target_launch_date_definition` и
  `sprint_plan.post_launch_note` переписаны: упоминают только `WBS-9.4`
  как продолжающийся после запуска, плюс явное указание, что
  гиперподдержка ведётся отдельным Epic и не входит в этот план.
  `--selftest`: убраны тесты/ассерты на метку "Гиперподдержка" в имени
  спринта; добавлена регрессия «83 → фактическое число Task в шаблоне»
  неявно (через существующие проверки классификации).
- **`agent/jira_export.py`**: новый `build_support_epic_issues()` —
  строит Epic "Поддержка" (`SUPPORT_EPIC_SUMMARY`, локализуемая константа,
  не хардкод языка) + единственную Task-журнал (`SUPPORT_LOG_TASK_SUMMARY`)
  внутри, тем же issuetype-паттерном, что основной Epic
  (`schema.epic_type`/`schema.task_type`), тем же ADF-паттерном описания
  (`_adf_text_paragraph`). `ExportPlan` получил поля `support_epic`/
  `support_task`; `execute_export()` создаёт их всегда, сразу после
  основного Epic, до WBS-Issue; `format_dry_run_report()` показывает их в
  dry-run отчёте. Без Subtask/Sprint/timetracking; не участвует в
  sprint-планировании/R-7/effort-оценках/`--create-sprints` — эти
  механизмы читают только `plan["milestones"]`/`plan["sprint_plan"]`, куда
  этот Epic не входит ни при каких условиях. Комментарии/докстринги,
  описывавшие прежнее исключение `WBS-9.3` из привязки к Sprint
  (`build_wbs_sprint`), переписаны — такого исключения больше не бывает
  ни для одного WBS.
- **`agent/sprint-mapping-rules.md`**: раздел "Гиперподдержка и завершение
  проекта (WBS-9.3, WBS-9.4)" переписан в "Завершение проекта (WBS-9.4) и
  гиперподдержка вне плана" — гиперподдержка описана как решение
  `jira_export.py`, не запись `schema/sprint_plan.yaml`. Метка
  "Гиперподдержка" в имени спринта убрана из раздела "Даты спринтов".
- **`docs/agent-development-plan.md`**: Этап 5 и Этап 8 (таблица маппинга
  + абзац `--selftest`) обновлены под новую структуру; список Task с
  keyword-эвристикой без совпадения — `T-9.3.1` убран (6 Task вместо 7).
- **`docs/source-map.md`**: строка `WBS-9.3` убрана из таблицы
  трассируемости WBS → документация Comarch.
- **`open-issues.md`**: п.2 (`effort-estimates.yaml` keyword-эвристика) —
  `T-9.3.1` убран из списка, с пометкой, что Task удалена вместе с WBS.
- **Регрессия**: `client-abc.plan.json` пересобран (83 Task в шаблоне без
  вариативности WBS-6.4, было 86; 38 WBS, было 39; 4 спринта, было 5) и
  связанные артефакты (`client-abc.validation-report.txt` — 0 находок,
  `client-abc.jira-export.dryrun.log.txt` — теперь показывает 2 Epic +
  1 Task поддержки). `assemble_plan.py --selftest` и
  `jira_export.py --selftest` — гейт, зелёные; регрессии на M1–M8 нет
  (проверено: диапазон изменений в `client-abc.plan.json` ограничен
  разделом M9/`sprint_plan`, остальные Milestones/WBS байт-в-байт
  идентичны).

## v3.0 — Убраны Этапы 7.5/7.6 и алгоритм Этапа 5, добавлены schema/sprint_plan.yaml и create_project.py (изменение архитектуры пайплайна, не точечный фикс)
**Это изменение архитектуры пайплайна**, а не точечный фикс — убирает два
целых этапа из пайплайна, заменяет вычисляемый алгоритм Этапа 5 ручным
шаблоном и добавляет единую точку входа поверх уже существующих шагов.

- **Убраны Этапы 7.5/7.6.** `agent/generate_client_document.py` и
  `agent/merge-corrections.py` удалены вместе с их примерами
  (`client-abc.agreement.md`, `client-abc.corrections*.csv`,
  `client-abc.merged-plan.json`, `client-abc.merged-plan.validation-report.txt`).
  Промежуточного документа для согласования с заказчиком и приёма правок
  через CSV в пайплайне больше нет: `agent/jira_export.py` (Этап 8) берёт
  на вход план Этапа 6, провалидированный Этапом 7, напрямую. Пять функций,
  которые Этап 8 переиспользовал из `generate_client_document.py`
  (`clean_business_text`, `human_refs`, `build_id_to_name`,
  `integration_task_ids`, `render_risks` — сборка ADF-таблицы Рисков в
  description Эпика), перенесены как есть в `agent/jira_export.py`, не
  переизобретены.
- **Этап 5 стал шаблоном, не алгоритмом.** Из `assemble_plan.py` убран весь
  код построения WBS-графа зависимостей и жадной упаковки по трудоёмкости
  (`topological_order`, `build_wbs_dependencies`, `SprintBook`,
  `sprint_duration_weeks_for`, `WEEKLY_CAPACITY_HOURS`,
  `POST_LAUNCH_WBS_IDS`, `SUPPORT_MONITORING_TASK_ID`; `heapq`/`math`
  больше не импортируются) — v2.0 (см. запись выше) полностью удалён, не
  адаптирован. Новый файл `schema/sprint_plan.yaml` — эталонное
  распределение всех WBS (M1–M9) по спринтам, часть шаблона (общий для всех
  клиентов, как `schema/milestones_wbs.yaml`), заполняется и калибруется
  консультантом вручную. `assemble_plan.py` только читает готовое
  расписание: Task наследует спринт своего WBS целиком, даты вычисляются
  последовательно накопительно от `charter.start_date` конкретного клиента,
  длительность каждого спринта — `duration_weeks` из шаблона (ручное
  решение, не производная от трудоёмкости). Единственная проверка —
  `wbs_sprint_number_by_wbs()`: каждый реальный WBS плана покрыт ровно
  одним спринтом (не пропущен, не задублирован), иначе явный `ValueError`.
  `WBS-9.3`/`WBS-9.4` (Гиперподдержка/Завершение) стали обычными записями
  шаблона наравне с любым другим WBS — прежняя отдельная Task-level логика
  и эксклюзивная резервация под `T-9.3.2` удалены за ненадобностью.
  `schema/sprint_plan.yaml` заполнен отправной точкой — последним расчётом
  прежнего алгоритма на `agent/examples/client-abc.input.json` (5 спринтов:
  1–3 — основная упаковка M1–M9 до запуска, 4 — вся `WBS-9.3` одним
  спринтом (2 нед., номинально), 5 — `WBS-9.4` (1 нед.); раньше
  `WBS-9.3` расходилась по 3 спринтам Task-level, теперь сведена в один —
  осознанная ручная калибровка консультанта, не автоматический перенос).
  `agent/sprint-mapping-rules.md` переписан как описание формата
  `schema/sprint_plan.yaml` и правил его ручного заполнения/калибровки, не
  алгоритм. `R-7` пересчитывается по той же логике, что в v2.0 (сумма
  фактических `duration_weeks` спринтов до `T-9.2.2` против доступных
  календарных недель), но недели теперь не вычисляются, а читаются из
  шаблона. `estimation-config.yaml` (`sprint_duration_weeks`/
  `team_capacity_per_sprint`) больше не читается кодом для расчёта длины
  спринта — остаётся только справочным ориентиром для консультанта;
  `team_capacity_per_sprint` по-прежнему используется для
  `remediation_buffer_hours` (Этап 3, не изменилось).
- **Jira-экспорт: WBS-9.3 больше не исключается из привязки к Sprint.**
  Раньше (`jira_export.py`, `build_wbs_sprint`) `WBS-9.3` не попадала в
  `--create-sprints`-привязку, т.к. её Task расходились по нескольким
  спринтам. Теперь, когда любой WBS лежит ровно в одном спринте по
  построению шаблона, исключений больше не бывает — `build_wbs_sprint`/
  `build_sprint_wbs_ids` не переписаны (логика уже была корректной для
  этого случая), обновлён только `--selftest` (регрессия: `excluded_wbs`
  пуст).
- **Новый `agent/create_project.py` — единая точка входа.** Принимает
  клиентский `input-schema.json` и параметры подключения к Jira одной
  командой: `assemble_plan` (Этап 6) → `validate_plan` (Этап 7,
  предупреждение, не гейт) → `jira_export` (Этап 8, `--execute
  --create-sprints` — опционально, по умолчанию dry-run). Никакого
  промежуточного файла для скачивания консультантом между шагами — но
  собранный план всё равно сохраняется на диск как внутренний артефакт
  аудита (`agent/runs/{client_id}/plan.json`,
  `agent/runs/{client_id}/jira-export-state.json` при `--execute`) — тот
  же артефакт, что уже спасал при диагностике дублей на живом TPT (Этап 8),
  отказываться от него не стали. `agent/jira_export.py` рефакторен: логика
  Этапа 8 вынесена из `main()` в переиспользуемую `run_export()`, которую
  вызывают и CLI, и `create_project.py`, — не дублирована.
- **Регрессия.** `client-abc.plan.json` пересобран (5 спринтов вместо 6 —
  ожидаемо, шаблон сведён по-другому) и связанные артефакты
  (`client-abc.validation-report.txt`, `client-abc.jira-export.dryrun.log.txt`
  — теперь строится напрямую из `client-abc.plan.json`, без промежуточного
  merged-plan). `assemble_plan.py --selftest`: тесты упаковки WBS
  (`big_wbs_plan`/`early_close_plan`) убраны, добавлены тесты чтения
  `schema/sprint_plan.yaml` (полное покрытие всех 39 WBS шаблона; синтетика
  на пропущенный/задублированный WBS — явный `ValueError`; `build_sprint_plan`
  целиком на синтетическом шаблоне). `jira_export.py --selftest`: базовый
  `examples/client-abc.plan.json` вместо удалённого `merged-plan.json`;
  убраны проверки, специфичные для демо-правок Этапа 7.6 (custom Task
  `T-4.5-C1` без `effort_estimates`, битая ссылка `T-4.2.1.used_by →
  T-4.2.2`) — на чистом плане их источника больше нет.
  `create_project.py --selftest` — новый, полностью офлайн.

## v2.0 — Этап 5: упаковка WBS целиком в спринты, переменная длина (изменение алгоритма, не точечный фикс)
**Это изменение архитектуры алгоритма Этапа 5**, а не точечный фикс —
затрагивает `sprint-mapping-rules.md` (раздел "Алгоритм распределения"
переписан), `assemble_plan.py` (`build_sprint_plan`/`SprintBook`) и
пересобранные примеры (`client-abc.plan.json` и всё, что от него зависит).
`schema/milestones_wbs.yaml`/`tasks/M*_tasks.yaml` не менялись — только
читаются, как и раньше.

- **Единица упаковки — WBS целиком** (сумма трудоёмкости всех его Task,
  включая `remediation_buffer_hours`, если применимо), а не отдельная Task.
  Причина: жадное распределение по Task могло раскидать один WBS по
  нескольким спринтам, что не отражает практику (WBS сдаётся консультантом
  как единый результат).
- **WBS-уровневый граф зависимостей**: WBS A зависит от WBS B, если хотя бы
  одна Task из A имеет `depends_on` на Task из B (зависимости внутри
  одного WBS не считаются межблочными). Топологический порядок, тай-брейк
  — порядок в шаблоне (тот же принцип, что раньше для Task).
- **Жадная упаковка WBS-блоков**: очередной WBS целиком добавляется в
  текущий спринт, пока помещается в остаток `team_capacity_per_sprint`
  (`estimation-config.yaml`); как только следующий WBS целиком не
  помещается — спринт закрывается, даже если короче номинальных
  `sprint_duration_weeks`. WBS больше capacity сам по себе не режется —
  получает спринт целиком под себя (спринт растягивается).
- **Переменная длина спринта**: `ceil(часы_в_спринте / недельная_нагрузка)`
  недель (`недельная_нагрузка = team_capacity_per_sprint /
  sprint_duration_weeks`, по умолчанию 80/2=40ч/неделю) вместо
  фиксированного грида по `sprint_duration_weeks`. Даты вычисляются
  последовательно накопительно (следующий спринт стартует сразу после
  конца предыдущего), а не по формуле `start_date + (N-1) × const`.
  Спринт, зарезервированный только под `T-9.3.2` (`hours_used = 0`),
  получает номинальную `sprint_duration_weeks` — формула для нуля часов
  календарно не определена.
- **WBS-9.3/WBS-9.4 (Гиперподдержка/Завершение) — исключения, как и было**:
  не участвуют в WBS-упаковке, планируются по отдельной Task тем же
  Task-level алгоритмом, что в v1 (T-9.3.1 не имеет `depends_on` в
  шаблоне, `T-9.3.2` резервируется отдельным спринтом после T-9.3.1).
- **R-7 пересчитан**: раньше сравнивался `total_sprints_used >
  available_sprints` (при фиксированной длине спринта — число спринтов
  само по себе было показателем). Теперь сравниваются фактические недели:
  `weeks_used_until_launch` (сумма длительностей спринтов до запуска)
  против `available_weeks` (`(target_launch_date - start_date) / 7`).
  Ключи `total_sprints_used`/`available_sprints` в `sprint_plan` заменены
  на `weeks_used_until_launch`/`available_weeks` — `generate_client_document.py`
  (`render_summary`) обновлён под новые ключи.
- **Jira-экспорт (Этап 8, `--create-sprints`)**: привязка к реальному
  Sprint теперь только для WBS-Issue (не Subtask — Jira Sub-task не хранит
  Sprint независимо от родителя, см. v1.28 ниже), и без прежнего правила
  "самый ранний спринт из нескольких" — раз WBS теперь целиком лежит в
  одном спринте по построению, берётся этот спринт напрямую
  (`build_wbs_sprint`/`build_sprint_wbs_ids`). Прежние
  `SprintLinkingUnavailableError`/`require_sprint_linking_possible` (v1.28)
  удалены — структурно больше не нужны: WBS-Issue не бывает Subtask
  независимо от режима (Subtask/плоский).
- **Backlog-пункт зафиксирован** (`open-issues.md`, п.4, не реализован в
  этом проходе): выставление `duedate`/стартовой даты Issue/Subtask по
  трудоёмкости внутри спринта — отдельная, более объёмная задача.
- **Регрессия**: `assemble_plan.py --selftest` — новые кейсы (WBS больше
  capacity не режется; WBS закрывает спринт раньше номинальной длины) +
  вся существующая регрессия зелёная. `validate_plan.py`,
  `generate_client_document.py`, `merge-corrections.py`, `jira_export.py`
  `--selftest` — все зелёные после обновления под новые ключи `sprint_plan`.
  `client-abc.plan.json` пересобран с другими датами/номерами спринтов —
  это ожидаемо (алгоритм изменился), не тихая регрессия; все зависимые
  примеры (`agreement.md`, `corrections.csv`/`corrections.edited.csv`,
  `merged-plan.json`, `merged-plan.validation-report.txt`,
  `jira-export.dryrun.log.txt`) пересобраны тем же способом, что и раньше
  (`generate_client_document.py`, `merge-corrections.py`, `jira_export.py
  --schema-fixture`), с теми же демонстрационными правками в
  `corrections.edited.csv` (исключены T-4.2.2/T-8.3.1, изменены спринты
  T-1.2.1/T-5.3.1, добавлена custom Task T-4.5-C1), просто под новые
  валидные номера спринтов.

## v1.28 — Jira-экспорт: привязка к Sprint невозможна для Subtask — явная остановка
- Найдено на реальном `--execute --create-sprints` против TPT (первая попытка после v1.27): лог показывал "Привязано к Sprint N: NN issue" для всех 87 задач, но проверка через `GET /rest/agile/1.0/sprint/{id}/issue` показала **0 реально привязанных** во всех 6 Sprint. Причина — Jira Sub-task не хранит поле Sprint независимо от родителя: `POST /rest/agile/1.0/sprint/{id}/issue` для ключа Subtask возвращает `204 OK`, но тихо ничего не делает (`customfield` Sprint остаётся `null` даже сразу после вызова). Тот же вызов на обычном Issue (WBS-уровня, `Zadanie`) сработал мгновенно и корректно — это подтверждает архитектурное ограничение Jira, не баг в коде.
- Проверено дополнительно: привязка к родительскому WBS-Issue вместо Task была бы неточной — 7 из 39 WBS в `client-abc` содержат Task, распределённые по нескольким спринтам (например, `WBS-9.3`: спринты 4/5/6), такая замена ошибочно приписала бы им один спринт.
- Добавлена `require_sprint_linking_possible()` + `SprintLinkingUnavailableError` (по аналогии с `SubtaskUnavailableError`): `--create-sprints` в стандартном Subtask-режиме теперь останавливается явной ошибкой **до** любых GET/POST к доске — не создаёт Sprint и не делает вид, что привязка удалась. Работает только с `--allow-flat-fallback` (Task экспортируются как Issue, не Subtask) — там нативное поле Sprint устанавливается корректно.
- `--selftest`: `require_sprint_linking_possible(flat_fallback=False)` — останавливается явной ошибкой; `flat_fallback=True` — пропускается без ошибки.
- Диагностический побочный эффект (тестовая привязка `WBS-1.1` к Sprint 1 при проверке гипотезы) обнаружен и отменён (`POST /rest/agile/1.0/backlog/issue`) сразу после подтверждения находки.
- `link_issues_to_sprints()`/`chunked()`/`build_sprint_task_ids()` (v1.27) не удалялись — остаются рабочими для плоского режима, где Task = Issue.
- `docs/principles.md`, `schema/milestones_wbs.yaml` и `tasks/M*_tasks.yaml` не изменялись.

## v1.27 — Jira-экспорт: реальная привязка Issue/Subtask к Sprint (--create-sprints)
- После `--execute --create-sprints`: реальные ключи Issue/Subtask (по `sprint_plan.task_sprint`) привязываются к реально созданным Sprint через `POST /rest/agile/1.0/sprint/{id}/issue`, пакетами по `MAX_ISSUES_PER_SPRINT_LINK_BATCH = 50` (лимит Jira Agile API). Раньше (v1.22) привязка сознательно не делалась — имя спринта оставалось только текстом в description; теперь нативное поле Jira Sprint проставляется напрямую, текст в description остаётся как было (дублирует, не заменяет).
- Новая функция `link_issues_to_sprints()` (вызывается после создания и issues, и sprints) и `JiraClient.add_issues_to_sprint()`/`FakeJiraClient.add_issues_to_sprint()`. В отличие от `create_issue`/`create_issue_link`, эта операция идемпотентна на стороне Jira — повторная привязка уже привязанного issue не создаёт дубль.
- Task, для которых в `sprint_task_ids` есть номер спринта, но issue не был создан (нет ключа в `key_by_placeholder`), не привязываются молча — печатается явно, тем же паттерном, что `skipped_links`.
- Dry-run (`format_sprint_dry_run_report`) показывает превью привязки — сколько задач и батчей на каждый Sprint, без единого POST.
- `--selftest`: `build_sprint_task_ids()` покрывает все Task плана; `chunked()` режет на батчи без потерь/дублей (синтетический кейс >100 элементов); `link_issues_to_sprints()` через `FakeJiraClient` — issue без ключа пропускается явно, не молча.
- Проверено на живом TPT: dry-run показывает корректное распределение (87 задач по 6 спринтам, без потерь).
- Маппинг Epic/Issue/Subtask/Link, создание Sprint (`create_sprint`) не менялись — это отдельный шаг поверх них.
- `docs/principles.md`, `schema/milestones_wbs.yaml` и `tasks/M*_tasks.yaml` не изменялись.

## v1.26 — Параметры сетки спринтов вынесены в agent/estimation-config.yaml (Этап 5)
- Добавлен `agent/estimation-config.yaml` — `sprint_duration_weeks` (по умолчанию 2) и `team_capacity_per_sprint` (по умолчанию 80 часов). Генерация сетки спринтов и жадное распределение задач (топологическая сортировка по `depends_on`, размещение с учётом capacity — `agent/sprint-mapping-rules.md`, Этап 5) уже были реализованы в `assemble_plan.py` и работали; этой правкой константы `SPRINT_LENGTH_WEEKS`/`CAPACITY_PER_SPRINT_HOURS` (были захардкожены в коде) стали конфигурируемыми без изменения `assemble_plan.py`.
- `load_estimation_config()` читает YAML при импорте модуля; значения по умолчанию (2 недели, 80 часов) совпадают с прежними константами — регенерация `client-abc.plan.json` побайтово идентична предыдущей.
- `HOURS_PER_WORKING_DAY` (промежуточная константа для вычисления capacity) убрана — `team_capacity_per_sprint` теперь прямое значение в часах, не производное от рабочих часов в день; нигде больше не использовалась. `REMEDIATION_BUFFER_HOURS = 0.2 * capacity` остаётся константой в коде (не вынесена в конфиг — этого не просили).
- `agent/sprint-mapping-rules.md`, раздел "Константы v1" — обновлён: значения по умолчанию читаются из `estimation-config.yaml`, а не захардкожены в `assemble_plan.py`; расширение до per-клиентской конфигурации через `input-schema.json` по-прежнему предложение для v2, не вводится этой правкой.
- WBS-9.3/WBS-9.4 (гиперподдержка/завершение) по-прежнему не входят в `fits_in_target_launch_date`-проверку и в R-7 — не менялось, уже было реализовано (v1.7/v1.8).
- `assemble_plan.py --selftest` и `jira_export.py --selftest` проходят целиком.
- `schema/milestones_wbs.yaml` и `tasks/M*_tasks.yaml` не изменялись (только читаются, как и раньше).

## v1.25 — Jira-экспорт: originalEstimate в целых h/m (Jira не принимает дробные единицы)
- Найдено на реальном `--execute` против TPT (первый прогон с timetracking из v1.22): Epic + 39 WBS-Issue создались чисто, но первая же Subtask (T-1.1.1, `effort_hours=1.5`) упала — `HTTP 400: {"timetracking":"Określ prawidłową wartość dla rejestrowania czasu"}` ("Specify a valid value for time tracking"). Причина: Jira `timetracking.originalEstimate` — "pretty duration" (`"1h 30m"`), не принимает дробные единицы вроде `"1.5h"`, которые писал `f"{hours}h"`.
- Добавлена `hours_to_jira_duration()` — раскладывает дробные часы на целые `h`+`m` (округление до минуты): `1.5 → "1h 30m"`, `0.75 → "45m"`, `10.0 → "10h"`. `_timetracking_fields()` и dry-run отчёт используют её вместо голого `f"{hours}h"`.
- `--selftest`: `hours_to_jira_duration()` проверена на характерных значениях плана (1.5/0.75/0.5/0.25/1.25/10.0 часов), результат не должен содержать точки — именно дробный формат отклонил живой TPT.
- Маппинг Epic/Issue/Subtask/Link и ADF-таблицы (v1.24) не менялись — точечный фикс формата длительности.
- `docs/principles.md`, `schema/milestones_wbs.yaml` и `tasks/M*_tasks.yaml` не изменялись.

## v1.24 — Jira-экспорт: description Эпика — настоящие ADF-таблицы, отдельный блок "Описание"
- `description` Эпика при `--execute` теперь строится напрямую как ADF (`build_epic_description_adf`, поле `PlannedIssue.description_adf`), а не через построчный `text_to_adf()` — закрывает известное ограничение из v1.19 (markdown-таблица рисков оставалась построчным текстом с `|`, не настоящей ADF-таблицей).
- Добавлен отдельный блок "Описание" (из `charter.description` = `project.description` в `schema/milestones_wbs.yaml`, отдельно от уже существующего "Цель" = `charter.objective`/`project.objective`).
- "Риски проекта" — настоящая ADF-таблица (`build_risks_adf_table`): столбцы "Риск"/"Затрагивает", `tableRow`/`tableCell`/`tableHeader`; ячейка "Риск" — полноценный ADF-параграф (допускает форматирование), не голая строка. `clean_business_text()`/`human_refs()` из `generate_client_document.py` (Этап 7.5) переиспользованы как есть.
- "Критерии завершения этапов" — заменены: было по одному пункту `verification_checklist` на Task, агрегированному по Milestone (как в `render_deliverables()`, Этап 7.5); стало — одна ADF-таблица `ID`/`Название`/`Описание` по `milestones`/`wbs` верхнего уровня плана (там уже есть `id`/`name`/`description` из `schema/milestones_wbs.yaml`): строка Milestone (жирным), затем строки его WBS, без строк Task.
- `render_epic_description()` (текстовая версия, используется только в dry-run отчёте для консультанта) обновлена аналогично — блок "Описание" + таблица критериев по Milestone/WBS вместо `render_deliverables()`; `render_deliverables()` не удалена — остаётся в `generate_client_document.py` для клиентского документа (Этап 7.5), не участвует в Jira-экспорте.
- `--selftest`: новые проверки читают `description_adf` Epic напрямую — ровно 2 узла `table` (Риски + Критерии), правильные заголовки колонок, строки Критериев = ровно Milestone-ID ∪ WBS-ID без единого Task-ID, ни один текст риска не содержит `|`.
- `schema/milestones_wbs.yaml` и `tasks/M*_tasks.yaml` не менялись; правка только в `jira_export.py`.

## v1.23 — Jira-экспорт: короткое имя Sprint (лимит Jira 30 символов)
- Найдено на реальном создании 6 Sprint в TPT (первая попытка после v1.22): `POST /rest/agile/1.0/sprint` отклонён с `HTTP 400: "Długość nazwy sprintu musi być mniejsza niż 30 zn."` (имя Sprint должно быть короче 30 символов) — полное имя из плана (например, `"Спринт 1 (2026-08-03–2026-08-16)"`, 33 символа) в это не укладывается. Ни один Sprint создан не был (упало на первой же попытке).
- `PlannedSprint`: разделены `name` (короткое, `"Спринт N"` + метка вроде "Гиперподдержка", если есть — все 6 укладываются в лимит) и `goal` (полное имя из плана с датами, без изменений). В Jira `name` идёт короткая форма (обязательное поле API), `goal` — полное имя из плана (необязательное поле, лимитом не ограничено).
- `parse_sprint_dates_and_label()` (переименована из `parse_sprint_dates`) дополнительно извлекает метку (например, "Гиперподдержка") из уже готового имени — не по отдельному полю плана (такого нет), а из той же строки, что и раньше давала даты.
- `create_sprint()` (JiraClient и FakeJiraClient) — новый опциональный параметр `goal`; dry-run отчёт показывает оба значения (`name=... goal=...`) для каждого Sprint.
- `--selftest`: короткое `name` укладывается в лимит для всех 6 спринтов плана (в т.ч. с меткой "Гиперподдержка"), `goal` совпадает с полным именем из плана без изменений, `create_sprint` (FakeJiraClient) сохраняет оба поля.
- Маппинг Epic/Issue/Subtask/Link, timetracking, retry-механизм не менялись — точечный фикс формата имени Sprint.
- `docs/principles.md`, `schema/milestones_wbs.yaml` и `tasks/M*_tasks.yaml` не изменялись.

## v1.22 — Jira-экспорт: timetracking + опциональное создание Sprint (фикс Этапа 8)
- **Time tracking**: `execute_export()` проставляет `timetracking.originalEstimate` (формат `f"{hours}h"`) у Issue/Subtask, если для соответствующей Task в плане есть `effort_estimates[task_id].hours`. WBS-Issue (агрегированной оценки на уровне WBS в плане нет) и custom Task без записи в `effort_estimates` (например, `T-4.5-C1` из Этапа 7.6) timetracking не получают — не выдумывается. Dry-run отчёт показывает `originalEstimate` рядом с каждой Task/Subtask, как уже показываются `labels`/`sprint`.
- **`--create-sprints`** (opt-in, по умолчанию выключен): создаёт Sprint на доске проекта из `sprint_plan.sprints[]` через Agile REST API (`GET /rest/agile/1.0/board`, `POST /rest/agile/1.0/sprint`) — имя спринта берётся из плана без изменений, даты извлекаются из уже готового имени (`assemble_plan.py: sprint_name()`, не пересчитываются заново). Без привязки Issue/Subtask к созданным спринтам — `customfield_...` Sprint не трогается, имя спринта остаётся строкой в description, как и раньше; привязку делает консультант вручную. Dry-run печатает то же самое (GET доски + список спринтов с датами) без единого POST.
- Найдено на реальном dry-run против TPT: поле `type` доски (`GET /rest/agile/1.0/board`) ненадёжно как признак поддержки Sprint — team-managed проект TPT репортит доску как `type: "simple"`, хотя Sprint у неё реально включены (`GET .../board/{id}/sprint` успешен, там уже есть `TPT Sprint 1`). Проверка на `type == "scrum"` некорректно отклонила бы рабочую доску. Исправлено до реального создания: `require_sprint_capable_board()` определяет поддержку Sprint реальным вызовом `board_supports_sprints()` (`GET .../board/{id}/sprint`), а не чтением статичного поля схемы. Если ни одна доска не поддерживает Sprint — не включает функцию самостоятельно, а останавливается явной `BoardUnavailableError` (по аналогии с `SubtaskUnavailableError`).
- `board_supports_sprints()`/`get_board_candidates()`/`create_sprint()` идут через тот же `_request()` с retry на transient-ошибках, что и `create_issue`/`create_issue_link` (Этап 8, v1.21) — новых вызовов вне retry не добавлено.
- `--selftest`: originalEstimate из `effort_estimates` корректно формируется и попадает в fields созданного issue (в т.ч. отсутствие у WBS-Issue и custom Task без оценки); парсинг дат из имени спринта (в т.ч. с меткой "Гиперподдержка"); `require_sprint_capable_board` — находит доску по реальной поддержке Sprint (не по `type`), останавливается при отсутствии досок и при отсутствии доски с Sprint; создание N спринтов через `FakeJiraClient`; `JiraClient.board_supports_sprints` различает HTTP 400 "does not support sprints" (False) от прочих ошибок (не проглатывает их как False).
- Маппинг Epic/Issue/Subtask/Link, `--execute`/`--confirm`/dry-run логика и retry-механизм из v1.21 не менялись — фикс поверх них, не архитектура Этапа 8.
- `docs/principles.md`, `schema/milestones_wbs.yaml` и `tasks/M*_tasks.yaml` не изменялись.

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
