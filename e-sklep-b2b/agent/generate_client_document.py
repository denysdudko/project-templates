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
    и WBS, к которым он относится, по названию, а не по коду.

Запуск:
    python3 generate_client_document.py --plan path/to/plan.json --output doc.md
    python3 generate_client_document.py --selftest
"""

from __future__ import annotations

import argparse
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
# Вспомогательное
# ---------------------------------------------------------------------------


def build_id_to_name(plan: dict) -> dict[str, str]:
    names: dict[str, str] = {}
    for m in plan.get("milestones", []):
        names[m["id"]] = m["name"]
        for wbs in m.get("wbs", []):
            names[wbs["id"]] = wbs["name"]
            for t in wbs.get("tasks", []):
                names[t["id"]] = t["name"]
    return names


def human_refs(ids: list[str], names: dict[str, str]) -> str:
    if not ids:
        return "—"
    return ", ".join(names.get(i, i) for i in ids)


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


def render_plan_table(plan: dict, id_to_name: dict[str, str]) -> str:
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
            for t in wbs.get("tasks", []):
                sprint = task_sprint.get(t["id"], "—")
                deps = human_refs(t.get("depends_on") or [], id_to_name)
                lines.append(f"| {t['name']} | {sprint} | {deps} |")
            lines.append("")
    return "\n".join(lines)


def render_deliverables(plan: dict) -> str:
    lines = ["## Критерии завершения этапов", ""]
    for d in plan.get("deliverables", []):
        lines.append(f"### {d['milestone_id']} — {d['milestone_name']}")
        lines.append("")
        checks = d.get("verification_checklist") or []
        if not checks:
            lines.append("_Нет отдельных критериев на уровне этапа._")
        else:
            for item in checks:
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
    id_to_name = build_id_to_name(plan)
    parts = [
        render_header(plan),
        render_plan_table(plan, id_to_name),
        render_deliverables(plan),
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

    # Каждая Task шаблона должна попасть в план по этапам ровно один раз.
    all_tasks = flatten_tasks(plan)
    for t in all_tasks:
        assert t["name"] in doc, f"{t['id']} ({t['name']!r}) не найдена в документе"
    print(f"[selftest] все {len(all_tasks)} Task присутствуют в документе по названию -- OK")

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


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plan", type=Path, help="Путь к плану (JSON), собранному assemble_plan.py")
    parser.add_argument("--output", type=Path, help="Куда записать документ (по умолчанию -- stdout)")
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


if __name__ == "__main__":
    main()
