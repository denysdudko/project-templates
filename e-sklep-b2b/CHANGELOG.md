# Changelog

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
