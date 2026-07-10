#!/usr/bin/env python3
"""Этап 8 — экспорт смерженного плана в существующий Jira-проект.

Вход: результат Этапа 7.6 (`merge-corrections.py`) — смерженный и
провалидированный план, не сырой JSON Этапа 6. Целевой Jira-проект уже
существует (не создаётся этим скриптом).

Маппинг (docs/agent-development-plan.md, Этап 8):

    Наш уровень          Jira
    -------------------  ------------------------------------------------
    Весь план            1 Epic (summary = charter.project_name,
                          description = цель/даты/заказчик + Риски +
                          Deliverables)
    Milestone (M1-M9)     Label на каждой issue/subtask (M3, M6 и т.п.)
    WBS                   Issue, child Эпика -- summary = название WBS
    Task (наш)             Subtask под соответствующим WBS-Issue --
                          summary = название Task, description =
                          Interview/Verification checklist, Sprint = имя
                          спринта (sprint_plan.sprints[].name)
    depends_on/used_by    Issue Links (Blocks: "outward blocks inward")
    Риски (сработавшие)   Секция текста в description Эпика (не отдельные issue)
    Deliverables          Секция текста в description Эпика по milestone

Обязательное предусловие: перед построением маппинга скрипт запрашивает у
целевого Jira-проекта реальные issuetypes (`GET /rest/api/3/project/{key}`)
и подтверждает, что Subtask доступен на уровне схемы проекта. Если
Subtask недоступен (team-managed проект без Subtask) -- скрипт
останавливается с явным объяснением и НЕ выбирает обходной путь молча:
плоская структура (WBS и Task -- оба Issue, связаны Issue Link) включается
только по явному `--allow-flat-fallback`.

Явное подтверждение перед созданием issues: по умолчанию скрипт работает
в dry-run (только GET-запросы для определения схемы проекта + печать
того, что было бы создано, без единого POST/create). Реальное создание --
только по `--execute` вместе с `--confirm` (или интерактивным
подтверждением в терминале).

Известное ограничение (v1, не выдумывается обходом): нативное поле Jira
Sprint (`customfield_...`, обнаруживается через `GET /rest/api/3/field`)
принимает не текст, а ID уже существующего Sprint на Scrum-доске --
создание/сопоставление реальных Sprint через Agile REST API за пределами
этого скрипта (отдельная, более объёмная задача). Поэтому имя спринта
пишется первой строкой в description Issue/Subtask ("Sprint: Спринт N
(...)") -- человекочитаемо и не требует предварительной настройки доски;
`schema.sprint_field_id`, если найден, только показывается в dry-run
отчёте для консультанта, но не проставляется в issue напрямую.

Risks/Deliverables в description Эпика переиспользуют
`render_risks`/`render_deliverables` из `generate_client_document.py`
(Этап 7.5) целиком -- включая уже применённый `clean_business_text()` --
а не заново реализуют очистку текста риска.

Устойчивость к сети (найдено на реальном прогоне на TPT): `JiraClient._request`
ретраит только transient-ошибки (обрыв соединения, HTTP 429/5xx) с
экспоненциальным backoff (до 4 попыток), не ретраит логические 4xx (400/409
и т.п.) -- повтор их не исправит. `--execute` дополнительно пишет
key_by_placeholder (наш ID -> реальный Jira-ключ) в JSON-файл по ходу
создания (`--state-file`, по умолчанию `<plan>.jira-export-state.json`) --
переживает обрыв сети, не требует парсинга лога вручную. Оба POST-метода
(`create_issue`/`create_issue_link`) не идемпотентны -- при обрыве после
фактического создания на сервере, но до получения ответа, retry рискует
создать дубль; это не решается автоматически (см. комментарии в коде),
только смягчается видимостью state-файла для ручной сверки постфактум.

Запуск:
    python3 jira_export.py --plan merged-plan.json \
        --jira-url https://mycompany.atlassian.net --project-key ESK \
        --email consultant@example.com --api-token *** [--execute --confirm]

    # офлайн-демо/тесты без живого Jira-проекта:
    python3 jira_export.py --plan merged-plan.json \
        --schema-fixture examples/jira-project-schema.example.json

    python3 jira_export.py --selftest
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from generate_client_document import (
    build_id_to_name,
    clean_business_text,
    integration_task_ids,
    render_deliverables,
    render_risks,
)
from validate_plan import flatten_tasks, validate_plan

AGENT_DIR = Path(__file__).resolve().parent

LINK_TYPE_BLOCKS = "Blocks"  # стандартный тип связи Jira (outward "blocks" / inward "is blocked by")
DEFAULT_FLAT_CHILD_LINK_TYPE = "Relates"  # стандартный тип, доступен в любом проекте по умолчанию

EPIC_PLACEHOLDER_ID = "EPIC"

EPIC_TYPE_NAMES = {"epic", "epik"}  # "epik" -- польская локализация Jira (напр. TPT)

RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}
MAX_REQUEST_ATTEMPTS = 4  # 1 первая попытка + до 3 повторов
RETRY_BACKOFF_SECONDS = (1, 2, 4)  # пауза после попытки 1, 2, 3 (экспоненциально)


class JiraApiError(RuntimeError):
    pass


class SubtaskUnavailableError(RuntimeError):
    """Целевой проект не предоставляет issuetype Subtask на уровне схемы,
    и --allow-flat-fallback не передан -- решение явно за человеком."""


# ---------------------------------------------------------------------------
# Схема целевого Jira-проекта (issuetypes + Sprint field) -- обязательное
# предусловие перед построением маппинга.
# ---------------------------------------------------------------------------


@dataclass
class ProjectSchema:
    issue_types_raw: list[dict]
    epic_type: dict | None
    task_type: dict | None
    subtask_type: dict | None
    sprint_field_id: str | None
    epic_link_field_id: str | None  # None -> использовать fields.parent (team-managed/новая иерархия)


def resolve_issue_types(issue_types_raw: list[dict]) -> tuple[dict | None, dict | None, dict | None]:
    subtask_type = next((it for it in issue_types_raw if it.get("subtask")), None)
    epic_type = next((it for it in issue_types_raw if (it.get("name") or "").strip().lower() in EPIC_TYPE_NAMES), None)
    non_special = [it for it in issue_types_raw if it is not subtask_type and it is not epic_type]
    task_type = next((it for it in non_special if (it.get("name") or "").strip().lower() == "task"), None)
    if task_type is None and non_special:
        task_type = non_special[0]
    return epic_type, task_type, subtask_type


def build_project_schema(
    issue_types_raw: list[dict], fields_raw: list[dict] | None
) -> ProjectSchema:
    epic_type, task_type, subtask_type = resolve_issue_types(issue_types_raw)
    sprint_field_id = None
    epic_link_field_id = None
    for f in fields_raw or []:
        name = (f.get("name") or "").strip().lower()
        if name == "sprint" and sprint_field_id is None:
            sprint_field_id = f.get("id")
        elif name == "epic link" and epic_link_field_id is None:
            epic_link_field_id = f.get("id")
    return ProjectSchema(
        issue_types_raw=issue_types_raw,
        epic_type=epic_type,
        task_type=task_type,
        subtask_type=subtask_type,
        sprint_field_id=sprint_field_id,
        epic_link_field_id=epic_link_field_id,
    )


def require_subtask_or_flat_confirmation(schema: ProjectSchema, allow_flat_fallback: bool) -> bool:
    """Возвращает True, если экспорт должен идти в режиме плоской структуры.

    Если Subtask недоступен и явного разрешения на fallback нет -- не
    выдумывает обходной путь молча, а поднимает SubtaskUnavailableError с
    объяснением и явным вопросом консультанту."""
    if schema.epic_type is None:
        raise JiraApiError(
            "В проекте не найден issuetype 'Epic' -- маппинг Этапа 8 требует Epic на уровне "
            "всего плана. Это не восстановимо флагом (в отличие от Subtask) -- нужен проект, "
            "где Epic присутствует в схеме."
        )
    if schema.task_type is None:
        raise JiraApiError(
            "В проекте не найдено ни одного обычного (не Subtask, не Epic) issuetype для "
            "маппинга WBS/Task на Issue."
        )
    if schema.subtask_type is not None:
        return False
    if allow_flat_fallback:
        return True
    raise SubtaskUnavailableError(
        "Целевой проект не предоставляет issuetype Subtask на уровне схемы проекта "
        "(team-managed проект без Subtask). Экспорт остановлен -- это решение не принимается "
        "молча. Вопрос консультанту: использовать плоскую структуру вместо Subtask (WBS и Task "
        "-- оба Issue, связаны Issue Link relates to/is child of)? Если да -- повторите запуск "
        "с флагом --allow-flat-fallback."
    )


# ---------------------------------------------------------------------------
# JiraClient -- тонкая обёртка над REST API v3 (Jira Cloud). Используется
# только при переданных --jira-url/--project-key/--email/--api-token;
# офлайн-демо/тесты идут через --schema-fixture и FakeJiraClient (см. ниже).
# ---------------------------------------------------------------------------


class JiraClient:
    def __init__(
        self,
        base_url: str,
        email: str,
        api_token: str,
        project_key: str,
        opener=urllib.request.urlopen,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.project_key = project_key
        token = base64.b64encode(f"{email}:{api_token}".encode("utf-8")).decode("ascii")
        self._auth_header = f"Basic {token}"
        self._opener = opener  # подменяется в --selftest фейковым opener'ом для проверки retry без сети

    def _request(self, method: str, path: str, body: dict | None = None) -> dict | list:
        """Ретраит только transient-ошибки (ConnectionResetError/URLError, HTTP
        429/5xx) с экспоненциальным backoff -- обрыв сети на TPT (Этап 8)
        показал, что без этого консультанту приходится вручную парсить лог,
        чтобы понять, что реально создалось. HTTP 400/409 и прочие 4xx (кроме
        429) -- логическая ошибка запроса (например, невалидный ADF), retry
        её не исправит и рискует бесполезно задержать явную остановку."""
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None

        for attempt in range(1, MAX_REQUEST_ATTEMPTS + 1):
            req = urllib.request.Request(url, data=data, method=method)
            req.add_header("Authorization", self._auth_header)
            req.add_header("Content-Type", "application/json")
            req.add_header("Accept", "application/json")
            try:
                with self._opener(req) as resp:
                    raw = resp.read()
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                if exc.code not in RETRYABLE_HTTP_STATUS or attempt == MAX_REQUEST_ATTEMPTS:
                    raise JiraApiError(f"{method} {path} -> HTTP {exc.code}: {detail}") from exc
                reason = f"HTTP {exc.code}"
            except (urllib.error.URLError, ConnectionResetError) as exc:
                if attempt == MAX_REQUEST_ATTEMPTS:
                    raise JiraApiError(
                        f"{method} {path} -> сетевая ошибка после {MAX_REQUEST_ATTEMPTS} попыток: {exc}"
                    ) from exc
                reason = str(exc)

            delay = RETRY_BACKOFF_SECONDS[attempt - 1]
            print(
                f"ПОВТОР {attempt}/{MAX_REQUEST_ATTEMPTS - 1}: {method} {path} -- {reason} (transient) -- "
                f"жду {delay}с и пробую снова",
                file=sys.stderr,
            )
            time.sleep(delay)

    # --- только чтение -- безопасно и в dry-run ---

    def get_issue_types(self) -> list[dict]:
        data = self._request("GET", f"/rest/api/3/project/{self.project_key}")
        return data.get("issueTypes", [])

    def get_fields(self) -> list[dict]:
        return self._request("GET", "/rest/api/3/field")

    # --- запись -- только при --execute ---

    def create_issue(self, fields: dict) -> str:
        """POST не идемпотентен: retry в _request() ретраит только
        transient-ошибки уровня соединения (когда неизвестно, дошёл ли запрос
        до сервера) -- если Jira успела создать issue, но ответ не дошёл до
        клиента, повтор создаст дубль. Тот же класс риска уже проявился на
        TPT при обрыве create_issue_link. Не решается в этом проходе --
        полноценная защита требовала бы идемпотентных ключей на стороне Jira,
        которых REST API v3 не предоставляет; persisted state (execute_export)
        позволяет обнаружить и вручную сверить дубли постфактум, а не
        предотвращает их заранее."""
        data = self._request("POST", "/rest/api/3/issue", {"fields": fields})
        return data["key"]

    def create_issue_link(self, link_type: str, outward_key: str, inward_key: str) -> None:
        """Тот же риск дубля при retry после обрыва соединения, что и в
        create_issue выше -- см. комментарий там."""
        self._request(
            "POST",
            "/rest/api/3/issueLink",
            {
                "type": {"name": link_type},
                "outwardIssue": {"key": outward_key},
                "inwardIssue": {"key": inward_key},
            },
        )


class FakeJiraClient:
    """Для --selftest и разработки без живого Jira-проекта -- те же методы,
    что JiraClient, но в памяти; create_issue выдаёт синтетические ключи."""

    def __init__(self, issue_types: list[dict], fields: list[dict] | None = None) -> None:
        self._issue_types = issue_types
        self._fields = fields or []
        self.created_issues: list[dict] = []
        self.created_links: list[tuple[str, str, str]] = []
        self._next_num = 1

    def get_issue_types(self) -> list[dict]:
        return self._issue_types

    def get_fields(self) -> list[dict]:
        return self._fields

    def create_issue(self, fields: dict) -> str:
        key = f"ESK-{self._next_num}"
        self._next_num += 1
        self.created_issues.append({"key": key, "fields": fields})
        return key

    def create_issue_link(self, link_type: str, outward_key: str, inward_key: str) -> None:
        self.created_links.append((link_type, outward_key, inward_key))


class _FakeResponse:
    """Имитирует объект, который возвращает urllib.request.urlopen -- context
    manager с .read(), для проверки JiraClient._request через фейковый opener."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc_info) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


