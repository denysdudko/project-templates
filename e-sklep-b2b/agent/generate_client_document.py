#!/usr/bin/env python3
"""Этап 7.5 — документ для согласования с заказчиком.

Берёт уже собранный (Этап 6, `assemble_plan.py`) и провалидированный
(Этап 7, `validate_plan.py`) план и рендерит его в человекочитаемый
Markdown-документ для согласования сроков/объёма с заказчиком. Это
отдельный шаг перед экспортом в Jira (Этап 8) — не заменяет и не
предвосхищает его: здесь нет маппинга на Epic/Issue/Label, только
презентация уже готового плана для утверждения человеком.

Не включается в документ (техническая кухня, не предмет согласования):
  - interview_checklist -- внутренний инструмент сбора требований;
  - source.url / effort-эстимейт `basis` / `generated_from` -- внутренние
    поля построения плана, не относятся к согласованию сроков/объёма;
  - id/condition риска -- в документ идёт только `risk` (уже деловой текст)
    и WBS, к которым он относится, по названию, а не по коду;
  - названия конкретных интеграций (T-6.4.2.1..N, WBS-6.4) -- список
    интеграций формально фиксируется на интервью (T-1.3.1/T-1.3.2), а не
    на момент согласования плана; в таблице, критериях завершения и
    зависимостях они схлопываются в один обобщённый плейсхолдер
    (`INTEGRATION_PLACEHOLDER`). Это правка только рендеринга -- в самом
    JSON-плане (Этап 6) T-6.4.2.1..N остаются как есть, они нужны для
    Jira-экспорта (Этап 8).

Второй артефакт (Этап 7.5, расширение) -- CSV-таблица правок
(`--corrections-output`): построчно по каждой реальной Task плана (Task ID,
WBS ID, Milestone ID, Название, Спринт, Include, Comment), Include=yes по
умолчанию, Comment пустой. Это техническая рабочая таблица для
консультанта/заказчика, не заменяет markdown-документ -- в ней используются
настоящие Task ID (включая T-6.4.2.1..N по отдельности, без схлопывания в
плейсхолдер), т.к. именно по Task ID её принимает обратно `merge-corrections.py`
(Этап 7.6).

Запуск:
    python3 generate_client_document.py --plan path/to/plan.json --output doc.md
    python3 generate_client_document.py --plan path/to/plan.json --output doc.md \
        --corrections-output corrections.csv
    python3 generate_client_document.py --selftest
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

from validate_plan import flatten_tasks, validate_plan

AGENT_DIR = Path(__file__).resolve().parent

# `risk` в risk-register.yaml написан для консультанта и местами содержит
# технические скобочные уточнения (WBS-ID, Task-ID, имена полей схемы,
# пути к файлам) -- они всегда синтаксически необязательны (в скобках),
# поэтому их можно безопасно убрать целиком, не ломая грамматику
# предложения. Инлайновый (не в скобках) технический жаргон внутри
# предложения НЕ трогаем -- механическое вырезание слов из середины
# фразы регулярным выражением ломает грамматику чаще, чем помогает;
# полноценная адаптация формулировок под клиента -- за LLM-слоем
# (Этап 6), не за этим детерминированным скриптом.
_PAREN_JARGON = re.compile(
    r"\s*\([^()]*(?:\bWBS-\d|\bT-\d+\.\d|\bM\d\b|agent/|\.md\b|\.yaml\b|\.json\b|"
    r"source\.url|condition|input-schema)[^()]*\)"
)


def clean_business_text(text: str) -> str:
    text = _PAREN_JARGON.sub("", text)
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"\s+([,.;:)])", r"\1", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Именованные интеграции (WBS-6.4, T-6.4.2.1..N) -- список интеграций
# формально определяется на интервью (T-1.3.1/T-1.3.2), а не является
# зафиксированным фактом на момент согласования плана, даже если уже
# известен агенту из intake-данных отбора шаблона (Этап 2). В документе
# согласования конкретные названия сервисов (Baselinker/DHL/PayU/...) не
# показываются -- сворачиваются в один обобщённый плейсхолдер. Это правка
# только рендеринга Этапа 7.5: T-6.4.2.1/.2/.3 в самом JSON-плане (Этап 6,
# нужны для Jira-экспорта, Этап 8) не трогаются.
INTEGRATION_PLACEHOLDER = "Настроить интеграцию [Компонент] согласно документации Comarch"


def integration_task_ids(plan: dict) -> set[str]:
    return {t["id"] for t in flatten_tasks(plan) if t.get("generated_from") == "T-6.4.2"}


# ---------------------------------------------------------------------------
# Вспомогательное
# ---------------------------------------------------------------------------


def build_id_to_name(plan: dict, collapse_ids: set[str] | None = None) -> dict[str, str]:
    collapse_ids = collapse_ids or set()
    names: dict[str, str] = {}
    for m in plan.get("milestones", []):
        names[m["id"]] = m["name"]
        for wbs in m.get("wbs", []):
            names[wbs["id"]] = wbs["name"]
            for t in wbs.get("tasks", []):
                names[t["id"]] = INTEGRATION_PLACEHOLDER if t["id"] in collapse_ids else t["name"]
    return names


def human_refs(ids: list[str], names: dict[str, str]) -> str:
    if not ids:
        return "—"
    seen: list[str] = []
    for i in ids:
        label = names.get(i, i)
        if label not in seen:  # схлопнуть несколько интеграций в один плейсхолдер
            seen.append(label)
    return ", ".join(seen)


def aggregate_sprints(ids: list[str], task_sprint: dict) -> str:
    sprints = sorted({task_sprint[i] for i in ids if i in task_sprint})
    if not sprints:
        return "—"
    if len(sprints) == 1:
        return str(sprints[0])
    return f"{sprints[0]}–{sprints[-1]}"


# ---------------------------------------------------------------------------
# CSV-таблица правок -- отдельный артефакт, не часть markdown-документа
# ---------------------------------------------------------------------------

CORRECTIONS_FIELDS = ["Task ID", "WBS ID", "Milestone ID", "Название", "Спринт", "Include", "Comment"]


def build_corrections_rows(plan: dict) -> list[dict]:
    """Одна строка на каждую реальную Task плана (настоящие Task ID, без
    схлопывания именованных интеграций -- таблица правок нужна для
    точечного включения/исключения/переименования конкретных Task и должна
    сливаться обратно по Task ID, merge-corrections.py, Этап 7.6)."""
    task_sprint = plan.get("sprint_plan", {}).get("task_sprint", {})
    rows: list[dict] = []
    for m in plan.get("milestones", []):
        for wbs in m.get("wbs", []):
            for t in wbs.get("tasks", []):
                rows.append(
                    {
                        "Task ID": t["id"],
                        "WBS ID": wbs["id"],
                        "Milestone ID": m["id"],
                        "Название": t["name"],
                        "Спринт": task_sprint.get(t["id"], ""),
                        "Include": "yes",
                        "Comment": "",
                    }
                )
    return rows


def render_corrections_csv(plan: dict) -> str:
    import io

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CORRECTIONS_FIELDS)
    writer.writeheader()
    for row in build_corrections_rows(plan):
        writer.writerow(row)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Разделы документа
# ---------------------------------------------------------------------------


def render_header(plan: dict) -> str:
    c = plan["charter"]
    lines = [
        f"# {c['project_name']} — план внедрения на согласование",
        "",
        f"**Заказчик:** {c['client']}",
        f"**Цель проекта:** {c['objective']}",
        f"**Дата начала:** {c['start_date']}",
        f"**Дата запуска в эксплуатацию:** {c['target_launch_date']}",
        "",
        "> Дата запуска — это дата ввода магазина в промышленную эксплуатацию, "
        "не дата завершения проекта. После запуска проект продолжается "
        "периодом гиперподдержки и формальным закрытием — это учтено в "
        "итоговой сводке ниже, но не входит в срок до запуска.",
        "",
        "*Документ сгенерирован из собранного и провалидированного плана "
        "для согласования объёма и сроков с заказчиком — промежуточный шаг "
        "перед экспортом в Jira, не заменяет и не предвосхищает его.*",
        "",
    ]
    return "\n".join(lines)


def render_plan_table(plan: dict, id_to_name: dict[str, str], integration_ids: set[str]) -> str:
    task_sprint = plan.get("sprint_plan", {}).get("task_sprint", {})
    lines = ["## План по этапам", ""]
    for m in plan.get("milestones", []):
        lines.append(f"### {m['id']} — {m['name']}")
        lines.append("")
        for wbs in m.get("wbs", []):
            lines.append(f"#### {wbs['id']} — {wbs['name']}")
            lines.append("")
            lines.append("| Задача | Спринт | Зависит от |")
            lines.append("|---|---|---|")
            wbs_integration_tasks = [t for t in wbs.get("tasks", []) if t["id"] in integration_ids]
            placeholder_emitted = False
            for t in wbs.get("tasks", []):
                if t["id"] in integration_ids:
                    if placeholder_emitted:
                        continue  # уже одна строка-плейсхолдер на всю WBS
                    ids = [x["id"] for x in wbs_integration_tasks]
                    sprint = aggregate_sprints(ids, task_sprint)
                    # depends_on у всех сгенерированных интеграций одинаковый
                    # (T-6.4.1) -- берём из первой, схлопывать нечего.
                    deps = human_refs(wbs_integration_tasks[0].get("depends_on") or [], id_to_name)
                    lines.append(f"| {INTEGRATION_PLACEHOLDER} | {sprint} | {deps} |")
                    placeholder_emitted = True
                    continue
                sprint = task_sprint.get(t["id"], "—")
                deps = human_refs(t.get("depends_on") or [], id_to_name)
                lines.append(f"| {t['name']} | {sprint} | {deps} |")
            lines.append("")
    return "\n".join(lines)


INTEGRATION_DELIVERABLE_PLACEHOLDER = (
    "Проверить, что согласованные интеграции активны и работают согласно их документации."
)


def render_deliverables(plan: dict, integration_ids: set[str]) -> str:
    lines = ["## Критерии завершения этапов", ""]
    for d in plan.get("deliverables", []):
        lines.append(f"### {d['milestone_id']} — {d['milestone_name']}")
        lines.append("")
        checks = d.get("verification_checklist") or []
        if not checks:
            lines.append("_Нет отдельных критериев на уровне этапа._")
        else:
            placeholder_emitted = False
            for item in checks:
                # Второе условие -- критерий не сгенерированной интеграции,
                # но ссылается на слот T-6.4.2 голым кодом в тексте (шаблонная
                # формулировка T-6.5.1) -- та же техническая утечка, что и
                # именованные интеграции, схлопываем в тот же плейсхолдер.
                if item["task_id"] in integration_ids or "T-6.4.2" in item["check"]:
                    if placeholder_emitted:
                        continue  # по одному критерию на интеграцию -- схлопываем
                    lines.append(f"- {INTEGRATION_DELIVERABLE_PLACEHOLDER}")
                    placeholder_emitted = True
                    continue
                lines.append(f"- {item['check']}")
        lines.append("")
    return "\n".join(lines)


def render_risks(plan: dict, id_to_name: dict[str, str]) -> str:
    lines = ["## Риски проекта", ""]
    risks = plan.get("risks") or []
    if not risks:
        lines.append(
            "Для параметров этого проекта применимых рисков из реестра не выявлено."
        )
        lines.append("")
        return "\n".join(lines)

    lines.append("| Риск | Затрагивает |")
    lines.append("|---|---|")
    for r in risks:
        risk_text = clean_business_text(" ".join((r.get("risk") or "").split()))
        affects = human_refs(r.get("related_wbs") or [], id_to_name)
        lines.append(f"| {risk_text} | {affects} |")
    lines.append("")
    return "\n".join(lines)


def render_summary(plan: dict) -> str:
    sp = plan.get("sprint_plan", {})
    total_sprints_used = sp.get("total_sprints_used")
    available_sprints = sp.get("available_sprints")
    sprint_weeks = sp.get("sprint_length_weeks")
    all_sprints = len(sp.get("sprints") or [])
    duration_weeks = (total_sprints_used or 0) * (sprint_weeks or 0)

    lines = ["## Итоговая сводка", ""]
    lines.append(f"- Спринтов до запуска: {total_sprints_used} из {available_sprints} доступных")
    lines.append(f"- Длительность до запуска: {duration_weeks} нед. (спринт = {sprint_weeks} нед.)")
    lines.append(
        f"- Всего спринтов в плане, включая гиперподдержку и завершение проекта после запуска: {all_sprints}"
    )
    warning = sp.get("warning")
    if warning:
        lines.append("")
        lines.append(f"> ⚠️ **{warning}**")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Оркестрация
# ---------------------------------------------------------------------------


def render_client_document(plan: dict) -> str:
    integration_ids = integration_task_ids(plan)
    id_to_name = build_id_to_name(plan, collapse_ids=integration_ids)
    parts = [
        render_header(plan),
        render_plan_table(plan, id_to_name, integration_ids),
        render_deliverables(plan, integration_ids),
        render_risks(plan, id_to_name),
        render_summary(plan),
    ]
    return "\n".join(parts).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------


def _load_client_abc_plan() -> dict:
    path = AGENT_DIR / "examples" / "client-abc.plan.json"
    return json.loads(path.read_text(encoding="utf-8"))


def run_selftest() -> None:
    plan = _load_client_abc_plan()

    report = validate_plan(plan)
    if report.findings:
        print(f"[selftest] ПРЕДУПРЕЖДЕНИЕ: {len(report.findings)} находок(и) валидатора на входном плане")

    doc = render_client_document(plan)
    print(f"[selftest] документ сгенерирован, {len(doc.splitlines())} строк")

    # Технические поля не должны просочиться в клиентский документ.
    # Структурная утечка -- сырое поле/ключ/объект плана попал в документ
    # как есть (не про отдельные жаргонные слова внутри прозы risk-текста,
    # это за пределами возможностей детерминированного скрипта без LLM).
    forbidden = [
        "interview_checklist",
        "\"url\":",
        "\"basis\":",
        "generated_from",
        "MANUAL_TASK_TYPE_OVERRIDES",
    ]
    leaked = [f for f in forbidden if f in doc]
    assert not leaked, f"технические поля просочились в документ: {leaked}"
    print("[selftest] структурные технические поля (interview_checklist/basis/url-key/...) отсутствуют -- OK")

    # Скобочный технический жаргон в risk-текстах безопасно вырезан.
    assert "WBS-2.1)" not in doc and "(WBS-2.1)" not in doc
    assert "(M8)" not in doc
    print("[selftest] скобочные технические уточнения в risk-текстах вырезаны -- OK")

    # Каждая обычная Task шаблона должна попасть в план по этапам по названию
    # (кроме именованных интеграций -- у них отдельная проверка ниже).
    all_tasks = flatten_tasks(plan)
    int_ids = integration_task_ids(plan)
    assert int_ids, "в тестовом плане нет ни одной сгенерированной интеграции -- ветка не проверена"
    for t in all_tasks:
        if t["id"] in int_ids:
            continue
        assert t["name"] in doc, f"{t['id']} ({t['name']!r}) не найдена в документе"
    print(f"[selftest] все {len(all_tasks) - len(int_ids)} обычных Task присутствуют в документе по названию -- OK")

    # Именованные интеграции схлопнуты в один плейсхолдер: ни в таблице, ни
    # в критериях завершения конкретные названия сервисов не показываются.
    integration_names = {t["name"] for t in all_tasks if t["id"] in int_ids}
    for name in integration_names:
        assert name not in doc, f"именованная интеграция просочилась в документ: {name!r}"
    for service in ("Baselinker", "DHL", "PayU"):
        assert service not in doc, f"название сервиса {service!r} просочилось в документ"
    assert doc.count(INTEGRATION_PLACEHOLDER) == 2, (
        "плейсхолдер интеграций должен встретиться дважды -- один раз в таблице плана, "
        f"один раз как зависимость в T-6.5.1; фактически: {doc.count(INTEGRATION_PLACEHOLDER)}"
    )
    assert INTEGRATION_DELIVERABLE_PLACEHOLDER in doc
    assert doc.count(INTEGRATION_DELIVERABLE_PLACEHOLDER) == 1
    deliverables_section = render_deliverables(plan, int_ids)
    assert "T-6.4.2" not in deliverables_section, (
        "голый код T-6.4.2 просочился в критерии завершения (например, из чек-листа T-6.5.1); "
        "риски -- отдельный, уже задокументированный случай инлайнового жаргона, не сюда"
    )
    print(
        f"[selftest] {len(int_ids)} именованные интеграции схлопнуты в один плейсхолдер "
        "(таблица + критерии завершения + зависимости) -- OK"
    )

    # Зависимости выведены названиями, а не голыми T-ID.
    import re

    task_ids_with_deps = [t["id"] for t in all_tasks if t.get("depends_on")]
    assert task_ids_with_deps, "в тестовом плане нет ни одной Task с depends_on -- тест неполный"
    bare_id_in_table = re.search(r"\| T-\d", doc)
    assert not bare_id_in_table, "в таблице плана встречается голый T-ID вместо названия"
    print("[selftest] зависимости в таблице показаны названиями, не ID -- OK")

    # Риски -- только реально сработавшие, без source/condition-полей.
    risk_count_in_plan = len(plan.get("risks") or [])
    assert risk_count_in_plan > 0, "в тестовом плане нет ни одного риска -- ветка не проверена"
    for r in plan["risks"]:
        assert r["id"] not in doc, f"внутренний ID риска {r['id']} просочился в документ"
    print(f"[selftest] риски ({risk_count_in_plan} шт.) отражены без внутренних id/condition/source -- OK")

    # Сводка содержит числа спринтов.
    sp = plan["sprint_plan"]
    assert str(sp["total_sprints_used"]) in doc
    assert str(sp["available_sprints"]) in doc
    print("[selftest] итоговая сводка содержит числа спринтов -- OK")

    # Ветка с warning: план с дефицитом времени должен показать предупреждение.
    tight_plan = json.loads(json.dumps(plan))
    tight_plan["sprint_plan"]["warning"] = "Тестовое предупреждение о нехватке спринтов."
    tight_doc = render_client_document(tight_plan)
    assert "Тестовое предупреждение о нехватке спринтов." in tight_doc
    print("[selftest] sprint_plan.warning отражается в сводке, когда есть -- OK")

    # Ветка без рисков.
    no_risk_plan = json.loads(json.dumps(plan))
    no_risk_plan["risks"] = []
    no_risk_doc = render_client_document(no_risk_plan)
    assert "не выявлено" in no_risk_doc
    print("[selftest] пустой risks -- OK (текст про отсутствие рисков, не пустая таблица)")

    print("[selftest] Все проверки документа сработали корректно -- OK")

    # --- CSV-таблица правок ---
    import io

    task_sprint_lookup = plan.get("sprint_plan", {}).get("task_sprint", {})
    csv_text = render_corrections_csv(plan)
    reader = csv.DictReader(io.StringIO(csv_text))
    assert reader.fieldnames == CORRECTIONS_FIELDS, reader.fieldnames
    csv_rows = list(reader)
    assert len(csv_rows) == len(all_tasks), (
        f"в CSV должна быть одна строка на каждую реальную Task ({len(all_tasks)}), "
        f"фактически {len(csv_rows)}"
    )
    csv_task_ids = {row["Task ID"] for row in csv_rows}
    assert csv_task_ids == {t["id"] for t in all_tasks}, "Task ID в CSV не совпадают с Task ID плана"
    # Именованные интеграции в CSV НЕ схлопнуты -- в отличие от markdown-документа,
    # это рабочая таблица, сливается обратно по настоящим Task ID.
    assert int_ids <= csv_task_ids, "сгенерированные интеграции должны присутствовать в CSV по отдельности"
    assert all(row["Include"] == "yes" for row in csv_rows), "Include по умолчанию должен быть yes для всех Task"
    assert all(row["Comment"] == "" for row in csv_rows), "Comment по умолчанию должен быть пустым"
    for row in csv_rows:
        assert row["Спринт"] == str(task_sprint_lookup.get(row["Task ID"], "")), (
            f"{row['Task ID']}: Спринт в CSV не совпадает со sprint_plan.task_sprint"
        )
    print(f"[selftest] CSV-таблица правок: {len(csv_rows)} строк, все Task с Include=yes, Comment пуст -- OK")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plan", type=Path, help="Путь к плану (JSON), собранному assemble_plan.py")
    parser.add_argument("--output", type=Path, help="Куда записать документ (по умолчанию -- stdout)")
    parser.add_argument(
        "--corrections-output",
        type=Path,
        help="Куда записать CSV-таблицу правок (построчно по каждой Task, для Этапа 7.6)",
    )
    parser.add_argument("--selftest", action="store_true", help="Прогнать самопроверку на client-abc.plan.json")
    args = parser.parse_args()

    if args.selftest:
        run_selftest()
        return

    if not args.plan:
        parser.error("--plan обязателен (или используйте --selftest)")

    plan = json.loads(args.plan.read_text(encoding="utf-8"))

    report = validate_plan(plan)
    if report.findings:
        print(
            f"ПРЕДУПРЕЖДЕНИЕ: план не прошёл validate_plan.py начисто "
            f"({len(report.findings)} находок(и)) -- документ всё равно сгенерирован, "
            f"но рекомендуется сначала прогнать validate_plan.py --plan {args.plan}",
            file=sys.stderr,
        )

    doc = render_client_document(plan)

    if args.output:
        args.output.write_text(doc, encoding="utf-8")
        print(f"Записано: {args.output}", file=sys.stderr)
    else:
        print(doc)

    if args.corrections_output:
        # utf-8-sig -- чтобы кириллица корректно открывалась в Excel, а не
        # только в текстовых редакторах/git diff.
        args.corrections_output.write_text(render_corrections_csv(plan), encoding="utf-8-sig", newline="")
        print(f"Записано: {args.corrections_output}", file=sys.stderr)


if __name__ == "__main__":
    main()
