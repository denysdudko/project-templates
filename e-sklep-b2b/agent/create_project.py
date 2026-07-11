#!/usr/bin/env python3
"""Единая точка входа: клиентский input -> Jira.

Оркестратор поверх уже существующих шагов: `assemble_plan` (Этап 6) ->
`validate_plan` (Этап 7) -> `jira_export` (Этап 8). Консультант передаёт
`agent/input-schema.json` конкретного клиента и параметры подключения к
Jira одной командой -- никакого промежуточного файла для скачивания
консультантом между шагами (Этапы 7.5/7.6, документ для согласования и
приём правок, удалены из пайплайна, см. CHANGELOG.md).

Собранный JSON-план всё равно сохраняется на диск -- но как внутренний
артефакт аудита (`agent/runs/{client_id}/plan.json`), не как результат для
скачивания консультантом: именно такой артефакт (наряду с
`--state-file` Этапа 8) уже спасал при диагностике дублей на живом TPT
(см. CHANGELOG.md, Этап 8) -- отказываться от него не нужно.

По умолчанию -- dry-run (как и раньше в `jira_export.py`): только сборка +
валидация + печать того, что было бы создано в Jira, без единого POST.
Реальное создание -- только по `--execute` вместе с `--confirm`.

Запуск:
    python3 create_project.py --input client.input.json \
        --jira-url https://mycompany.atlassian.net --project-key ESK \
        --email consultant@example.com --api-token *** \
        [--execute --confirm] [--create-sprints]

    python3 create_project.py --selftest
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

from assemble_plan import assemble_plan, load_json
from jira_export import DEFAULT_FLAT_CHILD_LINK_TYPE, run_export
from validate_plan import validate_plan

AGENT_DIR = Path(__file__).resolve().parent
RUNS_DIR = AGENT_DIR / "runs"


def slugify_client_id(text: str) -> str:
    slug = re.sub(r"[^\w]+", "-", text.strip().lower()).strip("-_")
    return slug or "client"


def run_pipeline(
    input_data: dict,
    project_key: str,
    *,
    jira_url: str | None = None,
    email: str | None = None,
    api_token: str | None = None,
    schema_fixture: Path | None = None,
    client_id: str | None = None,
    runs_dir: Path = RUNS_DIR,
    allow_flat_fallback: bool = False,
    flat_child_link_type: str = DEFAULT_FLAT_CHILD_LINK_TYPE,
    execute: bool = False,
    confirm: bool = False,
    create_sprints: bool = False,
) -> Path:
    """assemble_plan -> сохранение аудит-артефакта -> validate_plan (не
    гейт, только предупреждение) -> jira_export. Возвращает путь к
    сохранённому plan.json."""
    plan = assemble_plan(input_data)

    client_id = client_id or slugify_client_id(input_data["client"])
    run_dir = runs_dir / client_id
    run_dir.mkdir(parents=True, exist_ok=True)
    plan_path = run_dir / "plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"План сохранён (внутренний артефакт аудита): {plan_path}", file=sys.stderr)

    report = validate_plan(plan)
    if report.findings:
        print(
            f"ПРЕДУПРЕЖДЕНИЕ: план не прошёл validate_plan.py начисто ({len(report.findings)} находок(и)) -- "
            f"экспорт продолжается, но рекомендуется сначала устранить находки",
            file=sys.stderr,
        )

    run_export(
        plan,
        project_key,
        jira_url=jira_url,
        email=email,
        api_token=api_token,
        schema_fixture=schema_fixture,
        allow_flat_fallback=allow_flat_fallback,
        flat_child_link_type=flat_child_link_type,
        state_file=run_dir / "jira-export-state.json",
        execute=execute,
        confirm=confirm,
        create_sprints=create_sprints,
    )
    return plan_path


# ---------------------------------------------------------------------------
# Self-test -- офлайн (schema_fixture вместо живого Jira-проекта), проверяет
# сборку + сохранение аудит-артефакта + dry-run вызов jira_export без сети.
# ---------------------------------------------------------------------------


def run_selftest() -> None:
    input_data = load_json(AGENT_DIR / "examples" / "client-abc.input.json")
    schema_fixture = AGENT_DIR / "examples" / "jira-project-schema.example.json"

    with tempfile.TemporaryDirectory() as tmp:
        runs_dir = Path(tmp) / "runs"
        plan_path = run_pipeline(
            input_data,
            project_key="ESK",
            schema_fixture=schema_fixture,
            runs_dir=runs_dir,
        )

        expected_client_id = slugify_client_id(input_data["client"])
        assert plan_path == runs_dir / expected_client_id / "plan.json", plan_path
        assert plan_path.exists(), "plan.json не сохранён по ожидаемому пути"
        saved_plan = json.loads(plan_path.read_text(encoding="utf-8"))
        assert saved_plan["charter"]["project_name"] == input_data["project_name"]
        print(f"[selftest] plan.json сохранён как аудит-артефакт: {plan_path} -- OK")

        report = validate_plan(saved_plan)
        assert not report.findings, f"regression: собранный план должен быть чист: {report.findings}"
        print("[selftest] validate_plan на собранном плане -- 0 находок -- OK")

        assert not (runs_dir / expected_client_id / "jira-export-state.json").exists(), (
            "dry-run (--execute не передан) не должен писать state-файл"
        )
        print("[selftest] dry-run не создаёт jira-export-state.json (нет --execute) -- OK")

    custom_id_slug = slugify_client_id("Custom Client ID!!!")
    assert custom_id_slug == "custom-client-id", custom_id_slug
    print(f"[selftest] slugify_client_id: {custom_id_slug!r} -- OK")

    print("[selftest] Все проверки create_project.py сработали корректно -- OK")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, help="Путь к заполненному input-schema.json клиента")
    parser.add_argument("--jira-url", help="Базовый URL Jira (например https://mycompany.atlassian.net)")
    parser.add_argument("--project-key", help="Ключ целевого Jira-проекта (уже существующего)")
    parser.add_argument("--email", help="Email для Basic Auth (вместе с Jira API token)")
    parser.add_argument("--api-token", help="Jira API token")
    parser.add_argument(
        "--schema-fixture",
        type=Path,
        help="Офлайн JSON со схемой проекта вместо живого API -- для демо/тестов, не для реального запуска",
    )
    parser.add_argument(
        "--client-id",
        help="Имя поддиректории agent/runs/{client_id}/ для аудит-артефактов "
             "(по умолчанию -- слаг из charter.client)",
    )
    parser.add_argument(
        "--runs-dir", type=Path, default=RUNS_DIR, help="Куда сохранять аудит-артефакты (по умолчанию agent/runs)"
    )
    parser.add_argument(
        "--allow-flat-fallback",
        action="store_true",
        help="Разрешить плоскую структуру (WBS и Task -- оба Issue), если Subtask недоступен в проекте",
    )
    parser.add_argument(
        "--flat-child-link-type",
        default=DEFAULT_FLAT_CHILD_LINK_TYPE,
        help=f"Тип Issue Link между Task и WBS в плоской структуре (по умолчанию {DEFAULT_FLAT_CHILD_LINK_TYPE!r})",
    )
    parser.add_argument("--execute", action="store_true", help="Реально создавать issues в Jira (по умолчанию -- dry-run)")
    parser.add_argument("--confirm", action="store_true", help="Явное подтверждение плана человеком (обязательно вместе с --execute)")
    parser.add_argument(
        "--create-sprints",
        action="store_true",
        help="Опционально создать Sprint на доске проекта и привязать к ним WBS-Issue",
    )
    parser.add_argument("--selftest", action="store_true", help="Прогнать самопроверку офлайн")
    args = parser.parse_args()

    if args.selftest:
        run_selftest()
        return

    if not args.input:
        parser.error("--input обязателен (или используйте --selftest)")
    if not args.project_key:
        parser.error("--project-key обязателен")
    if not args.schema_fixture and not (args.jira_url and args.email and args.api_token):
        parser.error("нужен либо --schema-fixture, либо все из --jira-url/--email/--api-token")

    input_data = load_json(args.input)
    run_pipeline(
        input_data,
        args.project_key,
        jira_url=args.jira_url,
        email=args.email,
        api_token=args.api_token,
        schema_fixture=args.schema_fixture,
        client_id=args.client_id,
        runs_dir=args.runs_dir,
        allow_flat_fallback=args.allow_flat_fallback,
        flat_child_link_type=args.flat_child_link_type,
        execute=args.execute,
        confirm=args.confirm,
        create_sprints=args.create_sprints,
    )


if __name__ == "__main__":
    main()
