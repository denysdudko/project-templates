#!/usr/bin/env python3
"""Этап 7.6 — приём правок заказчика и слияние с базовым планом.

Берёт уже собранный (Этап 6, `assemble_plan.py`) план и CSV-таблицу правок
(Этап 7.5, `generate_client_document.py --corrections-output`, после того
как её отредактировал консультант/заказчик) и сливает их в один план по
Task ID. Результат слияния — то, что идёт на вход Этапу 8 (Jira-экспорт),
а не исходный JSON Этапа 6.

Правила слияния (по Task ID):
  - Include = no, ИЛИ Task ID базового плана вообще отсутствует в таблице
    правок (строка удалена) -> Task исключается из плана.
  - Include = yes (или пусто — значение по умолчанию) -> Task остаётся;
    непустые Название/Спринт из таблицы применяются к ней.
  - Строка без Task ID -> добавляется как новая custom Task. Обязателен
    существующий WBS ID (нельзя ввести новый WBS/Milestone через таблицу
    правок — это отдельное решение, не для Этапа 7.6). Source такой Task —
    "Internal Project Methodology" с added_by: "client_approval_process".
    effort_estimates для неё сознательно не выставляется (в таблице правок
    нет данных для оценки трудозатрат) — её отсутствие всплывёт находкой
    cross_section при повторном прогоне валидатора, а не будет придумано.

Важно: при исключении Task её ID точечно вычищается из dependencies /
effort_estimates / sprint_plan.task_sprint / deliverables (это чисто
производные от milestones разделы). Но depends_on/used_by ОСТАЮЩИХСЯ Task,
ссылающиеся на исключённый ID, НЕ переписываются автоматически — если
исключение разорвало граф зависимостей, это обязано явно всплыть в отчёте
validate_plan.py (Этап 7, check_integrity), а не потеряться молча.

Не трогает schema/milestones_wbs.yaml и tasks/M*_tasks.yaml.

Запуск:
    python3 merge-corrections.py --plan plan.json --corrections corrections.csv \
        --output merged-plan.json
    python3 merge-corrections.py --selftest
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from validate_plan import flatten_tasks, format_report, validate_plan

AGENT_DIR = Path(__file__).resolve().parent

ADDED_BY_CLIENT_APPROVAL = "client_approval_process"
CORRECTIONS_FIELDS = ["Task ID", "WBS ID", "Milestone ID", "Название", "Спринт", "Include", "Comment"]


# ---------------------------------------------------------------------------
# Чтение таблицы правок
# ---------------------------------------------------------------------------


def read_corrections(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in CORRECTIONS_FIELDS if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"В таблице правок отсутствуют обязательные колонки: {missing}")
        return [row for row in reader if any((v or "").strip() for v in row.values())]


# ---------------------------------------------------------------------------
# Слияние
# ---------------------------------------------------------------------------


def _index_plan(plan: dict) -> tuple[dict[str, dict], dict[str, dict], dict[str, str]]:
    """task_id -> Task dict; wbs_id -> WBS dict; wbs_id -> Milestone ID."""
    tasks_by_id: dict[str, dict] = {}
    wbs_by_id: dict[str, dict] = {}
    milestone_of_wbs: dict[str, str] = {}
    for m in plan.get("milestones", []):
        for wbs in m.get("wbs", []):
            wbs_by_id[wbs["id"]] = wbs
            milestone_of_wbs[wbs["id"]] = m["id"]
            for t in wbs.get("tasks", []):
                tasks_by_id[t["id"]] = t
    return tasks_by_id, wbs_by_id, milestone_of_wbs


def _new_custom_task_id(wbs_id: str, existing_ids: set[str]) -> str:
    base = f"T-{wbs_id.removeprefix('WBS-')}-C"
    n = 1
    candidate = f"{base}{n}"
    while candidate in existing_ids:
        n += 1
        candidate = f"{base}{n}"
    return candidate


def merge_corrections(plan: dict, corrections: list[dict]) -> tuple[dict, list[str]]:
    """Возвращает (смерженный план, список сообщений о ходе слияния).

    Не мутирует переданный plan -- работает на глубокой копии."""
    plan = json.loads(json.dumps(plan))
    notes: list[str] = []

    tasks_by_id, wbs_by_id, milestone_of_wbs = _index_plan(plan)
    original_task_ids = set(tasks_by_id.keys())

    rows_by_task_id: dict[str, dict] = {}
    new_rows: list[dict] = []
    for row in corrections:
        task_id = (row.get("Task ID") or "").strip()
        if not task_id:
            new_rows.append(row)
            continue
        if task_id in rows_by_task_id:
            notes.append(f"{task_id}: встречается в таблице правок более одного раза -- использована последняя строка")
        rows_by_task_id[task_id] = row

    for task_id, row in rows_by_task_id.items():
        if task_id not in original_task_ids:
            notes.append(f"{task_id}: Task ID из таблицы правок не найден в базовом плане -- строка проигнорирована")

    # 1. Существующие Task -- включение/исключение + правки Название/Спринт.
    excluded_ids: set[str] = set()
    task_sprint = plan.setdefault("sprint_plan", {}).setdefault("task_sprint", {})
    for task_id in original_task_ids:
        row = rows_by_task_id.get(task_id)
        if row is None:
            excluded_ids.add(task_id)
            notes.append(f"{task_id}: строка отсутствует в таблице правок -- Task исключена из плана")
            continue

        include = (row.get("Include") or "yes").strip().lower()
        if include not in ("yes", "no", ""):
            notes.append(f"{task_id}: неизвестное значение Include={row.get('Include')!r} -- трактовано как yes")
        if include == "no":
            excluded_ids.add(task_id)
            continue

        task = tasks_by_id[task_id]
        new_name = (row.get("Название") or "").strip()
        if new_name and new_name != task["name"]:
            notes.append(f"{task_id}: название изменено на {new_name!r}")
            task["name"] = new_name

        new_sprint_raw = (row.get("Спринт") or "").strip()
        if new_sprint_raw:
            try:
                new_sprint = int(new_sprint_raw)
            except ValueError:
                notes.append(f"{task_id}: значение Спринт={new_sprint_raw!r} не число -- проигнорировано")
            else:
                if task_sprint.get(task_id) != new_sprint:
                    notes.append(f"{task_id}: спринт изменён на {new_sprint}")
                    task_sprint[task_id] = new_sprint

    # 2. Удаление исключённых Task из всех производных разделов плана.
    if excluded_ids:
        for m in plan["milestones"]:
            for wbs in m["wbs"]:
                wbs["tasks"] = [t for t in wbs["tasks"] if t["id"] not in excluded_ids]
        for tid in excluded_ids:
            plan.get("dependencies", {}).pop(tid, None)
            plan.get("effort_estimates", {}).pop(tid, None)
            task_sprint.pop(tid, None)
        for d in plan.get("deliverables", []):
            d["verification_checklist"] = [
                item for item in (d.get("verification_checklist") or []) if item["task_id"] not in excluded_ids
            ]
        notes.append(
            f"Исключено Task: {len(excluded_ids)} ({', '.join(sorted(excluded_ids))}) -- "
            "depends_on/used_by оставшихся Task намеренно не переписаны, разрывы (если есть) "
            "покажет повторный прогон validate_plan.py"
        )

    # 3. Новые custom-задачи -- обязателен существующий WBS ID.
    all_ids_in_use = set(tasks_by_id.keys()) - excluded_ids
    for row in new_rows:
        wbs_id = (row.get("WBS ID") or "").strip()
        name = (row.get("Название") or "").strip()
        if not wbs_id:
            notes.append(f"Новая строка без Task ID и без WBS ID -- пропущена: {row!r}")
            continue
        if wbs_id not in wbs_by_id:
            notes.append(
                f"Новая задача {name!r}: WBS ID {wbs_id!r} не существует в плане -- строка пропущена "
                "(новый WBS через таблицу правок не поддерживается, это отдельное решение)"
            )
            continue
        if not name:
            notes.append(f"Новая задача в {wbs_id}: пустое Название -- строка пропущена")
            continue

        milestone_id_given = (row.get("Milestone ID") or "").strip()
        actual_milestone_id = milestone_of_wbs[wbs_id]
        if milestone_id_given and milestone_id_given != actual_milestone_id:
            notes.append(
                f"Новая задача {name!r}: указанный Milestone ID={milestone_id_given!r} не совпадает с "
                f"фактическим милстоуном {wbs_id} ({actual_milestone_id}) -- использован фактический"
            )

        new_id = _new_custom_task_id(wbs_id, all_ids_in_use)
        all_ids_in_use.add(new_id)

        new_task = {
            "id": new_id,
            "name": name,
            "performer": "Консультант",
            "source": {"type": "Internal Project Methodology"},
            "added_by": ADDED_BY_CLIENT_APPROVAL,
            "depends_on": [],
            "used_by": [],
            "interview_checklist": [],
            "verification_checklist": [],
        }
        wbs_by_id[wbs_id]["tasks"].append(new_task)
        plan.setdefault("dependencies", {})[new_id] = []

        sprint_raw = (row.get("Спринт") or "").strip()
        if sprint_raw:
            try:
                task_sprint[new_id] = int(sprint_raw)
            except ValueError:
                notes.append(f"{new_id}: значение Спринт={sprint_raw!r} не число -- не выставлено")
        else:
            notes.append(f"{new_id}: Спринт не указан в таблице правок -- потребует ручного назначения")

        notes.append(
            f"{new_id}: добавлена как custom Task в {wbs_id} ({actual_milestone_id}) -- "
            "effort_estimates для неё не выставлен (таблица правок не содержит оценки трудозатрат), "
            "это ожидаемо всплывёт находкой cross_section в отчёте валидатора"
        )

    return plan, notes


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------


def _load_client_abc_plan() -> dict:
    path = AGENT_DIR / "examples" / "client-abc.plan.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _rows_from_plan(plan: dict) -> list[dict]:
    """Тот же построчный формат, что и generate_client_document.py
    --corrections-output -- Include=yes для всех Task по умолчанию."""
    task_sprint = plan.get("sprint_plan", {}).get("task_sprint", {})
    rows = []
    for m in plan.get("milestones", []):
        for wbs in m.get("wbs", []):
            for t in wbs.get("tasks", []):
                rows.append(
                    {
                        "Task ID": t["id"],
                        "WBS ID": wbs["id"],
                        "Milestone ID": m["id"],
                        "Название": t["name"],
                        "Спринт": str(task_sprint.get(t["id"], "")),
                        "Include": "yes",
                        "Comment": "",
                    }
                )
    return rows


def run_selftest() -> None:
    plan = _load_client_abc_plan()
    base_report = validate_plan(plan)
    assert not base_report.findings, "regression: базовый client-abc.plan.json должен быть чист"
    print("[selftest] базовый client-abc.plan.json чист по validate_plan.py -- OK")

    # --- 1. Пустая/неизменённая таблица правок -- план не должен меняться. ---
    rows = _rows_from_plan(plan)
    merged, notes = merge_corrections(plan, rows)
    assert flatten_tasks(merged) == flatten_tasks(plan), "неизменённая таблица правок не должна менять план"
    assert not any("исключен" in n.lower() or "добавлена" in n.lower() for n in notes)
    print("[selftest] таблица правок без изменений -- план идентичен базовому -- OK")

    # --- 2. Include=no исключает Task. ---
    rows2 = _rows_from_plan(plan)
    target = next(r for r in rows2 if r["Task ID"] == "T-8.3.1")  # без зависимых Task
    target["Include"] = "no"
    merged2, notes2 = merge_corrections(plan, rows2)
    merged_ids2 = {t["id"] for t in flatten_tasks(merged2)}
    assert "T-8.3.1" not in merged_ids2
    assert "T-8.3.1" not in merged2["dependencies"]
    assert "T-8.3.1" not in merged2["effort_estimates"]
    assert "T-8.3.1" not in merged2["sprint_plan"]["task_sprint"]
    r2 = validate_plan(merged2)
    assert not r2.findings, f"исключение независимой Task не должно порождать находок: {r2.findings}"
    print("[selftest] Include=no исключает Task из milestones/dependencies/effort_estimates/sprint_plan -- OK")

    # --- 3. Отсутствующая строка = исключение (то же самое, что Include=no). ---
    rows3 = [r for r in _rows_from_plan(plan) if r["Task ID"] != "T-8.3.1"]
    merged3, notes3 = merge_corrections(plan, rows3)
    assert "T-8.3.1" not in {t["id"] for t in flatten_tasks(merged3)}
    print("[selftest] отсутствующая в таблице строка -- Task исключена так же, как Include=no -- OK")

    # --- 4. Исключение Task, от которой зависят другие -- разрыв должен
    #        всплыть в validate_plan.py (integrity), а не потеряться молча. ---
    rows4 = _rows_from_plan(plan)
    target4 = next(r for r in rows4 if r["Task ID"] == "T-1.1.1")  # T-1.1.2 depends_on T-1.1.1
    target4["Include"] = "no"
    merged4, notes4 = merge_corrections(plan, rows4)
    assert "T-1.1.1" not in {t["id"] for t in flatten_tasks(merged4)}
    r4 = validate_plan(merged4)
    hits4 = [f for f in r4.findings if f.check == "integrity" and "T-1.1.1" in f.message]
    assert hits4, "исключение Task, от которой зависит T-1.1.2, должно дать находку integrity"
    print("[selftest] исключение Task с зависимыми -- разрыв виден в отчёте валидатора (не потерян молча) -- OK")

    # --- 5. Изменение Спринт/Название применяется к Task. ---
    rows5 = _rows_from_plan(plan)
    target5 = next(r for r in rows5 if r["Task ID"] == "T-1.2.1")
    target5["Название"] = "Провести интервью по функциональным требованиям (уточнённая формулировка)"
    target5["Спринт"] = "2"
    merged5, notes5 = merge_corrections(plan, rows5)
    t5 = next(t for t in flatten_tasks(merged5) if t["id"] == "T-1.2.1")
    assert t5["name"] == "Провести интервью по функциональным требованиям (уточнённая формулировка)"
    assert merged5["sprint_plan"]["task_sprint"]["T-1.2.1"] == 2
    print("[selftest] правки Название/Спринт применены к существующей Task -- OK")

    # --- 6. Новая custom Task с указанием существующего WBS ID. ---
    rows6 = _rows_from_plan(plan)
    rows6.append(
        {
            "Task ID": "",
            "WBS ID": "WBS-6.4",
            "Milestone ID": "M6",
            "Название": "Подключить дополнительный тестовый профиль интеграции по запросу заказчика",
            "Спринт": "2",
            "Include": "yes",
            "Comment": "Добавлено по итогам согласования (Этап 7.6)",
        }
    )
    merged6, notes6 = merge_corrections(plan, rows6)
    new_tasks6 = [t for t in flatten_tasks(merged6) if t.get("added_by") == ADDED_BY_CLIENT_APPROVAL]
    assert len(new_tasks6) == 1, new_tasks6
    new_task6 = new_tasks6[0]
    assert new_task6["source"] == {"type": "Internal Project Methodology"}
    assert new_task6["id"] not in plan["dependencies"], "ID новой Task не должен пересекаться с базовым планом"
    assert merged6["dependencies"][new_task6["id"]] == []
    assert merged6["sprint_plan"]["task_sprint"][new_task6["id"]] == 2
    assert new_task6["id"] not in merged6["effort_estimates"], (
        "effort_estimates для custom Task намеренно не выставляется -- должно быть находкой валидатора"
    )
    wbs64 = next(
        wbs for m in merged6["milestones"] if m["id"] == "M6" for wbs in m["wbs"] if wbs["id"] == "WBS-6.4"
    )
    assert new_task6["id"] in [t["id"] for t in wbs64["tasks"]]
    r6 = validate_plan(merged6)
    hits6 = [f for f in r6.findings if f.check == "cross_section" and new_task6["id"] in f.message]
    assert hits6, "отсутствие effort_estimates у custom Task должно дать находку cross_section"
    print(f"[selftest] новая custom Task {new_task6['id']!r} добавлена в WBS-6.4, отсутствие effort_estimates видно валидатору -- OK")

    # --- 7. Новая задача с несуществующим WBS ID -- отклоняется, не создаёт новый WBS. ---
    rows7 = _rows_from_plan(plan)
    rows7.append(
        {
            "Task ID": "",
            "WBS ID": "WBS-99.9",
            "Milestone ID": "",
            "Название": "Что-то за пределами шаблона",
            "Спринт": "",
            "Include": "yes",
            "Comment": "",
        }
    )
    merged7, notes7 = merge_corrections(plan, rows7)
    assert len(flatten_tasks(merged7)) == len(flatten_tasks(plan)), "несуществующий WBS ID не должен добавлять Task"
    assert any("WBS-99.9" in n and "не существует" in n for n in notes7)
    print("[selftest] новая Task с несуществующим WBS ID отклонена (не создаёт новый WBS) -- OK")

    print("[selftest] Все проверки слияния сработали корректно -- OK")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plan", type=Path, help="Путь к базовому плану (JSON), собранному assemble_plan.py")
    parser.add_argument("--corrections", type=Path, help="Путь к отредактированной CSV-таблице правок")
    parser.add_argument("--output", type=Path, help="Куда записать смерженный план (JSON)")
    parser.add_argument(
        "--report", type=Path, help="Куда записать отчёт валидатора по смерженному плану (по умолчанию -- stdout)"
    )
    parser.add_argument("--selftest", action="store_true", help="Прогнать самопроверку на client-abc.plan.json")
    args = parser.parse_args()

    if args.selftest:
        run_selftest()
        return

    if not args.plan or not args.corrections:
        parser.error("--plan и --corrections обязательны (или используйте --selftest)")

    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    corrections = read_corrections(args.corrections)

    merged, notes = merge_corrections(plan, corrections)
    report = validate_plan(merged)

    report_lines = ["Журнал слияния:", ""]
    if notes:
        report_lines.extend(f"  - {n}" for n in notes)
    else:
        report_lines.append("  (изменений нет)")
    report_lines.append("")
    report_lines.append("Повторная валидация смерженного плана (Этап 7):")
    report_lines.append("")
    report_lines.append(format_report(report, merged))
    report_text = "\n".join(report_lines)

    if args.output:
        args.output.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Записано: {args.output}", file=sys.stderr)

    if args.report:
        args.report.write_text(report_text, encoding="utf-8")
        print(f"Записано: {args.report}", file=sys.stderr)
    else:
        print(report_text)


if __name__ == "__main__":
    main()