class _FlakyOpener:
    """Фейковый opener для JiraClient(..., opener=...) -- кидает
    ConnectionResetError на первых `fail_times` вызовах, затем отдаёт
    успешный ответ. Используется только в --selftest, для проверки retry
    в _request() без обращения к сети."""

    def __init__(self, fail_times: int, response_body: bytes = b'{"key": "TPT-999"}') -> None:
        self.fail_times = fail_times
        self.response_body = response_body
        self.calls = 0

    def __call__(self, req: urllib.request.Request) -> _FakeResponse:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise ConnectionResetError("[Errno 104] Connection reset by peer (симуляция для --selftest)")
        return _FakeResponse(self.response_body)


def load_schema_fixture(path: Path) -> tuple[list[dict], list[dict]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("issueTypes", []), data.get("fields", [])


# ---------------------------------------------------------------------------
# Построение плана экспорта -- чистая функция, без обращений к API.
# ---------------------------------------------------------------------------


@dataclass
class PlannedIssue:
    placeholder_id: str  # наш ID (WBS-x.y / T-x.y.z / "EPIC") до создания реального ключа
    issue_type_name: str
    summary: str
    description: str
    labels: list[str] = field(default_factory=list)
    sprint_name: str | None = None
    parent_placeholder: str | None = None  # Subtask.parent или Issue.parent/Epic Link
    is_epic_child_issue: bool = False  # True для WBS-Issue -- родитель через Epic Link/parent, не Subtask.parent


@dataclass
class PlannedLink:
    link_type: str
    outward_id: str  # placeholder_id, несёт исходящий смысл ("blocks")
    inward_id: str  # placeholder_id, несёт входящий смысл ("is blocked by")


@dataclass
class ExportPlan:
    epic: PlannedIssue
    issues: list[PlannedIssue]  # WBS-issues (+ Task-issues в flat-режиме)
    subtasks: list[PlannedIssue]  # Task-subtasks (пусто в flat-режиме)
    links: list[PlannedLink]
    skipped_links: list[str]  # человекочитаемые причины пропуска (битые ссылки)
    flat_fallback: bool


def render_epic_description(plan: dict) -> str:
    c = plan["charter"]
    header_lines = [
        f"Заказчик: {c['client']}",
        f"Цель: {c['objective']}",
        f"Дата начала: {c['start_date']}",
        f"Дата запуска в эксплуатацию: {c['target_launch_date']}",
        "",
        c["target_launch_date_definition"],
        "",
    ]
    integration_ids = integration_task_ids(plan)
    id_to_name = build_id_to_name(plan, collapse_ids=integration_ids)
    parts = [
        "\n".join(header_lines),
        render_risks(plan, id_to_name),
        render_deliverables(plan, integration_ids),
    ]
    return "\n".join(parts).rstrip() + "\n"


def render_task_description(t: dict) -> str:
    lines: list[str] = []
    interview = t.get("interview_checklist") or []
    verification = t.get("verification_checklist") or []
    if interview:
        lines.append("Interview Checklist:")
        lines.extend(f"- {q}" for q in interview)
    if verification:
        if lines:
            lines.append("")
        lines.append("Verification Checklist:")
        lines.extend(f"- {q}" for q in verification)
    if not lines:
        return "(нет Interview/Verification Checklist для этой Task)"
    return "\n".join(lines)


def build_dependency_links(plan: dict, known_placeholder_ids: set[str]) -> tuple[list[PlannedLink], list[str]]:
    """depends_on -> Blocks (зависимость blocks зависимую Task).
    used_by -> Blocks в обратную сторону, только если пара ещё не покрыта
    depends_on с другой стороны (used_by часто зеркалит depends_on --
    sprint-mapping-rules.md называет его "вторичной, информативной ссылкой",
    не альтернативным графом; дублировать связь в обе стороны означало бы
    создать два Issue Link на одну и ту же пару). used_by иногда указывает
    на WBS ID (агрегатор), а не Task -- такого зеркала в depends_on нет, и
    для него связь создаётся."""
    all_tasks = flatten_tasks(plan)
    covered_pairs: set[frozenset] = set()
    links: list[PlannedLink] = []
    skipped: list[str] = []

    for t in all_tasks:
        for dep in t.get("depends_on") or []:
            if dep not in known_placeholder_ids or t["id"] not in known_placeholder_ids:
                skipped.append(f"{t['id']}.depends_on -> {dep!r}: ссылается на несуществующий в плане ID")
                continue
            links.append(PlannedLink(LINK_TYPE_BLOCKS, outward_id=dep, inward_id=t["id"]))
            covered_pairs.add(frozenset((dep, t["id"])))

    for t in all_tasks:
        for target in t.get("used_by") or []:
            pair = frozenset((t["id"], target))
            if pair in covered_pairs:
                continue
            if target not in known_placeholder_ids or t["id"] not in known_placeholder_ids:
                skipped.append(f"{t['id']}.used_by -> {target!r}: ссылается на несуществующий в плане ID")
                continue
            links.append(PlannedLink(LINK_TYPE_BLOCKS, outward_id=t["id"], inward_id=target))
            covered_pairs.add(pair)

    return links, skipped


def build_export_plan(
    plan: dict,
    schema: ProjectSchema,
    flat_fallback: bool,
    flat_child_link_type: str = DEFAULT_FLAT_CHILD_LINK_TYPE,
) -> ExportPlan:
    epic = PlannedIssue(
        placeholder_id=EPIC_PLACEHOLDER_ID,
        issue_type_name=schema.epic_type["name"],
        summary=plan["charter"]["project_name"],
        description=render_epic_description(plan),
    )

    issues: list[PlannedIssue] = []
    subtasks: list[PlannedIssue] = []
    extra_links: list[PlannedLink] = []
    task_sprint = plan.get("sprint_plan", {}).get("task_sprint", {})
    sprint_by_number = {s["sprint"]: s["name"] for s in plan.get("sprint_plan", {}).get("sprints", [])}

    for m in plan.get("milestones", []):
        label = m["id"]
        for wbs in m.get("wbs", []):
            wbs_issue = PlannedIssue(
                placeholder_id=wbs["id"],
                issue_type_name=schema.task_type["name"],
                summary=wbs["name"],
                description=wbs.get("description") or "",
                labels=[label],
                parent_placeholder=EPIC_PLACEHOLDER_ID,
                is_epic_child_issue=True,
            )
            issues.append(wbs_issue)

            for t in wbs.get("tasks", []):
                sprint_number = task_sprint.get(t["id"])
                sprint_name = sprint_by_number.get(sprint_number)
                summary = t["name"]
                description = render_task_description(t)

                if flat_fallback:
                    issues.append(
                        PlannedIssue(
                            placeholder_id=t["id"],
                            issue_type_name=schema.task_type["name"],
                            summary=summary,
                            description=description,
                            labels=[label],
                            sprint_name=sprint_name,
                        )
                    )
                    extra_links.append(PlannedLink(flat_child_link_type, outward_id=t["id"], inward_id=wbs["id"]))
                else:
                    subtasks.append(
                        PlannedIssue(
                            placeholder_id=t["id"],
                            issue_type_name=schema.subtask_type["name"],
                            summary=summary,
                            description=description,
                            labels=[label],
                            sprint_name=sprint_name,
                            parent_placeholder=wbs["id"],
                        )
                    )

    known_ids = {EPIC_PLACEHOLDER_ID} | {i.placeholder_id for i in issues} | {s.placeholder_id for s in subtasks}
    dep_links, skipped = build_dependency_links(plan, known_ids)

    return ExportPlan(
        epic=epic,
        issues=issues,
        subtasks=subtasks,
        links=extra_links + dep_links,
        skipped_links=skipped,
        flat_fallback=flat_fallback,
    )


# ---------------------------------------------------------------------------
# Dry-run отчёт -- только печать, ни одного вызова на запись.
# ---------------------------------------------------------------------------


def format_dry_run_report(export_plan: ExportPlan, schema: ProjectSchema, project_key: str) -> str:
    lines = ["=== Jira-экспорт (Этап 8) -- DRY-RUN, вызовов на запись не было ===", ""]
    lines.append(f"Проект: {project_key}")
    lines.append(
        f"issuetypes: Epic={schema.epic_type['name'] if schema.epic_type else '—'}, "
        f"Task={schema.task_type['name'] if schema.task_type else '—'}, "
        f"Subtask={schema.subtask_type['name'] if schema.subtask_type else 'недоступен'}"
    )
    lines.append(
        f"Sprint field: {schema.sprint_field_id or 'не найден (Sprint не будет проставлен)'}; "
        f"Epic Link field: {schema.epic_link_field_id or 'не найден -- используется fields.parent'}"
    )
    lines.append(f"Режим: {'ПЛОСКАЯ структура (--allow-flat-fallback)' if export_plan.flat_fallback else 'Subtask (стандартный)'}")
    lines.append("")

    lines.append(f"Было бы создано: 1 Epic, {len(export_plan.issues)} Issue, "
                  f"{len(export_plan.subtasks)} Subtask, {len(export_plan.links)} Issue Link")
    lines.append("")

    e = export_plan.epic
    lines.append(f"[Epic] {e.placeholder_id}  \"{e.summary}\"")
    lines.append("  description:")
    lines.extend(f"    {ln}" for ln in e.description.splitlines())
    lines.append("")

    lines.append(f"-- Issue ({len(export_plan.issues)}) --")
    for i in export_plan.issues:
        parent_note = f"  parent={i.parent_placeholder}" if i.parent_placeholder else ""
        sprint_note = f"  sprint={i.sprint_name!r}" if i.sprint_name else ""
        lines.append(f"  {i.placeholder_id}  [{i.issue_type_name}]  \"{i.summary}\"  labels={i.labels}{parent_note}{sprint_note}")
    lines.append("")

    if export_plan.subtasks:
        lines.append(f"-- Subtask ({len(export_plan.subtasks)}) --")
        for s in export_plan.subtasks:
            sprint_note = f"  sprint={s.sprint_name!r}" if s.sprint_name else ""
            lines.append(f"  {s.placeholder_id}  [{s.issue_type_name}]  \"{s.summary}\"  parent={s.parent_placeholder}  labels={s.labels}{sprint_note}")
        lines.append("")

    lines.append(f"-- Issue Link ({len(export_plan.links)}) --")
    for lnk in export_plan.links:
        lines.append(f"  {lnk.outward_id}  --[{lnk.link_type}]-->  {lnk.inward_id}")
    lines.append("")

    if export_plan.skipped_links:
        lines.append(f"-- Пропущенные связи ({len(export_plan.skipped_links)}) -- не потеряны молча, требуют внимания консультанта --")
        for msg in export_plan.skipped_links:
            lines.append(f"  ! {msg}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Реальное создание -- только --execute (+ --confirm).
# ---------------------------------------------------------------------------


def issue_description_with_sprint(planned: PlannedIssue) -> str:
    """Имя спринта -- первой строкой в description (не в нативном Jira Sprint
    field -- см. docstring модуля, "Известное ограничение")."""
    if not planned.sprint_name:
        return planned.description
    return f"Sprint: {planned.sprint_name}\n\n{planned.description}"


def text_to_adf(text: str) -> dict:
    """Jira Cloud API v3 принимает description только в Atlassian Document
    Format (ADF), не голой строкой. Каждая строка исходного текста -- отдельный
    параграф; пустая строка -- пустой параграф (сохраняет исходные пропуски).
    Markdown-таблицы (риск-секция Epic из render_risks) не разбираются в
    настоящую ADF-таблицу -- остаются построчным текстом с '|' -- см.
    CHANGELOG.md."""
    lines = text.split("\n")
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": line}]} if line else {"type": "paragraph"}
            for line in lines
        ],
    }


