# Changelog

## v1.1 — Этап 0: исправление ошибок
- Исправлена ошибка отступов YAML в `schema/milestones_wbs.yaml` (`project.description`/`project.objective`), файл не парсился.
- Убраны пустые узлы `tasks:`, `dependencies:`, `risks:` из `schema/milestones_wbs.yaml` (контент живёт в `tasks/M*_tasks.yaml`).
- Обновлена устаревшая ссылка на документацию Comarch ERP Optima в `tasks/M9_tasks.yaml` (T-9.1.2, T-9.2.1): архивная версия `2024_5` → актуальная `2026`.
- Добавлен `docs/principles.md` с зафиксированными правилами WBS/Task, чек-листов и иерархией источников.

## v1.0
- Базовый шаблон: Milestones M1–M9, WBS, задачи по M1–M9 с checklist'ами и ссылками на документацию Comarch.
