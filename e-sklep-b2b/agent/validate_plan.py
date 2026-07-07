#!/usr/bin/env python3
"""Этап 7 — валидатор собранного плана (выход agent/assemble_plan.py, Этап 6).

Это отчёт для консультанта/PM перед экспортом в Jira (Этап 8), не гейт:
валидатор ничего не блокирует и не переписывает — только явно перечисляет
находки, вместо того чтобы молча пропустить их дальше по конвейеру.

Проверки:
  1. integrity   -- все ID в depends_on/used_by существуют среди реальных
                     Task/WBS ID плана.
  2. source_url  -- каждый source.url принадлежит одному из доменов/разделов
                     официальной документации Comarch.
  3. source      -- у каждой Task есть source; отсутствие url допустимо
                     только для source.type == "Internal Project Methodology".
  4. checklist_shape -- interview_checklist/verification_checklist -- списки
                     строк, без вложенных dict/list (тот самый баг с
                     незакавыченным ": " внутри пункта чек-листа, найденный
                     и исправленный вручную перед Этапом 7).
  5. cross_section -- каждая Task из milestones присутствует в dependencies,
                     effort_estimates и sprint_plan.task_sprint, и наоборот
                     -- никаких "осиротевших" записей без Task.

Запуск:
    python3 validate_plan.py --plan path/to/plan.json
    python3 validate_plan.py --plan path/to/plan.json --strict   # exit 1 при находках
    python3 validate_plan.py --selftest
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import re

AGENT_DIR = Path(__file__).resolve().parent

# Источник истины для доменов/разделов документации Comarch -- тот же
# список, что в docs/principles.md, docs/selection-rules.md и
# agent/sprint-mapping-rules.md:
#   https://pomoc.comarchesklep.pl/kategoria/jak-zaczac/
#   https://pomoc.comarchesklep.pl/kategoria/b2b/
#   https://pomoc.comarch.pl/optima/pl/2026_5/dokumentacja/comarch-e-sklep/
#   https://pomoc.comarch.pl/optima/pl/2026_5/dokumentacja/wspolpraca-z-comarch-e-sklep/
# Это 4 URL, но 2 уникальных домена -- в реальных Task (см.
# docs/source-map.md) source.url указывает на конкретные статьи
# (/artykul/<slug>/, /kategoria/<slug>/ на pomoc.comarchesklep.pl;
# /optima/pl/<версия>/dokumentacja/<slug>/ на pomoc.comarch.pl, версия
# в пути реально варьируется -- 2026 и 2026_5 оба встречаются), а не
# буквально на эти 4 страницы. Проверка -- по домену + форме пути
# ("раздел"), не по точному совпадению URL.
ALLOWED_DOC_SECTIONS: dict[str, re.Pattern] = {
    "pomoc.comarchesklep.pl": re.compile(r"^/(artykul|kategoria)/[^/]+/?$"),
    "pomoc.comarch.pl": re.compile(r"^/optima/pl/[^/]+/dokumentacja/[^/]+/?$"),
}

INTERNAL_METHODOLOGY = "Internal Project Methodology"
OFFICIAL_DOC = "Official Comarch Documentation"


@dataclass
class Finding:
    check: str
    severity: str  # "error" | "warning"
    message: str
    location: str


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)

    def add(self, check: str, message: str, location: str, severity: str = "error") -> None:
        self.findings.append(Finding(check=check, severity=severity, message=message, location=location))

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warning"]

    def ok(self) -> bool:
        return not self.errors


# ---------------------------------------------------------------------------
# Вспомогательное: развернуть план в плоские структуры для проверок
# ---------------------------------------------------------------------------


def flatten_tasks(plan: dict) -> list[dict]:
    return [t for m in plan.get("milestones", []) for wbs in m.get("wbs", []) for t in wbs.get("tasks", [])]


def collect_ids(plan: dict) -> tuple[set[str], set[str], set[str]]:
    """Возвращает (task_ids, wbs_ids, milestone_ids)."""
    task_ids, wbs_ids, milestone_ids = set(), set(), set()
    for m in plan.get("milestones", []):
        milestone_ids.add(m["id"])
        for wbs in m.get("wbs", []):
            wbs_ids.add(wbs["id"])
            for t in wbs.get("tasks", []):
                task_ids.add(t["id"])
    return task_ids, wbs_ids, milestone_ids


# ---------------------------------------------------------------------------
# 1. integrity -- depends_on/used_by ссылаются на реальные Task/WBS ID
# ---------------------------------------------------------------------------


def check_integrity(plan: dict, report: Report) -> None:
    task_ids, wbs_ids, milestone_ids = collect_ids(plan)
    valid_targets = task_ids | wbs_ids
    for t in flatten_tasks(plan):
        for field_name in ("depends_on", "used_by"):
            for ref in t.get(field_name) or []:
                if ref in valid_targets:
                    continue
                hint = " (это Milestone ID, а не Task/WBS ID)" if ref in milestone_ids else ""
                report.add(
                    "integrity",
                    f"{t['id']}.{field_name} ссылается на несуществующий ID {ref!r}{hint}",
                    location=t["id"],
                )

    # dependencies -- отдельный раздел плана, тоже граф на тех же ID
    for tid, deps in (plan.get("dependencies") or {}).items():
        for dep in deps:
            if dep not in valid_targets:
                hint = " (Milestone ID)" if dep in milestone_ids else ""
                report.add(
                    "integrity",
                    f"dependencies[{tid!r}] ссылается на несуществующий ID {dep!r}{hint}",
                    location=tid,
                )


# ---------------------------------------------------------------------------
# 2. source_url -- домен/раздел документации Comarch
# ---------------------------------------------------------------------------


def is_allowed_doc_url(url: str) -> bool:
    parsed = urlparse(url)
    pattern = ALLOWED_DOC_SECTIONS.get(parsed.netloc)
    return bool(pattern and pattern.match(parsed.path))


def check_source_url(plan: dict, report: Report) -> None:
    for t in flatten_tasks(plan):
        source = t.get("source") or {}
        url = source.get("url")
        if source.get("type") == OFFICIAL_DOC and url:
            if not is_allowed_doc_url(url):
                report.add(
                    "source_url",
                    f"{t['id']}.source.url вне разрешённых доменов/разделов документации Comarch: {url!r}",
                    location=t["id"],
                )


# ---------------------------------------------------------------------------
# 3. source -- ни одна Task не без source, кроме Internal Project Methodology
# ---------------------------------------------------------------------------


def check_source_presence(plan: dict, report: Report) -> None:
    for t in flatten_tasks(plan):
        source = t.get("source")
        if not source or not source.get("type"):
            report.add("source", f"{t['id']} создана без source (или без source.type)", location=t["id"])
            continue
        stype = source["type"]
        if stype not in (INTERNAL_METHODOLOGY, OFFICIAL_DOC):
            report.add(
                "source",
                f"{t['id']}.source.type={stype!r} -- не входит в разрешённый набор "
                f"({OFFICIAL_DOC!r} / {INTERNAL_METHODOLOGY!r})",
                location=t["id"],
            )
            continue
        if stype == OFFICIAL_DOC and not source.get("url"):
            report.add(
                "source",
                f"{t['id']}.source.type={OFFICIAL_DOC!r}, но source.url отсутствует",
                location=t["id"],
            )


# ---------------------------------------------------------------------------
# 4. checklist_shape -- interview_checklist/verification_checklist: list[str]
# ---------------------------------------------------------------------------


def check_checklist_shape(plan: dict, report: Report) -> None:
    for t in flatten_tasks(plan):
        for field_name in ("interview_checklist", "verification_checklist"):
            value = t.get(field_name)
            if value is None:
                continue
            if not isinstance(value, list):
                report.add(
                    "checklist_shape",
                    f"{t['id']}.{field_name} должен быть списком, а не {type(value).__name__}",
                    location=t["id"],
                )
                continue
            for idx, item in enumerate(value):
                if not isinstance(item, str):
                    report.add(
                        "checklist_shape",
                        f"{t['id']}.{field_name}[{idx}] -- {type(item).__name__}, а не строка "
                        f"(похоже на незакавыченный ': ' внутри пункта чек-листа: {item!r})",
                        location=t["id"],
                    )


# ---------------------------------------------------------------------------
# 5. cross_section -- Task <-> dependencies/effort_estimates/sprint_plan.task_sprint
# ---------------------------------------------------------------------------


def check_cross_section_completeness(plan: dict, report: Report) -> None:
    task_ids = {t["id"] for t in flatten_tasks(plan)}

    sections = {
        "dependencies": set((plan.get("dependencies") or {}).keys()),
        "effort_estimates": set((plan.get("effort_estimates") or {}).keys()),
        "sprint_plan.task_sprint": set(((plan.get("sprint_plan") or {}).get("task_sprint") or {}).keys()),
    }

    for name, ids_in_section in sections.items():
        missing = sorted(task_ids - ids_in_section)
        orphaned = sorted(ids_in_section - task_ids)
        for tid in missing:
            report.add(
                "cross_section",
                f"{tid} есть в milestones, но отсутствует в {name}",
                location=tid,
            )
        for tid in orphaned:
            report.add(
                "cross_section",
                f"{tid} есть в {name}, но отсутствует среди Task в milestones (осиротевшая запись)",
                location=tid,
            )


# ---------------------------------------------------------------------------
# Оркестрация
# ---------------------------------------------------------------------------

CHECKS = [
    ("integrity", check_integrity),
    ("source_url", check_source_url),
    ("source", check_source_presence),
    ("checklist_shape", check_checklist_shape),
    ("cross_section", check_cross_section_completeness),
]


def validate_plan(plan: dict) -> Report:
    report = Report()
    for _name, fn in CHECKS:
        fn(plan, report)
    return report


def format_report(report: Report, plan: dict) -> str:
    lines = []
    n_tasks = len(flatten_tasks(plan))
    lines.append(f"Проверено Task: {n_tasks}")
    lines.append(f"Находок: {len(report.findings)} (errors: {len(report.errors)}, warnings: {len(report.warnings)})")
    lines.append("")
    if not report.findings:
        lines.append("Нарушений не найдено.")
        return "\n".join(lines)

    by_check: dict[str, list[Finding]] = {}
    for f in report.findings:
        by_check.setdefault(f.check, []).append(f)

    for check_name, _fn in CHECKS:
        items = by_check.get(check_name)
        if not items:
            continue
        lines.append(f"[{check_name}] {len(items)} находок(и):")
        for f in items:
            lines.append(f"  - ({f.severity}) {f.message}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Self-test -- намеренно ломаем каждую проверку на копии реального плана,
# плюс regression-прогон на agent/examples/client-abc.plan.json.
# ---------------------------------------------------------------------------


def _load_client_abc_plan() -> dict:
    path = AGENT_DIR / "examples" / "client-abc.plan.json"
    return json.loads(path.read_text(encoding="utf-8"))


def run_selftest() -> None:
    plan = _load_client_abc_plan()

    report = validate_plan(plan)
    print(f"[selftest] regression на agent/examples/client-abc.plan.json: {len(report.findings)} находок(и)")

    # Известная проблема "used_by указывает на Milestone ID вместо Task/WBS
    # ID" (была open-issues.md п.1) закрыта точечной правкой tasks/M*_tasks.yaml
    # -- реальный план теперь обязан быть полностью чист по всем 5 проверкам.
    if report.findings:
        print(format_report(report, plan))
        print(
            f"[selftest] ОШИБКА: {len(report.findings)} находок(и) на реальном плане -- "
            f"регрессия должна быть чистой (0)"
        )
        sys.exit(1)
    print("[selftest] regression -- OK: 0 находок")

    # --- integrity: сломать depends_on ---
    broken = json.loads(json.dumps(plan))
    broken["milestones"][0]["wbs"][0]["tasks"][0]["depends_on"] = ["T-NOT-A-REAL-TASK"]
    r = validate_plan(broken)
    assert any(f.check == "integrity" for f in r.findings), "integrity не поймал несуществующий depends_on"
    print("[selftest] integrity: несуществующий ID в depends_on -- поймано OK")

    # --- integrity: used_by указывает на Milestone ID ---
    broken = json.loads(json.dumps(plan))
    broken["milestones"][0]["wbs"][0]["tasks"][0]["used_by"] = ["M9"]
    r = validate_plan(broken)
    hits = [f for f in r.findings if f.check == "integrity" and "Milestone ID" in f.message]
    assert hits, "integrity не поймал used_by на Milestone ID"
    print("[selftest] integrity: used_by на Milestone ID -- поймано OK")

    # --- source_url: домен вне списка ---
    broken = json.loads(json.dumps(plan))
    broken["milestones"][0]["wbs"][0]["tasks"][0]["source"] = {
        "type": OFFICIAL_DOC,
        "url": "https://example.com/not-comarch/",
    }
    r = validate_plan(broken)
    assert any(f.check == "source_url" for f in r.findings), "source_url не поймал чужой домен"
    print("[selftest] source_url: домен вне списка -- поймано OK")

    # --- source_url: домен верный, но раздел/форма пути не подходит ---
    broken = json.loads(json.dumps(plan))
    broken["milestones"][0]["wbs"][0]["tasks"][0]["source"] = {
        "type": OFFICIAL_DOC,
        "url": "https://pomoc.comarchesklep.pl/",
    }
    r = validate_plan(broken)
    assert any(f.check == "source_url" for f in r.findings), "source_url не поймал URL без /artykul|kategoria/"
    print("[selftest] source_url: верный домен, но не раздел -- поймано OK")

    # --- source: Official Comarch Documentation без url ---
    broken = json.loads(json.dumps(plan))
    broken["milestones"][0]["wbs"][0]["tasks"][0]["source"] = {"type": OFFICIAL_DOC}
    r = validate_plan(broken)
    assert any(f.check == "source" for f in r.findings), "source не поймал Official Comarch Documentation без url"
    print("[selftest] source: Official Comarch Documentation без url -- поймано OK")

    # --- source: Task вообще без source ---
    broken = json.loads(json.dumps(plan))
    del broken["milestones"][0]["wbs"][0]["tasks"][0]["source"]
    r = validate_plan(broken)
    assert any(f.check == "source" for f in r.findings), "source не поймал Task без source вообще"
    print("[selftest] source: Task без source -- поймано OK")

    # --- source: Internal Project Methodology без url -- НЕ должно быть находкой ---
    broken = json.loads(json.dumps(plan))
    broken["milestones"][0]["wbs"][0]["tasks"][0]["source"] = {"type": INTERNAL_METHODOLOGY}
    r = validate_plan(broken)
    assert not any(
        f.check == "source" and f.location == broken["milestones"][0]["wbs"][0]["tasks"][0]["id"] for f in r.findings
    ), "source ложно сработал на Internal Project Methodology без url"
    print("[selftest] source: Internal Project Methodology без url -- не ложное срабатывание, OK")

    # --- checklist_shape: воспроизвести именно тот баг, что уже нашли и исправили ---
    broken = json.loads(json.dumps(plan))
    broken["milestones"][0]["wbs"][0]["tasks"][0]["verification_checklist"] = [
        {"Проверить, что X": "Y, Z."}
    ]
    r = validate_plan(broken)
    hits = [f for f in r.findings if f.check == "checklist_shape"]
    assert hits, "checklist_shape не поймал dict вместо строки"
    print("[selftest] checklist_shape: dict вместо строки в чек-листе -- поймано OK")

    # --- cross_section: Task есть в milestones, но выпала из dependencies ---
    broken = json.loads(json.dumps(plan))
    some_id = broken["milestones"][0]["wbs"][0]["tasks"][0]["id"]
    del broken["dependencies"][some_id]
    r = validate_plan(broken)
    hits = [f for f in r.findings if f.check == "cross_section" and f.location == some_id]
    assert hits, "cross_section не поймал пропажу Task из dependencies"
    print("[selftest] cross_section: Task выпала из dependencies -- поймано OK")

    # --- cross_section: осиротевшая запись в effort_estimates без Task ---
    broken = json.loads(json.dumps(plan))
    broken["effort_estimates"]["T-ORPHAN"] = {"task_type": "configuration", "hours": 1}
    r = validate_plan(broken)
    hits = [f for f in r.findings if f.check == "cross_section" and "T-ORPHAN" in f.message]
    assert hits, "cross_section не поймал осиротевшую запись в effort_estimates"
    print("[selftest] cross_section: осиротевшая запись в effort_estimates -- поймано OK")

    print("[selftest] Все проверки валидатора сработали корректно -- OK")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plan", type=Path, help="Путь к плану (JSON), собранному assemble_plan.py")
    parser.add_argument("--strict", action="store_true", help="exit 1, если есть хотя бы одна находка")
    parser.add_argument("--selftest", action="store_true", help="Прогнать самопроверку + regression на client-abc.plan.json")
    args = parser.parse_args()

    if args.selftest:
        run_selftest()
        return

    if not args.plan:
        parser.error("--plan обязателен (или используйте --selftest)")

    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    report = validate_plan(plan)
    print(format_report(report, plan))

    if args.strict and not report.ok():
        sys.exit(1)


if __name__ == "__main__":
    main()