class ExecutionNotConfirmed(RuntimeError):
    """--execute был передан без --confirm, и подтверждение не было получено
    (ни явным флагом, ни интерактивным вводом) -- создание не выполняется."""


def confirm_execution(
    project_key: str,
    export_plan: ExportPlan,
    already_confirmed: bool,
    isatty: bool,
    input_fn=input,
) -> None:
    """Явное подтверждение человеком перед реальным созданием issues.
    Поднимает ExecutionNotConfirmed, если подтверждения нет и неоткуда его
    интерактивно получить -- --execute никогда не выполняется по умолчанию."""
    if already_confirmed:
        return
    if not isatty:
        raise ExecutionNotConfirmed(
            "--execute требует --confirm (явное подтверждение человеком) в неинтерактивном режиме"
        )
    n_total = 1 + len(export_plan.issues) + len(export_plan.subtasks)
    answer = input_fn(
        f"Будет создано в проекте {project_key}: 1 Epic, {len(export_plan.issues)} Issue, "
        f"{len(export_plan.subtasks)} Subtask, {len(export_plan.links)} Issue Link "
        f"(итого {n_total} issue). Подтвердить создание? [yes/no]: "
    )
    if answer.strip().lower() not in ("yes", "y", "да"):
        raise ExecutionNotConfirmed("подтверждение не получено (ответ отличен от yes/y/да)")


