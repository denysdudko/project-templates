#!/usr/bin/env python3
"""Этап 6 — сборка итогового плана внедрения Comarch e-Sklep B2B.

Пайплайн: Charter -> Milestones -> WBS -> Tasks -> Dependencies ->
Оценки (effort-estimates.yaml) -> Sprint-план (schema/sprint_plan.yaml) ->
Риски (risk-register.yaml) -> Deliverables.

Источники (не переопределяются этим файлом, только читаются):
  schema/milestones_wbs.yaml, tasks/M*_tasks.yaml   -- структура и Task
  docs/selection-rules.md                            -- вариативность WBS-6.4
  agent/effort-estimates.yaml                        -- Этап 3
  schema/sprint_plan.yaml                            -- Этап 5 (эталонное
                                                         распределение WBS по
                                                         спринтам -- шаблон,
                                                         не вычисляется)
  agent/risk-register.yaml                           -- Этап 4

`schema/milestones_wbs.yaml`, `tasks/M*_tasks.yaml` и `schema/sprint_plan.yaml`
этим скриптом не изменяются — только читаются.

Запуск:
    python3 assemble_plan.py --input path/to/client-input.json --output plan.json
    python3 assemble_plan.py --input path/to/client-input.json --lang ua
    python3 assemble_plan.py --selftest
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

AGENT_DIR = Path(__file__).resolve().parent
TEMPLATE_ROOT = AGENT_DIR.parent

# ---------------------------------------------------------------------------
# agent/estimation-config.yaml -- team_capacity_per_sprint используется
# только для REMEDIATION_BUFFER_HOURS (Этап 3, ниже). Длительность спринтов
# с Этапа 5 v3 больше не вычисляется от capacity -- она фиксируется вручную
# консультантом в schema/sprint_plan.yaml (duration_weeks на каждый спринт);
# team_capacity_per_sprint и sprint_duration_weeks в estimation-config.yaml
# остаются справочным ориентиром при ручном заполнении этого файла (см.
# agent/sprint-mapping-rules.md).
# ---------------------------------------------------------------------------


def load_estimation_config(path: Path | None = None) -> dict:
    path = path or AGENT_DIR / "estimation-config.yaml"
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


_ESTIMATION_CONFIG = load_estimation_config()
CAPACITY_PER_SPRINT_HOURS = _ESTIMATION_CONFIG["team_capacity_per_sprint"]
REMEDIATION_BUFFER_HOURS = 0.2 * CAPACITY_PER_SPRINT_HOURS  # 16 при значениях по умолчанию

LAUNCH_TASK_ID = "T-9.2.2"  # WBS-9.2, "запуск в эксплуатацию" (fit-check gate)

# Task, для которых keyword-эвристика Этапа 3 не даёт совпадения, но
# правильный тип однозначно следует из description самой Task (а не
# придуман заново). Пример: T-8.1.1 называется "Определить состав
# участников и формат обучения", но его description буквально начинается
# со слова "Согласовать с заказчиком..." — то есть это Tier negotiation,
# просто в Task.name выбран синоним, не входящий в keywords
# effort-estimates.yaml. Это находка при реализации Этапа 6, а не
# самостоятельная переоценка типов — effort-estimates.yaml не менялся.
# Каждая запись обязана быть задокументирована здесь с обоснованием.
MANUAL_TASK_TYPE_OVERRIDES: dict[str, tuple[str, str]] = {
    "T-8.1.1": (
        "negotiation",
        'description начинается с "Согласовать с заказчиком, кто из сотрудников..." '
        '— тот же паттерн: в Task.name использован синоним "Определить" вместо '
        '"Согласовать".',
    ),
    "T-2.1.2": (
        "negotiation",
        'Точечное подтверждение с заказчиком одного набора данных (название компании, '
        'магазина, PIN из письма активации) — по объёму и природе работы то же самое, '
        'что и "Согласовать" (узкий, суженный набор параметров), просто без этого '
        'глагола в названии.',
    ),
    "T-5.5.1": (
        "verification",
        'Запуск синхронизации и проверка результата ("Проверить, что синхронизация '
        'завершилась без сообщений об ошибке") — тот же паттерн, что T-3.3.1 '
        '"Выполнить тестовую синхронизацию" и T-9.2.1 "Выполнить контрольную '
        'синхронизацию" (оба классифицируются как verification по keyword), только '
        'использовано слово "первую" вместо "тестовую"/"контрольную".',
    ),
    "T-6.2.5": (
        "verification",
        'Тот же паттерн "Выполнить синхронизацию + проверить результат", что и '
        'T-5.5.1/T-3.3.1/T-9.2.1.',
    ),
    "T-7.1.2": (
        "synthesis_reporting",
        'Небольшая задача (согласовать состав демо-сценария на основе уже собранных '
        'в T-7.1.1 результатов) — по объёму и характеру работы (сведение уже '
        'существующих решений в документ) ближе к synthesis_reporting (1-3ч), чем к '
        'content_data_preparation (4-16ч, рассчитан на объём каталога товаров).',
    ),
    "T-7.2.2": (
        "synthesis_reporting",
        'Фиксация (агрегация) замечаний заказчика по итогам демонстрации в протокол '
        '— соответствует определению synthesis_reporting ("Агрегация результатов... '
        'в единый документ"), просто в названии использован глагол "Зафиксировать" '
        'вместо "Свести".',
    ),
}

# Известные интеграции -> проверенная (curl, 2026-07-07) официальная статья
# документации Comarch. selection-rules.md запрещает "придумывать" source.url
# для WBS-6.4 — интеграция вне этой карты не разворачивается в Task
# автоматически (см. build_wbs_6_4_tasks: попадает в meta.unresolved_integrations,
# и это ровно сценарий риска R-2 в risk-register.yaml).
KNOWN_INTEGRATION_DOCS: dict[str, str] = {
    "baselinker": "https://pomoc.comarchesklep.pl/artykul/jak-podlaczyc-konto-baselinker-w-comarch-e-sklep/",
    "dhl": "https://pomoc.comarchesklep.pl/artykul/jak-przeprowadzic-integracje-dostawy-z-dhl/",
    "payu": "https://pomoc.comarchesklep.pl/artykul/payu-konfiguracja/",
}

ALLOWED_FEATURES = {"individual_prices", "credit_limits", "multiple_warehouses"}
REQUIRED_INPUT_FIELDS = [
    "project_name",
    "client",
    "erp",
    "users_count",
    "start_date",
    "target_launch_date",
]


# ---------------------------------------------------------------------------
# Загрузка
# ---------------------------------------------------------------------------


def load_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_yaml(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def validate_input(data: dict) -> dict:
    missing = [f for f in REQUIRED_INPUT_FIELDS if f not in data]
    if missing:
        raise ValueError(f"input-schema.json: отсутствуют обязательные поля: {missing}")
    if data["erp"].get("system") != "Comarch ERP Optima":
        raise ValueError(
            "input-schema.json: erp.system вне enum — v1 шаблона покрывает "
            "только 'Comarch ERP Optima'"
        )
    if data["users_count"] < 1:
        raise ValueError("input-schema.json: users_count должен быть >= 1")
    unknown_features = set(data.get("features", [])) - ALLOWED_FEATURES
    if unknown_features:
        raise ValueError(
            f"input-schema.json: features вне enum, не покрыты шаблоном: {unknown_features}"
        )
    start = parse_date(data["start_date"])
    target = parse_date(data["target_launch_date"])
    if target <= start:
        raise ValueError("input-schema.json: target_launch_date должен быть позже start_date")
    return data


LANG_CHOICES = ("ru", "ua")


def load_template(lang: str = "ru") -> tuple[dict, dict[str, dict]]:
    suffix = "" if lang == "ru" else f".{lang}"
    schema = load_yaml(TEMPLATE_ROOT / "schema" / f"milestones_wbs{suffix}.yaml")
    tasks_by_milestone = {}
    for i in range(1, 10):
        mid = f"M{i}"
        tasks_by_milestone[mid] = load_yaml(TEMPLATE_ROOT / "tasks" / f"{mid}_tasks{suffix}.yaml")
    return schema, tasks_by_milestone


def load_sprint_plan_template(path: Path | None = None) -> dict:
    path = path or TEMPLATE_ROOT / "schema" / "sprint_plan.yaml"
    return load_yaml(path)


# ---------------------------------------------------------------------------
# Charter
# ---------------------------------------------------------------------------


def build_charter(input_data: dict, template_schema: dict) -> dict:
    project = template_schema["project"]
    start = parse_date(input_data["start_date"])
    target = parse_date(input_data["target_launch_date"])
    requested_weeks = (target - start).days / 7
    return {
        "project_name": input_data["project_name"],
        "client": input_data["client"],
        "product": project.get("product"),
        "description": (project.get("description") or "").strip(),
        "objective": (project.get("objective") or "").strip(),
        "erp": input_data["erp"],
        "users_count": input_data["users_count"],
        "integrations": input_data.get("integrations", []),
        "features": input_data.get("features", []),
        "start_date": input_data["start_date"],
        "target_launch_date": input_data["target_launch_date"],
        "target_launch_date_definition": (
            "target_launch_date -- дата запуска магазина в эксплуатацию (WBS-9.2, "
            f"{LAUNCH_TASK_ID}), не дата закрытия всего проекта. Формальное "
            "завершение проекта (WBS-9.4) продолжается после этой даты. "
            'Гиперподдержка ведётся отдельным Epic "Поддержка" в Jira '
            "(создаётся всегда при экспорте, Этап 8) и не входит в этот план -- "
            "WBS/Task, sprint-планирование и оценки трудозатрат её не описывают."
        ),
        "requested_duration_weeks": round(requested_weeks, 1),
        "template_default_duration_weeks": project.get("default_duration_weeks"),
    }


# ---------------------------------------------------------------------------
# Milestones / WBS / Tasks (+ вариативность WBS-6.4 из selection-rules.md)
# ---------------------------------------------------------------------------


def lookup_integration_doc(name: str) -> str | None:
    return KNOWN_INTEGRATION_DOCS.get(name.strip().lower())


# Task для WBS-6.4 генерируются динамически (по каждой integration из input),
# а не читаются из tasks/M6_tasks{.lang}.yaml -- поэтому их текст не покрыт
# переводом контента и локализуется здесь отдельно по lang (см. --lang в
# CHANGELOG v3.6).
INTEGRATION_TASK_TEXT: dict[str, dict[str, str]] = {
    "ru": {
        "name": "Настроить интеграцию {name} согласно документации Comarch",
        "result": "Настроенная и активная интеграция {name}",
        "verification": "Проверить, что интеграция {name} активна и работает согласно её документации.",
    },
    "ua": {
        "name": "Налаштувати інтеграцію {name} згідно з документацією Comarch",
        "result": "Налаштована та активна інтеграція {name}",
        "verification": "Перевірити, що інтеграція {name} активна і працює згідно з її документацією.",
    },
}


def build_wbs_6_4_tasks(
    base_tasks: list[dict], integrations: list[str], lang: str = "ru"
) -> tuple[list[dict], list[str]]:
    """selection-rules.md, раздел "Правило для WBS-6.4"."""
    if not integrations:
        return [dict(t) for t in base_tasks], []

    texts = INTEGRATION_TASK_TEXT[lang]
    t_6_4_1 = next(dict(t) for t in base_tasks if t["id"] == "T-6.4.1")
    result = [t_6_4_1]
    unresolved: list[str] = []
    for idx, name in enumerate(integrations, start=1):
        doc_url = lookup_integration_doc(name)
        if doc_url is None:
            unresolved.append(name)
            continue
        result.append(
            {
                "id": f"T-6.4.2.{idx}",
                "name": texts["name"].format(name=name),
                "performer": "Консультант",
                "depends_on": ["T-6.4.1"],
                "source": {"type": "Official Comarch Documentation", "url": doc_url},
                "result": [texts["result"].format(name=name)],
                "used_by": ["WBS-6.5"],
                "interview_checklist": [],
                "verification_checklist": [texts["verification"].format(name=name)],
                "generated_from": "T-6.4.2",
            }
        )
    return result, unresolved


def build_milestones(
    template_schema: dict, tasks_by_milestone: dict[str, dict], integrations: list[str], lang: str = "ru"
) -> tuple[list[dict], list[str]]:
    milestones = []
    unresolved_integrations: list[str] = []
    for m in template_schema["milestones"]:
        mid = m["id"]
        tasks_doc = tasks_by_milestone[mid]
        tasks_by_wbs = {block["wbs"]: block["tasks"] for block in tasks_doc["tasks"]}
        wbs_out = []
        for wbs_def in m["wbs"]:
            wbs_id = wbs_def["id"]
            tasks = tasks_by_wbs.get(wbs_id, [])
            if wbs_id == "WBS-6.4":
                tasks, unresolved = build_wbs_6_4_tasks(tasks, integrations, lang=lang)
                unresolved_integrations.extend(unresolved)
            else:
                tasks = [dict(t) for t in tasks]
            wbs_out.append(
                {
                    "id": wbs_id,
                    "name": wbs_def["name"],
                    "description": (wbs_def.get("description") or "").strip(),
                    "tasks": tasks,
                }
            )
        milestones.append(
            {
                "id": mid,
                "name": m["name"],
                "description": (m.get("description") or "").strip(),
                "wbs": wbs_out,
            }
        )
    patch_stale_slot_dependencies(milestones)
    return milestones, unresolved_integrations


def flatten_tasks(milestones: list[dict]) -> list[dict]:
    return [t for m in milestones for wbs in m["wbs"] for t in wbs["tasks"]]


def patch_stale_slot_dependencies(milestones: list[dict]) -> None:
    """Когда WBS-6.4 разворачивается в T-6.4.2.1..N (integrations непуст),
    T-6.4.2 как id перестаёт существовать. Другие Task, у которых
    depends_on ИЛИ used_by ссылался на T-6.4.2 (в шаблоне -- T-6.5.1.depends_on
    и T-6.4.1.used_by, симметрично друг другу), должны ссылаться на все
    сгенерированные child-Task, иначе ссылка молча выпадает из графа
    (валидатор просто не найдёт несуществующий id)."""
    all_tasks = flatten_tasks(milestones)
    ids = {t["id"] for t in all_tasks}
    if "T-6.4.2" in ids:
        return  # WBS-6.4 не разворачивалась (integrations пуст) -- патчить нечего
    generated_ids = sorted(tid for tid in ids if tid.startswith("T-6.4.2."))
    if not generated_ids:
        return
    for t in all_tasks:
        for field_name in ("depends_on", "used_by"):
            values = t.get(field_name) or []
            if "T-6.4.2" in values:
                t[field_name] = [v for v in values if v != "T-6.4.2"] + generated_ids


# ---------------------------------------------------------------------------
# Dependencies -- из шаблона, без изменений (used_by не используется как
# источник порядка, см. sprint-mapping-rules.md)
# ---------------------------------------------------------------------------


def build_dependencies(all_tasks: list[dict]) -> dict[str, list[str]]:
    return {t["id"]: list(t.get("depends_on") or []) for t in all_tasks}


# ---------------------------------------------------------------------------
# Оценки трудозатрат (effort-estimates.yaml, Этап 3)
# ---------------------------------------------------------------------------


def classify_task(task: dict, task_types: list[dict]) -> str | None:
    name = task["name"]
    candidates = []
    for tt in task_types:
        for kw in tt["keywords"]:
            # "Глагол в начале Task.name" (effort-estimates.yaml) обычно
            # означает startswith, но иногда перед глаголом стоит наречие
            # ("Формально закрыть проект") -- проверяем вхождение в первые
            # три слова, а не жёсткий префикс.
            prefix = " ".join(name.split()[:3]).lower()
            if kw.lower() in prefix:
                candidates.append((len(kw), tt["id"]))
    if not candidates:
        override = MANUAL_TASK_TYPE_OVERRIDES.get(task["id"])
        return override[0] if override else None
    candidates.sort(reverse=True)
    top_len = candidates[0][0]
    top_matches = {c[1] for c in candidates if c[0] == top_len}
    if len(top_matches) > 1:
        raise ValueError(
            f"{task['id']}: неоднозначная классификация по keyword-эвристике "
            f"(кандидаты одинаковой длины: {sorted(top_matches)}) -- нужен "
            f"fallback по чек-листам/WBS-контексту (effort-estimates.yaml, "
            f"task_type_matching_rule), который в этом скрипте не покрыт "
            f"автоматически."
        )
    return candidates[0][1]


def effort_for_task(task_type_id: str, task_types_by_id: dict[str, dict]) -> dict:
    tt = task_types_by_id[task_type_id]
    base = tt.get("base_estimate_hours")

    if task_type_id == "remediation":
        return {
            "task_type": task_type_id,
            "hours": REMEDIATION_BUFFER_HOURS,
            "basis": "remediation_buffer_hours (константа v1, sprint-mapping-rules.md)",
        }
    if base is None:
        raise ValueError(f"Тип {task_type_id}: base_estimate_hours отсутствует и не является особым случаем")
    midpoint = (base["min"] + base["max"]) / 2
    return {
        "task_type": task_type_id,
        "hours": midpoint,
        "basis": f"середина диапазона base_estimate_hours [{base['min']}, {base['max']}] для типа {task_type_id}",
    }


def build_effort_estimates(
    all_tasks: list[dict], effort_ref: dict, ru_name_by_id: dict[str, str] | None = None
) -> dict[str, dict]:
    """ru_name_by_id -- classify_task() сопоставляет keywords effort-estimates.yaml
    (русские глаголы) с текстом Task.name; при lang != "ru" сам отображаемый
    Task.name уже переведён и с этой эвристикой не совпадёт. Тип Task -- свойство
    Task ID (методология), не текста на конкретном языке, поэтому классификация
    всегда идёт по RU-названию, а часы применяются к Task выбранного языка (см.
    assemble_plan(), CHANGELOG v3.6)."""
    task_types = effort_ref["task_types"]
    task_types_by_id = {t["id"]: t for t in task_types}
    estimates = {}
    for t in all_tasks:
        classify_source = t if ru_name_by_id is None else {"id": t["id"], "name": ru_name_by_id.get(t["id"], t["name"])}
        type_id = classify_task(classify_source, task_types)
        if type_id is None:
            raise ValueError(
                f"{t['id']} ({classify_source['name']!r}): keyword-эвристика effort-estimates.yaml "
                f"не дала совпадения и нет override в MANUAL_TASK_TYPE_OVERRIDES -- "
                f"Task не может быть распределена без ручной классификации."
            )
        estimates[t["id"]] = effort_for_task(type_id, task_types_by_id)
    return estimates


# ---------------------------------------------------------------------------
# Sprint-план (agent/sprint-mapping-rules.md, Этап 5)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Sprint-план (schema/sprint_plan.yaml, Этап 5 -- шаблон, не алгоритм).
# Скрипт только читает готовое расписание: какой WBS в каком спринте и какой
# длительности -- решает консультант в schema/sprint_plan.yaml, не вычисляет
# assemble_plan.py. Единица -- WBS целиком: все Task одного WBS наследуют его
# спринт, WBS не режется между спринтами.
# ---------------------------------------------------------------------------


def wbs_task_ids_by_wbs(milestones: list[dict]) -> dict[str, list[str]]:
    """wbs_id -> [task_id, ...] в порядке шаблона (Milestone -> WBS -> Task)."""
    return {wbs["id"]: [t["id"] for t in wbs["tasks"]] for m in milestones for wbs in m["wbs"]}


def wbs_sprint_number_by_wbs(sprint_template: dict, known_wbs_ids: set[str]) -> dict[str, int]:
    """Читает schema/sprint_plan.yaml -> {wbs_id: sprint_number}, проверяя,
    что каждый реальный WBS плана покрыт РОВНО одним спринтом -- не
    пропущен, не задублирован. Ошибка -- явный ValueError, не молчаливый
    пропуск WBS."""
    wbs_sprint: dict[str, int] = {}
    for entry in sprint_template["sprints"]:
        for wbs_id in entry["wbs"]:
            if wbs_id in wbs_sprint:
                raise ValueError(
                    f"schema/sprint_plan.yaml: WBS {wbs_id!r} указан больше чем в одном "
                    f"спринте (спринт {wbs_sprint[wbs_id]} и спринт {entry['number']})"
                )
            wbs_sprint[wbs_id] = entry["number"]

    missing = sorted(known_wbs_ids - set(wbs_sprint))
    if missing:
        raise ValueError(f"schema/sprint_plan.yaml: WBS без назначенного спринта: {missing}")
    unknown = sorted(set(wbs_sprint) - known_wbs_ids)
    if unknown:
        raise ValueError(
            f"schema/sprint_plan.yaml: WBS ID отсутствуют в schema/milestones_wbs.yaml: {unknown}"
        )
    return wbs_sprint


def sprint_name(sprint_number: int, start: date, end: date) -> str:
    return f"Спринт {sprint_number} ({start.isoformat()}–{end.isoformat()})"


def build_sprint_plan(
    milestones: list[dict],
    effort: dict[str, dict],
    start_date: date,
    target_launch_date: date,
    sprint_template: dict,
) -> dict:
    wbs_tasks = wbs_task_ids_by_wbs(milestones)
    wbs_sprint = wbs_sprint_number_by_wbs(sprint_template, set(wbs_tasks))

    task_sprint: dict[str, int] = {}
    task_ids_by_sprint: dict[int, list[str]] = {}
    for wbs_id, tids in wbs_tasks.items():
        n = wbs_sprint[wbs_id]
        task_ids_by_sprint.setdefault(n, [])
        for tid in tids:
            task_sprint[tid] = n
            task_ids_by_sprint[n].append(tid)

    if LAUNCH_TASK_ID not in task_sprint:
        raise ValueError(f"{LAUNCH_TASK_ID} (запуск, WBS-9.2) не распределён -- проверь schema/sprint_plan.yaml")
    launch_sprint = task_sprint[LAUNCH_TASK_ID]

    # Даты -- последовательно накопительно: первый спринт стартует в
    # start_date, каждый следующий -- сразу после конца предыдущего.
    # Длительность -- duration_weeks из schema/sprint_plan.yaml (ручное
    # решение консультанта), не производная от трудоёмкости.
    cursor = start_date
    sprints_out: list[dict] = []
    for entry in sorted(sprint_template["sprints"], key=lambda e: e["number"]):
        n = entry["number"]
        weeks = entry["duration_weeks"]
        tids = task_ids_by_sprint.get(n, [])
        hours = sum(effort[tid].get("hours", 0.0) for tid in tids)
        sprint_start = cursor
        sprint_end = sprint_start + timedelta(weeks=weeks) - timedelta(days=1)
        sprints_out.append(
            {
                "sprint": n,
                "task_ids": tids,
                "hours_used": hours,
                "start_date": sprint_start.isoformat(),
                "end_date": sprint_end.isoformat(),
                "duration_weeks": weeks,
                "name": sprint_name(n, sprint_start, sprint_end),
            }
        )
        cursor = sprint_end + timedelta(days=1)

    # R-7: сравниваются фактические недели до запуска (сумма duration_weeks
    # спринтов вплоть до спринта WBS-9.2 включительно) против доступных
    # календарных недель start_date -> target_launch_date -- количество
    # спринтов само по себе не показатель при переменной длине.
    weeks_used_until_launch = sum(s["duration_weeks"] for s in sprints_out if s["sprint"] <= launch_sprint)
    available_weeks = round((target_launch_date - start_date).days / 7, 1)
    fits = weeks_used_until_launch <= available_weeks

    return {
        "sprints": sprints_out,
        "task_sprint": task_sprint,
        "launch_task_id": LAUNCH_TASK_ID,
        "total_sprints_used": launch_sprint,
        "weeks_used_until_launch": weeks_used_until_launch,
        "available_weeks": available_weeks,
        "fits_in_target_launch_date": fits,
        "warning": None
        if fits
        else (
            f"Расчётный план требует {weeks_used_until_launch} нед. до запуска "
            f"({LAUNCH_TASK_ID}, {launch_sprint} спринт(ов)), доступно {available_weeks} "
            f"нед. между start_date и target_launch_date -- дефицит "
            f"{round(weeks_used_until_launch - available_weeks, 1)} нед. Решение (сдвиг "
            f"target_launch_date / пересмотр schema/sprint_plan.yaml) -- за "
            f"консультантом/PM, не за агентом."
        ),
        "post_launch_note": (
            "WBS-9.4 (Завершение проекта) запланирован после launch_sprint и не "
            "входит в fits_in_target_launch_date -- это ожидаемое продолжение "
            "работ после запуска, не дефицит времени. Гиперподдержка ведётся "
            'отдельным Epic "Поддержка" вне этого плана (см. '
            "charter.target_launch_date_definition)."
        ),
    }


# ---------------------------------------------------------------------------
# Риски (agent/risk-register.yaml, Этап 4)
# ---------------------------------------------------------------------------


def evaluate_condition(risk_id: str, condition_text: str, ctx: dict) -> bool:
    if risk_id == "R-1":
        return not ctx["erp"].get("version")
    if risk_id == "R-7":
        sr = ctx["sprint_result"]
        return not sr["fits_in_target_launch_date"]
    # R-2..R-6: условие -- буквальное Python-булево выражение над
    # integrations/features/users_count/erp (см. risk-register.yaml,
    # condition_language). eval() в ограниченном пространстве имён --
    # осознанное решение (YAML этого файла контролируется тем же
    # репозиторием, не внешним вводом), а не обход валидации.
    safe_globals = {"__builtins__": {}}
    safe_locals = {
        "integrations": ctx["integrations"],
        "features": ctx["features"],
        "users_count": ctx["users_count"],
        "erp": ctx["erp"],
        "len": len,
    }
    try:
        return bool(eval(condition_text.strip(), safe_globals, safe_locals))
    except Exception as exc:  # noqa: BLE001 -- нужно явное сообщение с id риска
        raise ValueError(f"Не удалось вычислить condition риска {risk_id} ({condition_text!r}): {exc}") from exc


def evaluate_risks(risk_register: dict, ctx: dict) -> list[dict]:
    applicable = []
    for r in risk_register["risks"]:
        if evaluate_condition(r["id"], r["condition"], ctx):
            applicable.append(r)
    return applicable


# ---------------------------------------------------------------------------
# Deliverables -- агрегация verification_checklist, без новых формулировок
# ---------------------------------------------------------------------------


def build_deliverables(milestones: list[dict]) -> list[dict]:
    deliverables = []
    for m in milestones:
        items = []
        for wbs in m["wbs"]:
            for t in wbs["tasks"]:
                for check in t.get("verification_checklist") or []:
                    items.append({"task_id": t["id"], "wbs_id": wbs["id"], "check": check})
        deliverables.append({"milestone_id": m["id"], "milestone_name": m["name"], "verification_checklist": items})
    return deliverables


# ---------------------------------------------------------------------------
# LLM-слой (последний шаг) -- контракт, не реализация конкретного вызова
# ---------------------------------------------------------------------------

# Поля, которые LLM разрешено переписывать (только текст, не структуру).
LLM_EDITABLE_TASK_FIELDS = {"description", "interview_checklist", "verification_checklist"}
LLM_EDITABLE_CHARTER_FIELDS = {"description", "objective"}


def _structure_fingerprint(plan: dict) -> tuple:
    """Всё, что LLM НЕ имеет права менять: id/depends_on/used_by/состав."""
    ids = []
    for m in plan["milestones"]:
        for wbs in m["wbs"]:
            for t in wbs["tasks"]:
                ids.append((t["id"], tuple(t.get("depends_on") or []), tuple(t.get("used_by") or [])))
    milestone_ids = tuple(m["id"] for m in plan["milestones"])
    wbs_ids = tuple(wbs["id"] for m in plan["milestones"] for wbs in m["wbs"])
    return (milestone_ids, wbs_ids, tuple(sorted(ids)))


def adapt_wording_with_llm(plan: dict, input_data: dict, llm_client=None) -> tuple[dict, dict]:
    """Этап 6, последний шаг сборки.

    Контракт: LLM адаптирует под клиента только формулировки -- Charter
    (description/objective), Task.description, тексты
    interview_checklist/verification_checklist. LLM не создаёт, не удаляет
    и не переупорядочивает Milestone/WBS/Task, не трогает id/depends_on/
    used_by/source.url. Это не реализация конкретного вызова к LLM (в
    этом репозитории нет подключённого API) -- это enforced-контракт:
    если llm_client передан и меняет структуру, adapt_wording_with_llm
    отклоняет результат явной ошибкой, а не молча принимает его.
    """
    if llm_client is None:
        return plan, {"llm_step": "skipped", "reason": "llm_client не передан -- passthrough без изменений"}

    before = _structure_fingerprint(plan)
    adapted = llm_client.adapt(plan, input_data, editable_task_fields=LLM_EDITABLE_TASK_FIELDS, editable_charter_fields=LLM_EDITABLE_CHARTER_FIELDS)
    after = _structure_fingerprint(adapted)
    if before != after:
        raise ValueError(
            "LLM-адаптация изменила структуру плана (id/depends_on/used_by/состав "
            "Milestone/WBS/Task) -- отклонено по контракту Этапа 6."
        )
    return adapted, {"llm_step": "applied"}


# ---------------------------------------------------------------------------
# Оркестрация
# ---------------------------------------------------------------------------


def assemble_plan(input_data: dict, llm_client=None, lang: str = "ru") -> dict:
    if lang not in LANG_CHOICES:
        raise ValueError(f"lang должен быть одним из {LANG_CHOICES}, получено {lang!r}")
    input_data = validate_input(input_data)
    template_schema, tasks_by_milestone = load_template(lang=lang)
    effort_ref = load_yaml(AGENT_DIR / "effort-estimates.yaml")
    risk_register = load_yaml(AGENT_DIR / "risk-register.yaml")

    charter = build_charter(input_data, template_schema)
    milestones, unresolved_integrations = build_milestones(
        template_schema, tasks_by_milestone, input_data.get("integrations", []), lang=lang
    )
    all_tasks = flatten_tasks(milestones)
    dependencies = build_dependencies(all_tasks)

    ru_name_by_id = None
    if lang != "ru":
        ru_schema, ru_tasks_by_milestone = load_template(lang="ru")
        ru_milestones, _ = build_milestones(
            ru_schema, ru_tasks_by_milestone, input_data.get("integrations", []), lang="ru"
        )
        ru_name_by_id = {t["id"]: t["name"] for t in flatten_tasks(ru_milestones)}

    effort = build_effort_estimates(all_tasks, effort_ref, ru_name_by_id=ru_name_by_id)
    sprint_template = load_sprint_plan_template()

    sprint_result = build_sprint_plan(
        milestones,
        effort,
        parse_date(input_data["start_date"]),
        parse_date(input_data["target_launch_date"]),
        sprint_template,
    )

    risk_ctx = {
        "erp": input_data["erp"],
        "integrations": input_data.get("integrations", []),
        "features": input_data.get("features", []),
        "users_count": input_data["users_count"],
        "sprint_result": sprint_result,
    }
    risks = evaluate_risks(risk_register, risk_ctx)

    deliverables = build_deliverables(milestones)

    plan = {
        "charter": charter,
        "milestones": milestones,
        "dependencies": dependencies,
        "effort_estimates": effort,
        "sprint_plan": sprint_result,
        "risks": risks,
        "deliverables": deliverables,
        "meta": {
            "template_id": template_schema["template"]["id"],
            "template_version": template_schema["template"]["version"],
            "unresolved_integrations": unresolved_integrations,
            "lang": lang,
        },
    }

    plan, llm_meta = adapt_wording_with_llm(plan, input_data, llm_client=llm_client)
    plan["meta"]["llm_adaptation"] = llm_meta
    return plan


# ---------------------------------------------------------------------------
# Self-test -- сверка эвристики классификации против реального шаблона
# ---------------------------------------------------------------------------


def run_selftest() -> None:
    template_schema, tasks_by_milestone = load_template()
    effort_ref = load_yaml(AGENT_DIR / "effort-estimates.yaml")
    task_types = effort_ref["task_types"]
    task_types_by_id = {t["id"]: t for t in task_types}

    milestones, _ = build_milestones(template_schema, tasks_by_milestone, integrations=[])
    all_tasks = flatten_tasks(milestones)
    print(f"[selftest] Task в шаблоне (без вариативности WBS-6.4): {len(all_tasks)}")

    failures = []
    classified: dict[str, str] = {}
    for t in all_tasks:
        try:
            type_id = classify_task(t, task_types)
        except ValueError as exc:
            failures.append(f"{t['id']}: {exc}")
            continue
        if type_id is None:
            failures.append(f"{t['id']} ({t['name']!r}): нет совпадения по keyword и нет override")
            continue
        classified[t["id"]] = type_id

    mismatches = []
    for tt in task_types:
        for example_id in tt.get("examples", []):
            got = classified.get(example_id)
            if got != tt["id"]:
                mismatches.append(f"{example_id}: effort-estimates.yaml объявляет {tt['id']!r}, классификатор дал {got!r}")

    if failures:
        print(f"[selftest] НЕ КЛАССИФИЦИРОВАНО: {len(failures)}")
        for f in failures:
            print("  -", f)
    else:
        print("[selftest] Все Task шаблона классифицированы по типу -- OK")

    if mismatches:
        print(f"[selftest] Расхождения с examples в effort-estimates.yaml: {len(mismatches)}")
        for m in mismatches:
            print("  -", m)
    else:
        print("[selftest] Классификация совпадает с examples в effort-estimates.yaml -- OK")

    # Прогон варианта WBS-6.4 с интеграциями + неизвестной интеграцией.
    milestones_with, unresolved = build_milestones(
        template_schema, tasks_by_milestone, integrations=["Baselinker", "DHL", "PayU", "НеизвестнаяСистема"]
    )
    m6 = next(m for m in milestones_with if m["id"] == "M6")
    wbs64 = next(w for w in m6["wbs"] if w["id"] == "WBS-6.4")
    generated_ids = [t["id"] for t in wbs64["tasks"] if t["id"] != "T-6.4.1"]
    print(f"[selftest] WBS-6.4 c 4 интеграциями (1 неизвестная): сгенерировано Task = {generated_ids}")
    print(f"[selftest] unresolved_integrations = {unresolved}")
    assert generated_ids == ["T-6.4.2.1", "T-6.4.2.2", "T-6.4.2.3"], generated_ids
    assert unresolved == ["НеизвестнаяСистема"], unresolved
    print("[selftest] WBS-6.4 вариативность (integrations пуст/непуст/неизвестная интеграция) -- OK")

    # Регрессия: T-6.5.1.depends_on и T-6.4.1.used_by в шаблоне ссылаются на
    # T-6.4.2 -- при развороте WBS-6.4 обе ссылки должны переехать на все
    # сгенерированные T-6.4.2.x, а не молча выпасть из графа (см.
    # patch_stale_slot_dependencies).
    all_tasks_with = flatten_tasks(milestones_with)
    t651 = next(t for t in all_tasks_with if t["id"] == "T-6.5.1")
    assert "T-6.4.2" not in t651["depends_on"], t651["depends_on"]
    assert set(generated_ids) <= set(t651["depends_on"]), t651["depends_on"]
    print(f"[selftest] T-6.5.1.depends_on после разворота WBS-6.4 = {t651['depends_on']} -- OK")

    t641 = next(t for t in all_tasks_with if t["id"] == "T-6.4.1")
    assert "T-6.4.2" not in t641["used_by"], t641["used_by"]
    assert set(generated_ids) <= set(t641["used_by"]), t641["used_by"]
    print(f"[selftest] T-6.4.1.used_by после разворота WBS-6.4 = {t641['used_by']} -- OK")

    milestones_empty, unresolved_empty = build_milestones(template_schema, tasks_by_milestone, integrations=[])
    m6e = next(m for m in milestones_empty if m["id"] == "M6")
    wbs64e = next(w for w in m6e["wbs"] if w["id"] == "WBS-6.4")
    assert [t["id"] for t in wbs64e["tasks"]] == ["T-6.4.1", "T-6.4.2"], wbs64e["tasks"]
    assert unresolved_empty == []
    print("[selftest] WBS-6.4 при пустых integrations остаётся T-6.4.1/T-6.4.2 -- OK")

    # Прогон с заведомо тесным сроком -- должна сработать ветка
    # "не укладывается в срок" (fits=False, warning заполнен, R-7 в risks).
    tight_input = {
        "project_name": "Selftest: tight deadline",
        "client": "Selftest sp. z o.o.",
        "erp": {"system": "Comarch ERP Optima"},
        "users_count": 5,
        "integrations": [],
        "features": [],
        "start_date": "2026-08-03",
        "target_launch_date": "2026-08-17",  # 2 недели = 1 спринт
    }
    tight_plan = assemble_plan(dict(tight_input))
    tsp = tight_plan["sprint_plan"]
    assert tsp["fits_in_target_launch_date"] is False, tsp
    assert tsp["warning"], "warning должен быть заполнен при дефиците спринтов"
    risk_ids = {r["id"] for r in tight_plan["risks"]}
    assert "R-7" in risk_ids, risk_ids
    print(
        f"[selftest] Тесный срок: weeks_used_until_launch={tsp['weeks_used_until_launch']}, "
        f"available_weeks={tsp['available_weeks']}, R-7 в risks -- OK"
    )

    # Именование спринтов -- "Спринт {N} (start–end)", даты вычисляются
    # последовательно накопительно от start_date проекта.
    import re as _re

    sprint_name_re = _re.compile(r"^Спринт \d+ \(\d{4}-\d{2}-\d{2}–\d{4}-\d{2}-\d{2}\)$")
    assert tsp["sprints"], "в tight_plan нет ни одного спринта -- ветка не проверена"
    for s in tsp["sprints"]:
        assert sprint_name_re.match(s["name"]), f"неожиданный формат имени спринта: {s['name']!r}"
    first = tsp["sprints"][0]
    assert first["start_date"] == tight_input["start_date"], first
    assert first["name"] == f"Спринт 1 ({first['start_date']}–{first['end_date']})", first["name"]
    print(f"[selftest] Именование спринтов: {first['name']!r} -- OK")

    # --- Чтение schema/sprint_plan.yaml (Этап 5 -- шаблон, не алгоритм). ---

    def _flat_effort(hours_by_task: dict[str, float]) -> dict[str, dict]:
        return {tid: {"task_type": "synthetic", "hours": h, "basis": "selftest"} for tid, h in hours_by_task.items()}

    real_sprint_template = load_sprint_plan_template()
    real_wbs_ids = {wbs["id"] for m in milestones_empty for wbs in m["wbs"]}
    real_wbs_sprint = wbs_sprint_number_by_wbs(real_sprint_template, real_wbs_ids)
    assert set(real_wbs_sprint) == real_wbs_ids, set(real_wbs_sprint) ^ real_wbs_ids
    print(
        f"[selftest] schema/sprint_plan.yaml: все {len(real_wbs_ids)} WBS шаблона покрыты "
        "ровно одним спринтом (не пропущены, не задублированы) -- OK"
    )

    ok_template = {"sprints": [{"number": 1, "duration_weeks": 2, "wbs": ["WBS-1.1", "WBS-1.2"]}]}
    assert wbs_sprint_number_by_wbs(ok_template, {"WBS-1.1", "WBS-1.2"}) == {"WBS-1.1": 1, "WBS-1.2": 1}
    print("[selftest] wbs_sprint_number_by_wbs: полное покрытие без пропусков/дублей -- OK")

    missing_template = {"sprints": [{"number": 1, "duration_weeks": 2, "wbs": ["WBS-1.1"]}]}
    try:
        wbs_sprint_number_by_wbs(missing_template, {"WBS-1.1", "WBS-1.2"})
    except ValueError as exc:
        assert "WBS-1.2" in str(exc), exc
        print("[selftest] schema/sprint_plan.yaml: пропущенный WBS -- явная ошибка, не молчаливый пропуск -- OK")
    else:
        raise AssertionError("пропущенный в шаблоне WBS должен поднимать ValueError")

    duplicate_template = {
        "sprints": [
            {"number": 1, "duration_weeks": 2, "wbs": ["WBS-1.1"]},
            {"number": 2, "duration_weeks": 2, "wbs": ["WBS-1.1", "WBS-1.2"]},
        ]
    }
    try:
        wbs_sprint_number_by_wbs(duplicate_template, {"WBS-1.1", "WBS-1.2"})
    except ValueError as exc:
        assert "WBS-1.1" in str(exc), exc
        print("[selftest] schema/sprint_plan.yaml: задублированный WBS -- явная ошибка, не тихая перезапись -- OK")
    else:
        raise AssertionError("WBS, указанный в двух спринтах, должен поднимать ValueError")

    # build_sprint_plan целиком на синтетическом шаблоне -- Task наследуют
    # спринт своего WBS, WBS не режется между спринтами, даты -- сразу после
    # конца предыдущего спринта.
    def _synthetic_milestone(wbs_ids: list[str]) -> list[dict]:
        def task_id_for(wbs_id: str) -> str:
            return LAUNCH_TASK_ID if wbs_id == "WBS-9.2" else f"{wbs_id}-T1"

        return [
            {
                "id": "M1",
                "name": "M1 (synthetic)",
                "description": "",
                "wbs": [
                    {
                        "id": wbs_id,
                        "name": wbs_id,
                        "description": "",
                        "tasks": [
                            {"id": task_id_for(wbs_id), "name": task_id_for(wbs_id), "depends_on": [], "used_by": []}
                        ],
                    }
                    for wbs_id in wbs_ids
                ],
            }
        ]

    synthetic_milestones = _synthetic_milestone(["WBS-1.1", "WBS-1.2", "WBS-9.2"])
    synthetic_effort = _flat_effort({"WBS-1.1-T1": 10.0, "WBS-1.2-T1": 20.0, LAUNCH_TASK_ID: 1.0})
    synthetic_template = {
        "sprints": [
            {"number": 1, "duration_weeks": 2, "wbs": ["WBS-1.1"]},
            {"number": 2, "duration_weeks": 1, "wbs": ["WBS-1.2", "WBS-9.2"]},
        ]
    }
    synthetic_plan = build_sprint_plan(
        synthetic_milestones, synthetic_effort, date(2026, 1, 1), date(2026, 6, 1), synthetic_template
    )
    assert synthetic_plan["task_sprint"] == {"WBS-1.1-T1": 1, "WBS-1.2-T1": 2, LAUNCH_TASK_ID: 2}, (
        synthetic_plan["task_sprint"]
    )
    assert synthetic_plan["sprints"][0]["start_date"] == "2026-01-01", synthetic_plan["sprints"][0]
    assert synthetic_plan["sprints"][0]["end_date"] == "2026-01-14", synthetic_plan["sprints"][0]
    assert synthetic_plan["sprints"][1]["start_date"] == "2026-01-15", synthetic_plan["sprints"][1]
    assert synthetic_plan["total_sprints_used"] == 2, synthetic_plan["total_sprints_used"]
    print(
        "[selftest] build_sprint_plan: Task наследуют спринт своего WBS из schema/sprint_plan.yaml, "
        "даты -- последовательно накопительно -- OK"
    )

    # Контракт LLM-слоя: если llm_client меняет структуру -- adapt_wording_with_llm
    # обязан отклонить результат, а не молча принять.
    class _StructureBreakingLLM:
        def adapt(self, plan, input_data, **kwargs):
            broken = json.loads(json.dumps(plan))
            broken["milestones"][0]["wbs"][0]["tasks"].pop()  # удалили Task -- нарушение контракта
            return broken

    try:
        adapt_wording_with_llm(tight_plan, tight_input, llm_client=_StructureBreakingLLM())
    except ValueError:
        print("[selftest] LLM-контракт: изменение структуры отклонено -- OK")
    else:
        failures.append("adapt_wording_with_llm не отклонил LLM-клиента, сломавшего структуру плана")

    # --- --lang ua (CHANGELOG v3.6) ---------------------------------------
    # 1) lang="ru" (по умолчанию) должен остаться байт-в-байт таким же, как
    #    до появления --lang -- ru_name_by_id не должен подмешиваться, когда
    #    lang == "ru".
    # 2) lang="ua" не должен падать на build_effort_estimates (это и есть
    #    находка, которая привела к этой правке -- keyword-эвристика
    #    effort-estimates.yaml рассчитана на русские глаголы и не совпадёт
    #    с украинским текстом Task.name без классификации по RU-названию).
    # 3) ID Milestone/WBS/Task между lang="ru" и lang="ua" должны совпадать
    #    1:1 (перевод -- контента, не структуры).
    ua_input = dict(tight_input)
    ua_input["integrations"] = ["Baselinker", "DHL"]
    ru_plan_for_lang_check = assemble_plan(dict(ua_input), lang="ru")
    ua_plan = assemble_plan(dict(ua_input), lang="ua")

    assert ua_plan["meta"]["lang"] == "ua", ua_plan["meta"]
    assert ru_plan_for_lang_check["meta"]["lang"] == "ru", ru_plan_for_lang_check["meta"]

    def _all_ids(plan: dict) -> tuple[list[str], list[str], list[str]]:
        m_ids = [m["id"] for m in plan["milestones"]]
        wbs_ids = [wbs["id"] for m in plan["milestones"] for wbs in m["wbs"]]
        t_ids = sorted(t["id"] for t in flatten_tasks(plan["milestones"]))
        return m_ids, wbs_ids, t_ids

    ru_m_ids, ru_wbs_ids, ru_t_ids = _all_ids(ru_plan_for_lang_check)
    ua_m_ids, ua_wbs_ids, ua_t_ids = _all_ids(ua_plan)
    assert ru_m_ids == ua_m_ids, (ru_m_ids, ua_m_ids)
    assert ru_wbs_ids == ua_wbs_ids, (ru_wbs_ids, ua_wbs_ids)
    assert ru_t_ids == ua_t_ids, set(ru_t_ids) ^ set(ua_t_ids)
    print(f"[selftest] --lang ua: {len(ua_t_ids)} Task ID совпадают 1:1 с --lang ru (integrations: {ua_input['integrations']}) -- OK")

    assert set(ua_plan["effort_estimates"]) == set(ua_t_ids), (
        "--lang ua: build_effort_estimates должен покрыть все Task, включая динамически "
        "сгенерированные WBS-6.4 (integrations), без ValueError по keyword-эвристике"
    )
    assert ua_plan["effort_estimates"] == ru_plan_for_lang_check["effort_estimates"], (
        "--lang ua: классификация типа Task и часы -- методологическое свойство Task ID, "
        "не текста -- должны совпадать с --lang ru при одинаковом input"
    )
    print("[selftest] --lang ua: effort_estimates (тип и часы) идентичны --lang ru для всех Task, включая WBS-6.4 -- OK")

    ua_task_names = {t["id"]: t["name"] for t in flatten_tasks(ua_plan["milestones"])}
    ru_task_names = {t["id"]: t["name"] for t in flatten_tasks(ru_plan_for_lang_check["milestones"])}
    assert ua_task_names != ru_task_names, "--lang ua: тексты Task.name не должны совпадать с --lang ru (перевод не применился?)"
    assert ua_task_names["T-6.4.2.1"] != ru_task_names["T-6.4.2.1"], (
        "--lang ua: динамически сгенерированный Task для интеграции (WBS-6.4) должен быть локализован, не взят из RU"
    )
    print("[selftest] --lang ua: тексты Task.name (включая динамические WBS-6.4) отличаются от --lang ru -- OK")

    if failures or mismatches:
        sys.exit(1)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Путь к заполненному input-schema.json клиента")
    parser.add_argument("--output", type=Path, help="Куда записать итоговый план (по умолчанию -- stdout)")
    parser.add_argument("--format", choices=["json", "yaml"], default="json")
    parser.add_argument(
        "--lang",
        choices=list(LANG_CHOICES),
        default="ru",
        help="Язык контента шаблона (Milestones/WBS/Task) -- ru (по умолчанию) или ua",
    )
    parser.add_argument("--selftest", action="store_true", help="Прогнать самопроверку классификации без клиентского input")
    args = parser.parse_args()

    if args.selftest:
        run_selftest()
        return

    if not args.input:
        parser.error("--input обязателен (или используйте --selftest)")

    input_data = load_json(args.input)
    plan = assemble_plan(input_data, lang=args.lang)

    if args.format == "json":
        text = json.dumps(plan, ensure_ascii=False, indent=2, default=str)
    else:
        text = yaml.safe_dump(plan, allow_unicode=True, sort_keys=False)

    if args.output:
        args.output.write_text(text, encoding="utf-8")
        print(f"Записано: {args.output}", file=sys.stderr)
    else:
        print(text)


if __name__ == "__main__":
    main()