def _persist_state(state_path: Path | None, key_by_placeholder: dict[str, str]) -> None:
    """Пишет весь key_by_placeholder на диск после каждого успешного
    create_issue -- переживает обрыв сети (инцидент на TPT потребовал
    восстанавливать этот маппинг парсингом текстового лога вручную).
    Перезаписывает файл целиком: объём (десятки-сотни записей на реальный
    план) не оправдывает append-only формат."""
    if state_path is None:
        return
    state_path.write_text(
        json.dumps(key_by_placeholder, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def execute_export(
    client,
    export_plan: ExportPlan,
    project_key: str,
    verbose: bool = True,
    state_path: Path | None = None,
) -> dict[str, str]:
    def log(msg: str) -> None:
        if verbose:
            print(msg)

    key_by_placeholder: dict[str, str] = {}

    epic = export_plan.epic
    epic_fields = {
        "project": {"key": project_key},
        "issuetype": {"name": epic.issue_type_name},
        "summary": epic.summary,
        "description": text_to_adf(epic.description),
    }
    epic_key = client.create_issue(epic_fields)
    key_by_placeholder[epic.placeholder_id] = epic_key
    _persist_state(state_path, key_by_placeholder)
    log(f"Создан Epic: {epic_key}")

    for issue in export_plan.issues:
        fields: dict = {
            "project": {"key": project_key},
            "issuetype": {"name": issue.issue_type_name},
            "summary": issue.summary,
            "description": text_to_adf(issue_description_with_sprint(issue)),
            "labels": issue.labels,
        }
        if issue.parent_placeholder and issue.is_epic_child_issue:
            fields["parent"] = {"key": key_by_placeholder[issue.parent_placeholder]}
        key = client.create_issue(fields)
        key_by_placeholder[issue.placeholder_id] = key
        _persist_state(state_path, key_by_placeholder)
        log(f"Создан Issue: {key}  ({issue.placeholder_id})")

    for sub in export_plan.subtasks:
        parent_key = key_by_placeholder[sub.parent_placeholder]
        fields = {
            "project": {"key": project_key},
            "issuetype": {"name": sub.issue_type_name},
            "summary": sub.summary,
            "description": text_to_adf(issue_description_with_sprint(sub)),
            "labels": sub.labels,
            "parent": {"key": parent_key},
        }
        key = client.create_issue(fields)
        key_by_placeholder[sub.placeholder_id] = key
        _persist_state(state_path, key_by_placeholder)
        log(f"Создан Subtask: {key}  ({sub.placeholder_id})")

    for lnk in export_plan.links:
        outward_key = key_by_placeholder.get(lnk.outward_id)
        inward_key = key_by_placeholder.get(lnk.inward_id)
        if not outward_key or not inward_key:
            log(f"  ! Пропущена связь {lnk.outward_id}->{lnk.inward_id}: один из ключей не создан")
            continue
        client.create_issue_link(lnk.link_type, outward_key, inward_key)
        log(f"Создана связь [{lnk.link_type}]: {outward_key} -> {inward_key}")

    return key_by_placeholder


# ---------------------------------------------------------------------------
# Self-test -- полностью офлайн, через FakeJiraClient и фикстуры схемы.
# ---------------------------------------------------------------------------


def _load_client_abc_merged_plan() -> dict:
    path = AGENT_DIR / "examples" / "client-abc.merged-plan.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _company_managed_issue_types() -> list[dict]:
    return [
        {"id": "10001", "name": "Task", "subtask": False},
        {"id": "10002", "name": "Epic", "subtask": False},
        {"id": "10003", "name": "Sub-task", "subtask": True},
        {"id": "10004", "name": "Bug", "subtask": False},
    ]


def _team_managed_issue_types_no_subtask() -> list[dict]:
    return [
        {"id": "10101", "name": "Task", "subtask": False},
        {"id": "10102", "name": "Epic", "subtask": False},
    ]


def _fields_with_sprint_and_epic_link() -> list[dict]:
    return [
        {"id": "customfield_10020", "name": "Sprint"},
        {"id": "customfield_10014", "name": "Epic Link"},
        {"id": "summary", "name": "Summary"},
    ]


def run_selftest() -> None:
    plan = _load_client_abc_merged_plan()
    report = validate_plan(plan)
    if report.findings:
        print(f"[selftest] план содержит {len(report.findings)} находок(и) валидатора (ожидаемо для этого демо-плана)")

    # --- 1. Обычный (company-managed) проект -- Subtask доступен. ---
    schema = build_project_schema(_company_managed_issue_types(), _fields_with_sprint_and_epic_link())
    assert schema.epic_type and schema.epic_type["name"] == "Epic"
    assert schema.task_type and schema.task_type["name"] == "Task"
    assert schema.subtask_type and schema.subtask_type["name"] == "Sub-task"
    assert schema.sprint_field_id == "customfield_10020"
    assert schema.epic_link_field_id == "customfield_10014"
    flat = require_subtask_or_flat_confirmation(schema, allow_flat_fallback=False)
    assert flat is False
    print("[selftest] company-managed проект: Subtask найден, fallback не требуется -- OK")

    export_plan = build_export_plan(plan, schema, flat_fallback=flat)
    all_tasks = flatten_tasks(plan)
    all_wbs = [wbs for m in plan["milestones"] for wbs in m["wbs"]]
    assert len(export_plan.issues) == len(all_wbs), (len(export_plan.issues), len(all_wbs))
    assert len(export_plan.subtasks) == len(all_tasks), (len(export_plan.subtasks), len(all_tasks))
    assert all(i.issue_type_name == "Task" for i in export_plan.issues)
    assert all(s.issue_type_name == "Sub-task" for s in export_plan.subtasks)
    assert all(i.is_epic_child_issue and i.parent_placeholder == "EPIC" for i in export_plan.issues)
    print(f"[selftest] маппинг Subtask-режима: {len(export_plan.issues)} Issue (WBS), {len(export_plan.subtasks)} Subtask (Task) -- OK")

    # Labels = Milestone ID.
    for m in plan["milestones"]:
        wbs_ids = {wbs["id"] for wbs in m["wbs"]}
        task_ids = {t["id"] for wbs in m["wbs"] for t in wbs["tasks"]}
        for i in export_plan.issues:
            if i.placeholder_id in wbs_ids:
                assert i.labels == [m["id"]], (i.placeholder_id, i.labels)
        for s in export_plan.subtasks:
            if s.placeholder_id in task_ids:
                assert s.labels == [m["id"]], (s.placeholder_id, s.labels)
    print("[selftest] labels на Issue/Subtask = Milestone ID -- OK")

    # Sprint = имя спринта (не голый номер).
    named_subtasks = [s for s in export_plan.subtasks if s.sprint_name]
    assert named_subtasks, "ни у одной Subtask нет sprint_name -- ветка не проверена"
    assert all(s.sprint_name.startswith("Спринт ") for s in named_subtasks), [s.sprint_name for s in named_subtasks]
    hypercare = [s for s in named_subtasks if ", Гиперподдержка)" in s.sprint_name]
    assert hypercare, "метка гиперподдержки не найдена ни у одной Subtask -- ветка не проверена"
    print(f"[selftest] Sprint у Subtask -- имя спринта (в т.ч. метка гиперподдержки у {hypercare[0].placeholder_id}) -- OK")

    # Epic description -- риски очищены через clean_business_text (переиспользован
    # render_risks, не переизобретён), интеграции схлопнуты (переиспользован render_deliverables).
    assert "WBS-2.1)" not in export_plan.epic.description and "(WBS-2.1)" not in export_plan.epic.description
    assert "interview_checklist" not in export_plan.epic.description
    assert plan["charter"]["objective"] in export_plan.epic.description
    print("[selftest] description Epic содержит очищенные риски + deliverables (переиспользован Этап 7.5) -- OK")

    # Известная утечка в client-abc.merged-plan.json (Этап 7.6 demo): T-4.2.1.used_by
    # ссылается на исключённую T-4.2.2 -- не должна тихо потеряться, а должна попасть
    # в skipped_links.
    assert any("T-4.2.2" in msg for msg in export_plan.skipped_links), export_plan.skipped_links
    print(f"[selftest] битая ссылка T-4.2.1.used_by->T-4.2.2 (следствие исключения в Этапе 7.6) -- в skipped_links, не потеряна -- OK")

    # --- 2. Team-managed проект без Subtask -- без флага должен остановиться. ---
    schema_no_sub = build_project_schema(_team_managed_issue_types_no_subtask(), fields_raw=None)
    assert schema_no_sub.subtask_type is None
    try:
        require_subtask_or_flat_confirmation(schema_no_sub, allow_flat_fallback=False)
    except SubtaskUnavailableError:
        print("[selftest] team-managed проект без Subtask, без --allow-flat-fallback: остановлено явной ошибкой -- OK")
    else:
        raise AssertionError("отсутствие Subtask должно останавливать экспорт без --allow-flat-fallback")

    # --- 3. Тот же проект, но с явным --allow-flat-fallback -- плоская структура. ---
    flat2 = require_subtask_or_flat_confirmation(schema_no_sub, allow_flat_fallback=True)
    assert flat2 is True
    export_plan_flat = build_export_plan(plan, schema_no_sub, flat_fallback=flat2)
    assert not export_plan_flat.subtasks, "в плоском режиме не должно быть Subtask"
    assert len(export_plan_flat.issues) == len(all_wbs) + len(all_tasks), (
        len(export_plan_flat.issues), len(all_wbs), len(all_tasks)
    )
    assert all(i.issue_type_name == schema_no_sub.task_type["name"] for i in export_plan_flat.issues)
    child_links = [lnk for lnk in export_plan_flat.links if lnk.link_type == DEFAULT_FLAT_CHILD_LINK_TYPE]
    assert len(child_links) == len(all_tasks), (len(child_links), len(all_tasks))
    print(
        f"[selftest] плоский fallback (--allow-flat-fallback): {len(export_plan_flat.issues)} Issue "
        f"(WBS+Task), 0 Subtask, {len(child_links)} связей {DEFAULT_FLAT_CHILD_LINK_TYPE!r} WBS<->Task -- OK"
    )

    # --- 4. dry-run отчёт -- читаемый текст, без падений. ---
    report_text = format_dry_run_report(export_plan, schema, project_key="ESK")
    assert "DRY-RUN" in report_text
    assert f"{len(export_plan.issues)} Issue" in report_text
    print("[selftest] dry-run отчёт формируется без ошибок -- OK")

    # --- 4a. text_to_adf -- валидный ADF на многострочном input (пустые строки + risk-таблица). ---
    sample_multiline = (
        "Заказчик: ABC\n\n"
        "| Риск | Затрагивает |\n"
        "|---|---|\n"
        "| Версия ERP не указана | Подготовка |\n"
    )
    adf = text_to_adf(sample_multiline)
    assert adf["type"] == "doc" and adf["version"] == 1
    assert all(p["type"] == "paragraph" for p in adf["content"])
    non_empty = [p for p in adf["content"] if "content" in p]
    empty = [p for p in adf["content"] if "content" not in p]
    assert any(p["content"][0]["text"] == "Заказчик: ABC" for p in non_empty)
    assert any(p["content"][0]["text"] == "| Риск | Затрагивает |" for p in non_empty), (
        "risk-таблица должна остаться построчным текстом внутри параграфов (не ADF-таблицей)"
    )
    assert empty, "пустая строка должна давать параграф без content, а не пропадать"
    print("[selftest] text_to_adf: валидный ADF-документ на многострочном input (пустые строки + risk-таблица построчно) -- OK")

    # --- 5. execute -- через FakeJiraClient; счётчики совпадают с dry-run. ---
    fake = FakeJiraClient(_company_managed_issue_types(), _fields_with_sprint_and_epic_link())
    key_by_placeholder = execute_export(fake, export_plan, project_key="ESK", verbose=False)
    assert len(fake.created_issues) == 1 + len(export_plan.issues) + len(export_plan.subtasks), (
        len(fake.created_issues), 1, len(export_plan.issues), len(export_plan.subtasks)
    )
    assert len(fake.created_links) == len(export_plan.links)
    assert key_by_placeholder["EPIC"] == "ESK-1"
    wbs_issue = next(i for i in export_plan.issues)
    assert key_by_placeholder[wbs_issue.placeholder_id].startswith("ESK-")
    print(
        f"[selftest] execute (FakeJiraClient): {len(fake.created_issues)} issue создано "
        f"(Epic+Issue+Subtask), {len(fake.created_links)} связей -- совпадает с dry-run -- OK"
    )

    # Sprint field: не пишется в customfield_... напрямую (нет провизии реальных
    # Sprint-сущностей за пределами этого скрипта) -- имя спринта должно быть
    # первой строкой description созданной Subtask.
    created_by_key = {i["key"]: i for i in fake.created_issues}
    subtask_with_sprint = next(s for s in export_plan.subtasks if s.sprint_name)
    created_subtask_key = key_by_placeholder[subtask_with_sprint.placeholder_id]
    created_fields = created_by_key[created_subtask_key]["fields"]
    description_adf = created_fields["description"]
    assert description_adf["type"] == "doc" and description_adf["version"] == 1, description_adf
    first_paragraph_text = description_adf["content"][0]["content"][0]["text"]
    assert first_paragraph_text == f"Sprint: {subtask_with_sprint.sprint_name}", first_paragraph_text
    assert "customfield_10020" not in created_fields, (
        "Sprint field id не должен подставляться в fields без реальных Sprint-сущностей -- см. docstring"
    )
    print("[selftest] Sprint пишется первой строкой description (в ADF) созданной Subtask, не в нативный customfield -- OK")

    # --- 6. Подтверждение перед --execute -- никогда не выполняется по умолчанию. ---
    try:
        confirm_execution("ESK", export_plan, already_confirmed=False, isatty=False)
    except ExecutionNotConfirmed:
        print("[selftest] confirm_execution: неинтерактивно и без --confirm -- отклонено -- OK")
    else:
        raise AssertionError("--execute без --confirm и без TTY должен быть отклонён")

    confirm_execution("ESK", export_plan, already_confirmed=True, isatty=False)  # не должно поднять исключение
    print("[selftest] confirm_execution: --confirm передан явно -- пропущено без запроса -- OK")

    try:
        confirm_execution("ESK", export_plan, already_confirmed=False, isatty=True, input_fn=lambda _: "no")
    except ExecutionNotConfirmed:
        print("[selftest] confirm_execution: интерактивный ответ 'no' -- отклонено -- OK")
    else:
        raise AssertionError("ответ 'no' на интерактивное подтверждение должен быть отклонён")

    confirm_execution("ESK", export_plan, already_confirmed=False, isatty=True, input_fn=lambda _: "yes")
    print("[selftest] confirm_execution: интерактивный ответ 'yes' -- подтверждено -- OK")

    # --- 7. retry с backoff в _request() на transient ConnectionResetError. ---
    # time.sleep подменяется на no-op -- иначе тест реально ждал бы 1+2+4=7с на
    # ветку исчерпания попыток, а корректность retry от этого не зависит.
    original_sleep = time.sleep
    time.sleep = lambda seconds: None
    try:
        flaky = _FlakyOpener(fail_times=2)
        client_retry = JiraClient("https://example.atlassian.net", "a@b.com", "token", "ESK", opener=flaky)
        key = client_retry.create_issue({"summary": "test"})
        assert key == "TPT-999", key
        assert flaky.calls == 3, flaky.calls  # 2 неудачные попытки + 1 успешная
        print(
            "[selftest] retry: ConnectionResetError на 1-й/2-й попытке, успех на 3-й -- "
            "issue создан один раз (не задублирован) -- OK"
        )

        exhausted = _FlakyOpener(fail_times=MAX_REQUEST_ATTEMPTS + 1)  # больше попыток, чем есть у клиента
        client_exhausted = JiraClient("https://example.atlassian.net", "a@b.com", "token", "ESK", opener=exhausted)
        try:
            client_exhausted.create_issue({"summary": "test"})
        except JiraApiError:
            print(
                f"[selftest] retry: исчерпание всех {MAX_REQUEST_ATTEMPTS} попыток -- "
                f"JiraApiError поднят наверх, не проглочен молча -- OK"
            )
        else:
            raise AssertionError("исчерпание retry-попыток должно поднимать JiraApiError, а не проходить молча")
        assert exhausted.calls == MAX_REQUEST_ATTEMPTS, exhausted.calls
    finally:
        time.sleep = original_sleep

    print("[selftest] Все проверки Jira-экспорта сработали корректно -- OK")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plan", type=Path, help="Путь к смерженному плану (Этап 7.6, JSON)")
    parser.add_argument("--jira-url", help="Базовый URL Jira (например https://mycompany.atlassian.net)")
    parser.add_argument("--project-key", help="Ключ целевого Jira-проекта (уже существующего)")
    parser.add_argument("--email", help="Email для Basic Auth (вместе с Jira API token)")
    parser.add_argument("--api-token", help="Jira API token")
    parser.add_argument(
        "--schema-fixture",
        type=Path,
        help="Офлайн JSON со схемой проекта (issueTypes/fields) вместо живого API -- для демо/тестов",
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
    parser.add_argument("--output", type=Path, help="Куда записать dry-run отчёт (по умолчанию -- stdout)")
    parser.add_argument(
        "--state-file",
        type=Path,
        help="Куда писать key_by_placeholder (наш ID -> реальный Jira-ключ) по мере --execute -- "
             "переживает обрыв сети, не требует парсинга лога вручную "
             "(по умолчанию: <plan>.jira-export-state.json рядом с --plan)",
    )
    parser.add_argument("--execute", action="store_true", help="Реально создавать issues в Jira (по умолчанию -- dry-run)")
    parser.add_argument("--confirm", action="store_true", help="Явное подтверждение плана человеком (обязательно вместе с --execute)")
    parser.add_argument("--selftest", action="store_true", help="Прогнать самопроверку офлайн (FakeJiraClient)")
    args = parser.parse_args()

    if args.selftest:
        run_selftest()
        return

    if not args.plan:
        parser.error("--plan обязателен (или используйте --selftest)")
    if not args.schema_fixture and not (args.jira_url and args.project_key and args.email and args.api_token):
        parser.error("нужен либо --schema-fixture, либо все из --jira-url/--project-key/--email/--api-token")

    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    report = validate_plan(plan)
    if report.findings:
        print(
            f"ПРЕДУПРЕЖДЕНИЕ: план не прошёл validate_plan.py начисто ({len(report.findings)} находок(и)) -- "
            f"экспорт продолжается, но рекомендуется сначала устранить находки (validate_plan.py --plan {args.plan})",
            file=sys.stderr,
        )

    if args.schema_fixture:
        issue_types_raw, fields_raw = load_schema_fixture(args.schema_fixture)
        client = None
    else:
        client = JiraClient(args.jira_url, args.email, args.api_token, args.project_key)
        issue_types_raw = client.get_issue_types()
        fields_raw = client.get_fields()

    schema = build_project_schema(issue_types_raw, fields_raw)

    try:
        flat_fallback = require_subtask_or_flat_confirmation(schema, args.allow_flat_fallback)
    except SubtaskUnavailableError as exc:
        print(f"ОСТАНОВЛЕНО: {exc}", file=sys.stderr)
        sys.exit(2)
    except JiraApiError as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        sys.exit(2)

    export_plan = build_export_plan(plan, schema, flat_fallback, args.flat_child_link_type)

    if not args.execute:
        report_text = format_dry_run_report(export_plan, schema, args.project_key or "(из --schema-fixture)")
        if args.output:
            args.output.write_text(report_text, encoding="utf-8")
            print(f"Записано: {args.output}", file=sys.stderr)
        else:
            print(report_text)
        return

    if client is None:
        parser.error("--execute требует живого проекта (--jira-url/--project-key/--email/--api-token), не --schema-fixture")

    try:
        confirm_execution(args.project_key, export_plan, args.confirm, sys.stdin.isatty())
    except ExecutionNotConfirmed as exc:
        print(f"Отменено: {exc}", file=sys.stderr)
        sys.exit(1)

    state_path = args.state_file or args.plan.with_name(args.plan.stem + ".jira-export-state.json")
    print(f"key_by_placeholder пишется по ходу создания в: {state_path}", file=sys.stderr)
    execute_export(client, export_plan, args.project_key, state_path=state_path)


if __name__ == "__main__":
    main()
