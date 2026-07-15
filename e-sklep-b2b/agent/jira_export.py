#!/usr/bin/env python3
"""Этап 8 — экспорт плана в существующий Jira-проект.

Вход: результат Этапа 6 (`assemble_plan.py`), провалидированный Этапом 7
(`validate_plan.py`) -- Этапы 7.5/7.6 (документ для согласования и приём
правок) удалены из пайплайна (см. CHANGELOG.md), план идёт в Jira-экспорт
как есть. Целевой Jira-проект уже существует (не создаётся этим скриптом).

Маппинг (docs/agent-development-plan.md, Этап 8):

    Наш уровень          Jira
    -------------------  ------------------------------------------------
    Весь план            1 Epic (summary = charter.project_name,
                          description = Описание + Цель + даты/заказчик +
                          Риски (ADF-таблица) + Критерии завершения этапов
                          (ADF-таблица))
    Milestone (M1-M9)     Label на каждой issue/subtask (M3, M6 и т.п.)
    WBS                   Issue, child Эпика -- summary = название WBS
    Task (наш)             Subtask под соответствующим WBS-Issue --
                          summary = название Task, description =
                          Interview/Verification checklist, Sprint = имя
                          спринта (sprint_plan.sprints[].name)
    depends_on/used_by    Issue Links (Blocks: "outward blocks inward")
    Риски (сработавшие)   Настоящая ADF-таблица (Риск / Затрагивает) в
                          description Эпика (не отдельные issue)
    Критерии завершения   Настоящая ADF-таблица (ID / Название / Описание):
                          строка Milestone (жирным), затем строки его WBS --
                          без строк Task (см. milestones/wbs в плане, не
                          verification_checklist задач)
    Гиперподдержка         Отдельный 2-й Epic (SUPPORT_EPIC_SUMMARY, по
                          умолчанию "Поддержка"), создаётся ВСЕГДА, без
                          флага и вне зависимости от плана -- WBS-9.3
                          (Гиперподдержка) удалён из schema/milestones_wbs.yaml
                          (см. CHANGELOG.md). Внутри -- ровно одна Task
                          (журнал поддержки), без Subtask/Sprint/timetracking;
                          не участвует в sprint-планировании/R-7/effort-
                          оценках/--create-sprints.

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

При `--create-sprints` (opt-in) это ограничение снимается для WBS-Issue:
после `execute_export()` и создания Sprint скрипт собирает по
`sprint_plan` реальные ключи WBS-Issue на каждый Sprint и привязывает их
через `POST /rest/agile/1.0/sprint/{id}/issue` (пакетами по
`MAX_ISSUES_PER_SPRINT_LINK_BATCH`, лимит Jira Agile API) -- это
устанавливает нативное поле Sprint напрямую, а не только текст в
description. Привязываются только WBS-Issue, не Subtask -- обнаружено
эмпирически на живом TPT: Jira Sub-task не хранит поле Sprint независимо
от родителя (POST возвращает 204, но customfield остаётся null), тот же
вызов на обычном Issue сработал сразу. Каждый WBS-Issue лежит ровно в
одном спринте по построению `schema/sprint_plan.yaml` (Этап 5) --
`build_wbs_sprint()` берёт этот спринт напрямую, без прежнего правила
"самый ранний из нескольких" (актуального для алгоритма, который
вычислял распределение, а не читал готовый шаблон). Без `--create-sprints`
поведение не меняется (текст в description остаётся единственным способом).

Риски в description Эпика -- настоящая ADF-таблица (`build_risks_adf_table`),
не markdown-текст: `clean_business_text()` и сбор `related_wbs` -> имена
(бывшие функции `generate_client_document.py`, Этап 7.5, перенесены сюда
после удаления этого этапа -- см. CHANGELOG.md) переиспользуются как есть,
но результат собирается в узлы `table`/`tableRow`/`tableCell`, а не в строку
с `|`. Ячейка "Риск" -- полноценный ADF-параграф, допускает форматирование.

Критерии завершения этапов в description Эпика -- тоже настоящая ADF-таблица
(`build_criteria_adf_table`), столбцы ID/Название/Описание: строка Milestone
(жирным), затем строки его WBS, без строк Task. Источник -- `milestones`/
`wbs` верхнего уровня плана (у них уже есть `id`/`name`/`description` из
`schema/milestones_wbs.yaml`), не агрегированный `verification_checklist` задач.

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
    python3 jira_export.py --plan plan.json \
        --jira-url https://mycompany.atlassian.net --project-key ESK \
        --email consultant@example.com --api-token *** [--execute --confirm]

    # офлайн-демо/тесты без живого Jira-проекта:
    python3 jira_export.py --plan plan.json \
        --schema-fixture examples/jira-project-schema.example.json

    python3 jira_export.py --selftest
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from validate_plan import flatten_tasks, validate_plan

AGENT_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Перенесено из generate_client_document.py (бывший Этап 7.5, удалён --
# см. CHANGELOG.md): очистка деловых формулировок risk-текстов и сборка
# читаемых имён id -> название для Риски/Критерии завершения в description
# Эпика. Логика не переизобретена -- перенесена как есть.
# ---------------------------------------------------------------------------

_PAREN_JARGON = re.compile(
    r"\s*\([^()]*(?:\bWBS-\d|\bT-\d+\.\d|\bM\d\b|agent/|\.md\b|\.yaml\b|\.json\b|"
    r"source\.url|condition|input-schema)[^()]*\)"
)


def clean_business_text(text: str) -> str:
    text = _PAREN_JARGON.sub("", text)
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"\s+([,.;:)])", r"\1", text)
    return text.strip()


INTEGRATION_PLACEHOLDER = "Настроить интеграцию [Компонент] согласно документации Comarch"


def integration_task_ids(plan: dict) -> set[str]:
    return {t["id"] for t in flatten_tasks(plan) if t.get("generated_from") == "T-6.4.2"}


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


def render_risks(plan: dict, id_to_name: dict[str, str]) -> str:
    lines = ["## Риски проекта", ""]
    risks = plan.get("risks") or []
    if not risks:
        lines.append("Для параметров этого проекта применимых рисков из реестра не выявлено.")
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

LINK_TYPE_BLOCKS = "Blocks"  # стандартный тип связи Jira (outward "blocks" / inward "is blocked by")
DEFAULT_FLAT_CHILD_LINK_TYPE = "Relates"  # стандартный тип, доступен в любом проекте по умолчанию

EPIC_PLACEHOLDER_ID = "EPIC"

EPIC_TYPE_NAMES = {"epic", "epik"}  # "epik" -- польская локализация Jira (напр. TPT)

# Гиперподдержка (WBS-9.3 удалён из schema/milestones_wbs.yaml, см.
# CHANGELOG.md) ведётся отдельным Epic, создаваемым ВСЕГДА при экспорте --
# без флага, независимо от конкретного плана. Локализуемые константы (не
# хардкодить язык внутри логики) -- переключить на другой язык (например
# "Wsparcie") означает поменять только эти строки, не код ниже.
SUPPORT_EPIC_PLACEHOLDER_ID = "SUPPORT_EPIC"
SUPPORT_LOG_TASK_PLACEHOLDER_ID = "SUPPORT_LOG_TASK"

# По языку плана (plan["meta"]["lang"], см. assemble_plan.py --lang, CHANGELOG
# v3.6) -- этот Epic не читается из schema/milestones_wbs{.lang}.yaml (создаётся
# ВСЕГДА, вне plan["milestones"]), поэтому локализуется отдельно от остального
# контента плана, тем же способом (словарь по lang), что и было предусмотрено
# исходным комментарием "Локализуемые константы" при введении --lang.
SUPPORT_EPIC_SUMMARY_BY_LANG = {
    "ru": "Поддержка",
    "ua": "Підтримка",
}
SUPPORT_LOG_TASK_SUMMARY_BY_LANG = {
    "ru": "Журнал поддержки",
    "ua": "Журнал підтримки",
}
SUPPORT_EPIC_DESCRIPTION_TEXT_BY_LANG = {
    "ru": (
        "Гиперподдержка после формального закрытия проекта ведётся здесь, "
        "отдельно от плана внедрения -- WBS/Task, sprint-план и оценки "
        "трудозатрат её не описывают. Единственная задача ниже -- журнал "
        "поддержки: сюда заносятся обращения и решённые проблемы за весь "
        "период поддержки, без привязки к конкретному спринту или трудозатратам."
    ),
    "ua": (
        "Гіперпідтримка після формального закриття проєкту ведеться тут, "
        "окремо від плану впровадження -- WBS/Task, sprint-план і оцінки "
        "трудовитрат її не описують. Єдине завдання нижче -- журнал "
        "підтримки: сюди заносяться звернення та вирішені проблеми за весь "
        "період підтримки, без прив'язки до конкретного спринту чи трудовитрат."
    ),
}

# Backward-compat: значения по умолчанию (ru), на которые уже опирается
# существующий --selftest этого файла.
SUPPORT_EPIC_SUMMARY = SUPPORT_EPIC_SUMMARY_BY_LANG["ru"]
SUPPORT_LOG_TASK_SUMMARY = SUPPORT_LOG_TASK_SUMMARY_BY_LANG["ru"]
SUPPORT_EPIC_DESCRIPTION_TEXT = SUPPORT_EPIC_DESCRIPTION_TEXT_BY_LANG["ru"]

RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}
MAX_REQUEST_ATTEMPTS = 4  # 1 первая попытка + до 3 повторов
RETRY_BACKOFF_SECONDS = (1, 2, 4)  # пауза после попытки 1, 2, 3 (экспоненциально)


class JiraApiError(RuntimeError):
    pass


class SubtaskUnavailableError(RuntimeError):
    """Целевой проект не предоставляет issuetype Subtask на уровне схемы,
    и --allow-flat-fallback не передан -- решение явно за человеком."""


class BoardUnavailableError(RuntimeError):
    """--create-sprints: у проекта нет доски или ни одна не Scrum (не
    поддерживает спринты) -- скрипт не создаёт доску самостоятельно,
    решение явно за человеком (по аналогии с SubtaskUnavailableError)."""


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
# Доска с включёнными Sprint для --create-sprints -- обязательное
# предусловие перед созданием Sprint, по аналогии с
# require_subtask_or_flat_confirmation выше.
# ---------------------------------------------------------------------------


def require_sprint_capable_board(client, board_candidates: list[dict], project_key: str) -> dict:
    """Возвращает первую доску проекта, реально поддерживающую Sprint.

    Поле `type` из GET /rest/agile/1.0/board ненадёжно для этой проверки --
    team-managed проекты нередко репортят доску как "simple", даже когда
    Sprints у них включены (обнаружено на живом проекте TPT: type='simple',
    но GET .../board/{id}/sprint успешен и там уже есть спринт). Настоящая
    проверка -- реальный вызов client.board_supports_sprints(), а не чтение
    статичного поля схемы.

    Если досок нет или ни одна не поддерживает Sprint -- не включает функцию
    самостоятельно, а поднимает BoardUnavailableError с объяснением
    (--create-sprints не выполняется молча в обход)."""
    if not board_candidates:
        raise BoardUnavailableError(
            f"У проекта {project_key} не найдено ни одной доски (GET /rest/agile/1.0/board) -- "
            "--create-sprints требует существующую доску с включённым Sprint, скрипт её не создаёт."
        )
    for board in board_candidates:
        if client.board_supports_sprints(board["id"]):
            return board
    checked_types = ", ".join(sorted({(b.get("type") or "?") for b in board_candidates}))
    raise BoardUnavailableError(
        f"У проекта {project_key} есть доска(и) (типы: {checked_types}), но ни одна не поддерживает "
        "Sprint (GET /rest/agile/1.0/board/{id}/sprint отклонён как 'does not support sprints') -- "
        "--create-sprints требует доску с включённой функцией Sprint, скрипт её не включает."
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

    # --- --create-sprints (opt-in) -- Agile REST API, тот же retry из _request() ---

    def get_board_candidates(self) -> list[dict]:
        data = self._request("GET", f"/rest/agile/1.0/board?projectKeyOrId={self.project_key}")
        return data.get("values", [])

    def board_supports_sprints(self, board_id: int) -> bool:
        """Поле `type` доски ненадёжно (см. require_sprint_capable_board) --
        реальная проверка -- вызов списка спринтов доски; retry на
        transient-ошибках уже покрыт _request()."""
        try:
            self._request("GET", f"/rest/agile/1.0/board/{board_id}/sprint")
            return True
        except JiraApiError as exc:
            if "does not support sprints" in str(exc).lower():
                return False
            raise

    def create_sprint(
        self, board_id: int, name: str, start_date_iso: str, end_date_iso: str, goal: str | None = None
    ) -> dict:
        """Тот же риск дубля при retry после обрыва соединения, что и в
        create_issue выше -- см. комментарий там."""
        body = {"name": name, "startDate": start_date_iso, "endDate": end_date_iso, "originBoardId": board_id}
        if goal:
            body["goal"] = goal
        return self._request("POST", "/rest/agile/1.0/sprint", body)

    def add_issues_to_sprint(self, sprint_id: int, issue_keys: list[str]) -> None:
        """Привязка issue к спринту (POST /rest/agile/1.0/sprint/{id}/issue,
        не более MAX_ISSUES_PER_SPRINT_LINK_BATCH ключей за вызов -- лимит
        Jira Agile API; батчинг делает вызывающий код). В отличие от
        create_issue/create_issue_link, эта операция идемпотентна на стороне
        Jira -- повторное добавление уже привязанного issue не создаёт
        дубля, только переустанавливает то же членство в спринте, поэтому
        retry в _request() здесь безопасен без дополнительных оговорок."""
        self._request("POST", f"/rest/agile/1.0/sprint/{sprint_id}/issue", {"issues": issue_keys})


class FakeJiraClient:
    """Для --selftest и разработки без живого Jira-проекта -- те же методы,
    что JiraClient, но в памяти; create_issue выдаёт синтетические ключи."""

    def __init__(
        self,
        issue_types: list[dict],
        fields: list[dict] | None = None,
        board_candidates: list[dict] | None = None,
        sprint_capable_board_ids: set[int] | None = None,
    ) -> None:
        self._issue_types = issue_types
        self._fields = fields or []
        self._board_candidates = board_candidates or []
        self._sprint_capable_board_ids = set(sprint_capable_board_ids or [])
        self.created_issues: list[dict] = []
        self.created_links: list[tuple[str, str, str]] = []
        self.created_sprints: list[dict] = []
        self.sprint_issue_batches: list[tuple[int, list[str]]] = []
        self._next_num = 1
        self._next_sprint_id = 1

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

    def get_board_candidates(self) -> list[dict]:
        return self._board_candidates

    def board_supports_sprints(self, board_id: int) -> bool:
        return board_id in self._sprint_capable_board_ids

    def create_sprint(
        self, board_id: int, name: str, start_date_iso: str, end_date_iso: str, goal: str | None = None
    ) -> dict:
        sprint = {
            "id": self._next_sprint_id,
            "originBoardId": board_id,
            "name": name,
            "startDate": start_date_iso,
            "endDate": end_date_iso,
        }
        if goal:
            sprint["goal"] = goal
        self._next_sprint_id += 1
        self.created_sprints.append(sprint)
        return sprint

    def add_issues_to_sprint(self, sprint_id: int, issue_keys: list[str]) -> None:
        self.sprint_issue_batches.append((sprint_id, list(issue_keys)))


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
    effort_hours: float | None = None  # timetracking.originalEstimate; None -- в плане нет оценки (WBS, custom Task)
    description_adf: dict | None = None  # только у Epic: настоящий ADF (таблицы риск/критерии), не текст --
    # `description` остаётся человекочитаемым текстом для dry-run отчёта; при `--execute` описание Epic
    # берётся из description_adf напрямую (см. execute_export), в text_to_adf() не проходит


@dataclass
class PlannedLink:
    link_type: str
    outward_id: str  # placeholder_id, несёт исходящий смысл ("blocks")
    inward_id: str  # placeholder_id, несёт входящий смысл ("is blocked by")


@dataclass
class ExportPlan:
    epic: PlannedIssue
    support_epic: PlannedIssue  # Epic "Поддержка" -- создаётся всегда, вне plan["milestones"]
    support_task: PlannedIssue  # единственная Task внутри support_epic (журнал поддержки)
    issues: list[PlannedIssue]  # WBS-issues (+ Task-issues в flat-режиме)
    subtasks: list[PlannedIssue]  # Task-subtasks (пусто в flat-режиме)
    links: list[PlannedLink]
    skipped_links: list[str]  # человекочитаемые причины пропуска (битые ссылки)
    flat_fallback: bool


@dataclass
class PlannedSprint:
    number: int  # sprint_plan.sprints[].sprint -- матчит sprint_plan.task_sprint с реальным Sprint id после создания
    name: str  # короткое имя для поля Jira `name` (лимит API -- см. JIRA_SPRINT_NAME_MAX_LENGTH)
    goal: str  # полное имя из sprint_plan.sprints[].name (с датами), без изменений -- в поле Jira `goal`
    start_date: str  # YYYY-MM-DD
    end_date: str  # YYYY-MM-DD


SPRINT_NAME_DATE_RANGE_RE = re.compile(r"\((\d{4}-\d{2}-\d{2})–(\d{4}-\d{2}-\d{2})(?:, ([^)]+))?\)")

JIRA_SPRINT_NAME_MAX_LENGTH = 30  # обнаружено на живом TPT: HTTP 400 "Długość nazwy sprintu musi być mniejsza niż 30 zn."


def parse_sprint_dates_and_label(sprint_name: str) -> tuple[str, str, str | None]:
    """Извлекает даты начала/конца (и опциональную метку вроде "Гиперподдержка")
    из уже готового имени спринта (agent/assemble_plan.py, sprint_name():
    "Спринт N (start–end[, метка])") -- не пересчитывает их заново из
    sprint_length_weeks/start_date, чтобы не разойтись с тем, что уже
    зафиксировано в плане."""
    m = SPRINT_NAME_DATE_RANGE_RE.search(sprint_name)
    if not m:
        raise JiraApiError(f"Не удалось извлечь даты спринта из имени {sprint_name!r} -- неожиданный формат")
    return m.group(1), m.group(2), m.group(3)


def build_planned_sprints(plan: dict) -> list[PlannedSprint]:
    """Полное имя из плана (с датами) идёт в Jira `goal` без изменений --
    Jira `name` спринта ограничен JIRA_SPRINT_NAME_MAX_LENGTH символами
    (обнаружено на живом TPT: полное имя с датами это нарушает), поэтому
    для `name` строится короткая форма "Спринт N" (+ метка, если есть)."""
    planned = []
    for s in plan.get("sprint_plan", {}).get("sprints", []):
        full_name = s["name"]
        start_date, end_date, label = parse_sprint_dates_and_label(full_name)
        short_name = f"Спринт {s['sprint']}" + (f" ({label})" if label else "")
        if len(short_name) > JIRA_SPRINT_NAME_MAX_LENGTH:
            raise JiraApiError(
                f"Короткое имя Sprint {short_name!r} ({len(short_name)} симв.) всё равно превышает лимит "
                f"Jira ({JIRA_SPRINT_NAME_MAX_LENGTH}) -- нужна ручная правка меток в плане, не автоматическая обрезка"
            )
        planned.append(
            PlannedSprint(
                number=s["sprint"], name=short_name, goal=full_name, start_date=start_date, end_date=end_date
            )
        )
    return planned


MAX_ISSUES_PER_SPRINT_LINK_BATCH = 50  # лимит Jira Agile API за один вызов POST /sprint/{id}/issue


def build_wbs_sprint(plan: dict) -> dict[str, int]:
    """wbs_id -> sprint_number, только если все Task этого WBS оказались в
    одном и том же спринте. Каждый WBS шаблона лежит ровно в одном спринте
    по построению schema/sprint_plan.yaml (Этап 5) -- проверка ниже
    страхует на случай будущего отклонения от этого инварианта, а не
    описывает реально встречающийся сегодня случай."""
    task_sprint = plan.get("sprint_plan", {}).get("task_sprint", {})
    result: dict[str, int] = {}
    for m in plan.get("milestones", []):
        for wbs in m.get("wbs", []):
            sprints = {task_sprint[t["id"]] for t in wbs.get("tasks", []) if t["id"] in task_sprint}
            if len(sprints) == 1:
                result[wbs["id"]] = next(iter(sprints))
    return result


def build_sprint_wbs_ids(plan: dict) -> dict[int, list[str]]:
    """build_wbs_sprint() сгруппирован в обратную сторону (sprint_number ->
    [wbs_id, ...]) -- используется и для dry-run превью, и для реальной
    привязки WBS-Issue после создания issues/спринтов."""
    grouped: dict[int, list[str]] = {}
    for wbs_id, sprint_number in build_wbs_sprint(plan).items():
        grouped.setdefault(sprint_number, []).append(wbs_id)
    return grouped


def chunked(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def render_criteria_text(plan: dict) -> str:
    """Текстовый (не ADF) аналог build_criteria_adf_table -- используется
    только в dry-run отчёте для консультанта, читается в консоли. Одна
    таблица ID/Название/Описание: строка Milestone, затем строки его WBS,
    без строк Task."""
    lines = ["## Критерии завершения этапов", "", "| ID | Название | Описание |", "|---|---|---|"]
    for m in plan.get("milestones", []):
        lines.append(f"| **{m['id']}** | **{m['name']}** | {_table_cell_text(m.get('description'))} |")
        for wbs in m.get("wbs", []):
            lines.append(f"| {wbs['id']} | {wbs['name']} | {_table_cell_text(wbs.get('description'))} |")
    lines.append("")
    return "\n".join(lines)


def _table_cell_text(text: str | None) -> str:
    return " ".join((text or "").split()).replace("|", "/")


def render_epic_description(plan: dict) -> str:
    """Человекочитаемый текст -- используется только в dry-run отчёте.
    Реальное значение Jira description при --execute строится отдельно, как
    ADF (build_epic_description_adf), а не через эту строку/text_to_adf."""
    c = plan["charter"]
    header_lines = [f"Заказчик: {c['client']}"]
    if c.get("description"):
        header_lines.append(f"Описание: {c['description']}")
    header_lines += [
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
        render_criteria_text(plan),
    ]
    return "\n".join(parts).rstrip() + "\n"


# ---------------------------------------------------------------------------
# ADF (Atlassian Document Format) -- настоящие таблицы для description Эпика.
# Только Epic получает structured ADF напрямую (description_adf); обычные
# Issue/Subtask по-прежнему проходят через text_to_adf() построчно.
# ---------------------------------------------------------------------------


def _adf_text_paragraph(text: str | None, bold: bool = False) -> dict:
    text = text or ""
    if not text:
        return {"type": "paragraph"}
    node: dict = {"type": "text", "text": text}
    if bold:
        node["marks"] = [{"type": "strong"}]
    return {"type": "paragraph", "content": [node]}


def _adf_table_cell(text: str | None, header: bool = False, bold: bool = False) -> dict:
    return {
        "type": "tableHeader" if header else "tableCell",
        "attrs": {},
        "content": [_adf_text_paragraph(text, bold=bold)],
    }


def _adf_table_row(cells: list[str], header: bool = False, bold: bool = False) -> dict:
    return {"type": "tableRow", "content": [_adf_table_cell(c, header=header, bold=bold) for c in cells]}


def _adf_heading(text: str, level: int = 2) -> dict:
    return {"type": "heading", "attrs": {"level": level}, "content": [{"type": "text", "text": text}]}


def build_risks_adf_table(plan: dict, id_to_name: dict[str, str]) -> dict:
    """Настоящая ADF-таблица (Риск / Затрагивает), не markdown-текст внутри
    параграфов (закрывает известное ограничение из CHANGELOG v1.19). Ячейка
    "Риск" -- полноценный ADF-параграф (допускает форматирование), не голая
    строка. clean_business_text()/human_refs() определены выше в этом же
    файле (перенесены из удалённого generate_client_document.py, Этап 7.5)."""
    rows = [_adf_table_row(["Риск", "Затрагивает"], header=True)]
    risks = plan.get("risks") or []
    if not risks:
        rows.append(_adf_table_row(["Для параметров этого проекта применимых рисков из реестра не выявлено.", "—"]))
    else:
        for r in risks:
            risk_text = clean_business_text(" ".join((r.get("risk") or "").split()))
            affects = human_refs(r.get("related_wbs") or [], id_to_name)
            rows.append(_adf_table_row([risk_text, affects]))
    return {"type": "table", "attrs": {"isNumberColumnEnabled": False, "layout": "default"}, "content": rows}


def build_criteria_adf_table(plan: dict) -> dict:
    """Настоящая ADF-таблица ID/Название/Описание: строка Milestone (жирным),
    затем строки его WBS, следующий Milestone и т.д. -- без строк Task.
    Источник -- milestones/wbs верхнего уровня плана (id/name/description уже
    заданы в schema/milestones_wbs.yaml), не агрегированный
    verification_checklist задач."""
    rows = [_adf_table_row(["ID", "Название", "Описание"], header=True)]
    for m in plan.get("milestones", []):
        rows.append(_adf_table_row([m["id"], m["name"], _table_cell_text(m.get("description"))], bold=True))
        for wbs in m.get("wbs", []):
            rows.append(_adf_table_row([wbs["id"], wbs["name"], _table_cell_text(wbs.get("description"))]))
    return {"type": "table", "attrs": {"isNumberColumnEnabled": False, "layout": "default"}, "content": rows}


def build_epic_description_adf(plan: dict) -> dict:
    """Реальное значение Jira description Эпика при --execute (структурный
    ADF: параграфы шапки + настоящие таблицы Риски/Критерии), в отличие от
    render_epic_description() (плоский текст, только для dry-run отчёта)."""
    c = plan["charter"]
    integration_ids = integration_task_ids(plan)
    id_to_name = build_id_to_name(plan, collapse_ids=integration_ids)

    content: list[dict] = [_adf_text_paragraph(f"Заказчик: {c['client']}")]
    if c.get("description"):
        content.append(_adf_text_paragraph(f"Описание: {c['description']}"))
    content.extend(
        [
            _adf_text_paragraph(f"Цель: {c['objective']}"),
            _adf_text_paragraph(f"Дата начала: {c['start_date']}"),
            _adf_text_paragraph(f"Дата запуска в эксплуатацию: {c['target_launch_date']}"),
            {"type": "paragraph"},
            _adf_text_paragraph(c["target_launch_date_definition"]),
            _adf_heading("Риски проекта"),
            build_risks_adf_table(plan, id_to_name),
            _adf_heading("Критерии завершения этапов"),
            build_criteria_adf_table(plan),
        ]
    )
    return {"type": "doc", "version": 1, "content": content}


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


def build_support_epic_issues(schema: ProjectSchema, lang: str = "ru") -> tuple[PlannedIssue, PlannedIssue]:
    """Epic "Поддержка"/"Підтримка" + единственная Task внутри (журнал
    поддержки), создаются ВСЕГДА при экспорте -- без флага и независимо от
    конкретного плана (гиперподдержка после закрытия проекта не описывается
    WBS/Task шаблона, см. CHANGELOG.md). Issuetype -- те же schema.epic_type/
    task_type, что уже резолвит основной Epic (тот же паттерн локализации
    issuetype, см. resolve_issue_types/EPIC_TYPE_NAMES), description --
    тот же ADF-паттерн (paragraph), что и у основного Epic. Без Subtask
    (Task, не child Task), без Sprint (sprint_name не проставляется), без
    timetracking (effort_hours не проставляется) -- единственная задача не
    участвует в sprint-планировании/R-7/effort-оценках/--create-sprints,
    т.к. ни один из этих механизмов не читает ничего за пределами
    plan["milestones"]/plan["sprint_plan"], а этот Epic туда не входит.

    lang -- SUPPORT_EPIC_SUMMARY_BY_LANG и т.п. (см. --lang, CHANGELOG v3.6);
    build_export_plan() резолвит его из plan["meta"]["lang"]."""
    summary = SUPPORT_EPIC_SUMMARY_BY_LANG[lang]
    log_task_summary = SUPPORT_LOG_TASK_SUMMARY_BY_LANG[lang]
    description_text = SUPPORT_EPIC_DESCRIPTION_TEXT_BY_LANG[lang]
    epic = PlannedIssue(
        placeholder_id=SUPPORT_EPIC_PLACEHOLDER_ID,
        issue_type_name=schema.epic_type["name"],
        summary=summary,
        description=description_text,
        description_adf={"type": "doc", "version": 1, "content": [_adf_text_paragraph(description_text)]},
    )
    task = PlannedIssue(
        placeholder_id=SUPPORT_LOG_TASK_PLACEHOLDER_ID,
        issue_type_name=schema.task_type["name"],
        summary=log_task_summary,
        description=description_text,
        parent_placeholder=SUPPORT_EPIC_PLACEHOLDER_ID,
        is_epic_child_issue=True,
    )
    return epic, task


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
        description=render_epic_description(plan),  # текст -- только для dry-run отчёта
        description_adf=build_epic_description_adf(plan),  # реальный ADF -- для --execute
    )
    support_epic, support_task = build_support_epic_issues(schema, lang=plan.get("meta", {}).get("lang", "ru"))

    issues: list[PlannedIssue] = []
    subtasks: list[PlannedIssue] = []
    extra_links: list[PlannedLink] = []
    task_sprint = plan.get("sprint_plan", {}).get("task_sprint", {})
    sprint_by_number = {s["sprint"]: s["name"] for s in plan.get("sprint_plan", {}).get("sprints", [])}
    effort_estimates = plan.get("effort_estimates", {})

    for m in plan.get("milestones", []):
        label = m["id"]
        for wbs in m.get("wbs", []):
            # Агрегированной оценки трудозатрат на уровне WBS в плане нет (только
            # на уровне Task) -- timetracking для WBS-Issue не выдумывается.
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
                effort_hours = effort_estimates.get(t["id"], {}).get("hours")

                if flat_fallback:
                    issues.append(
                        PlannedIssue(
                            placeholder_id=t["id"],
                            issue_type_name=schema.task_type["name"],
                            summary=summary,
                            description=description,
                            labels=[label],
                            sprint_name=sprint_name,
                            effort_hours=effort_hours,
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
                            effort_hours=effort_hours,
                        )
                    )

    known_ids = {EPIC_PLACEHOLDER_ID} | {i.placeholder_id for i in issues} | {s.placeholder_id for s in subtasks}
    dep_links, skipped = build_dependency_links(plan, known_ids)

    return ExportPlan(
        epic=epic,
        support_epic=support_epic,
        support_task=support_task,
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

    lines.append(f"Было бы создано: 2 Epic (план + поддержка), {len(export_plan.issues)} Issue, "
                  f"{len(export_plan.subtasks)} Subtask, 1 Task (поддержка), {len(export_plan.links)} Issue Link")
    lines.append("")

    e = export_plan.epic
    lines.append(f"[Epic] {e.placeholder_id}  \"{e.summary}\"")
    lines.append("  description:")
    lines.extend(f"    {ln}" for ln in e.description.splitlines())
    lines.append("")

    se = export_plan.support_epic
    st = export_plan.support_task
    lines.append(f"[Epic] {se.placeholder_id}  \"{se.summary}\"  (создаётся всегда, вне плана)")
    lines.append("  description:")
    lines.extend(f"    {ln}" for ln in se.description.splitlines())
    lines.append(f"  -- Task (1) -- без Subtask/Sprint/timetracking")
    lines.append(f"    {st.placeholder_id}  [{st.issue_type_name}]  \"{st.summary}\"  parent={st.parent_placeholder}")
    lines.append("")

    lines.append(f"-- Issue ({len(export_plan.issues)}) --")
    for i in export_plan.issues:
        parent_note = f"  parent={i.parent_placeholder}" if i.parent_placeholder else ""
        sprint_note = f"  sprint={i.sprint_name!r}" if i.sprint_name else ""
        estimate_note = (
            f"  originalEstimate={hours_to_jira_duration(i.effort_hours)!r}" if i.effort_hours is not None else ""
        )
        lines.append(f"  {i.placeholder_id}  [{i.issue_type_name}]  \"{i.summary}\"  labels={i.labels}{parent_note}{sprint_note}{estimate_note}")
    lines.append("")

    if export_plan.subtasks:
        lines.append(f"-- Subtask ({len(export_plan.subtasks)}) --")
        for s in export_plan.subtasks:
            sprint_note = f"  sprint={s.sprint_name!r}" if s.sprint_name else ""
            estimate_note = (
                f"  originalEstimate={hours_to_jira_duration(s.effort_hours)!r}" if s.effort_hours is not None else ""
            )
            lines.append(f"  {s.placeholder_id}  [{s.issue_type_name}]  \"{s.summary}\"  parent={s.parent_placeholder}  labels={s.labels}{sprint_note}{estimate_note}")
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


def format_sprint_dry_run_report(
    planned_sprints: list[PlannedSprint],
    board: dict,
    project_key: str,
    sprint_wbs_ids: dict[int, list[str]],
) -> str:
    lines = ["=== --create-sprints -- DRY-RUN, вызовов на запись не было ===", ""]
    lines.append(f"Проект: {project_key}")
    lines.append(f"Доска с Sprint: {board.get('name')!r} (id={board.get('id')}, type={board.get('type')!r})")
    lines.append("")
    lines.append(f"Было бы создано: {len(planned_sprints)} Sprint")
    for sp in planned_sprints:
        lines.append(
            f"  name={sp.name!r}  goal={sp.goal!r}  (startDate={sp.start_date}, endDate={sp.end_date})"
        )
    lines.append("")
    lines.append(
        "Было бы привязано к Sprint после реального создания -- только WBS-Issue, не Subtask -- "
        f"POST /rest/agile/1.0/sprint/{{id}}/issue, пакетами <={MAX_ISSUES_PER_SPRINT_LINK_BATCH} issue:"
    )
    for sp in planned_sprints:
        wbs_ids = sprint_wbs_ids.get(sp.number, [])
        n_batches = len(list(chunked(wbs_ids, MAX_ISSUES_PER_SPRINT_LINK_BATCH)))
        lines.append(f"  {sp.name}  ({len(wbs_ids)} WBS, {n_batches} батч(ей)): {', '.join(wbs_ids)}")
    lines.append("")
    lines.append(
        "Нативное поле Jira Sprint (customfield_...) проставляется этой привязкой на WBS-Issue; имя "
        "спринта остаётся также первой строкой в description Issue/Subtask (человекочитаемо, "
        "дублирует нативное поле, не заменяет его)."
    )
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
    Используется для Issue/Subtask description. Epic description при
    --execute берёт structured ADF из PlannedIssue.description_adf напрямую
    (настоящие таблицы Риски/Критерии), эту построчную функцию не проходит --
    см. build_epic_description_adf."""
    lines = text.split("\n")
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": line}]} if line else {"type": "paragraph"}
            for line in lines
        ],
    }


def hours_to_jira_duration(hours: float) -> str:
    """Jira timetracking.originalEstimate -- "pretty duration" ("1h 30m"),
    не принимает дробные единицы вроде "1.5h" (обнаружено на живом TPT:
    HTTP 400 "Określ prawidłową wartość dla rejestrowania czasu" -- "Specify
    a valid value for time tracking"). Раскладывает часы на целые h + m
    (округление до минуты)."""
    total_minutes = round(hours * 60)
    h, m = divmod(total_minutes, 60)
    parts = []
    if h:
        parts.append(f"{h}h")
    if m or not parts:
        parts.append(f"{m}m")
    return " ".join(parts)


def _timetracking_fields(planned: PlannedIssue) -> dict:
    """originalEstimate из effort_estimates -- только если оно есть в плане
    (WBS-Issue и custom Task без оценки получают {}, а не выдуманное число)."""
    if planned.effort_hours is None:
        return {}
    return {"timetracking": {"originalEstimate": hours_to_jira_duration(planned.effort_hours)}}


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
        "description": epic.description_adf if epic.description_adf is not None else text_to_adf(epic.description),
    }
    epic_key = client.create_issue(epic_fields)
    key_by_placeholder[epic.placeholder_id] = epic_key
    _persist_state(state_path, key_by_placeholder)
    log(f"Создан Epic: {epic_key}")

    # Epic "Поддержка" -- создаётся всегда (без флага), вне plan["milestones"].
    support_epic = export_plan.support_epic
    support_epic_fields = {
        "project": {"key": project_key},
        "issuetype": {"name": support_epic.issue_type_name},
        "summary": support_epic.summary,
        "description": support_epic.description_adf
        if support_epic.description_adf is not None
        else text_to_adf(support_epic.description),
    }
    support_epic_key = client.create_issue(support_epic_fields)
    key_by_placeholder[support_epic.placeholder_id] = support_epic_key
    _persist_state(state_path, key_by_placeholder)
    log(f"Создан Epic (поддержка): {support_epic_key}")

    support_task = export_plan.support_task
    support_task_fields = {
        "project": {"key": project_key},
        "issuetype": {"name": support_task.issue_type_name},
        "summary": support_task.summary,
        "description": text_to_adf(support_task.description),
        "parent": {"key": support_epic_key},
    }
    support_task_key = client.create_issue(support_task_fields)
    key_by_placeholder[support_task.placeholder_id] = support_task_key
    _persist_state(state_path, key_by_placeholder)
    log(f"Создана Task (поддержка): {support_task_key}")

    for issue in export_plan.issues:
        fields: dict = {
            "project": {"key": project_key},
            "issuetype": {"name": issue.issue_type_name},
            "summary": issue.summary,
            "description": text_to_adf(issue_description_with_sprint(issue)),
            "labels": issue.labels,
        }
        fields.update(_timetracking_fields(issue))
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
        fields.update(_timetracking_fields(sub))
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


def link_issues_to_sprints(
    client,
    planned_sprints: list[PlannedSprint],
    sprint_wbs_ids: dict[int, list[str]],
    key_by_placeholder: dict[str, str],
    real_sprint_id_by_number: dict[int, int],
    verbose: bool = True,
) -> None:
    """Привязывает реально созданные WBS-Issue (не Subtask) к реально
    созданным Sprint -- только после того, как оба существуют (--execute +
    --create-sprints). Jira Sub-task не хранит Sprint независимо от
    родителя (обнаружено эмпирически на живом TPT), поэтому привязываются
    только WBS-Issue; каждый WBS шаблона лежит ровно в одном спринте
    (schema/sprint_plan.yaml, Этап 5) -- sprint_wbs_ids уже отфильтровал бы
    WBS, у которых это не так, если бы такой случай встретился
    (см. build_wbs_sprint). WBS, для которых в sprint_wbs_ids есть номер
    спринта, но нет ключа в
    key_by_placeholder (issue не создан), не привязываются молча -- это
    печатается явно, тем же паттерном, что skipped_links в execute_export."""

    def log(msg: str) -> None:
        if verbose:
            print(msg)

    for sp in planned_sprints:
        wbs_ids = sprint_wbs_ids.get(sp.number, [])
        issue_keys = []
        for wbs_id in wbs_ids:
            key = key_by_placeholder.get(wbs_id)
            if key is None:
                log(f"  ! Пропущена привязка {wbs_id} к Sprint {sp.name!r}: issue не создан")
                continue
            issue_keys.append(key)
        real_sprint_id = real_sprint_id_by_number[sp.number]
        for batch in chunked(issue_keys, MAX_ISSUES_PER_SPRINT_LINK_BATCH):
            client.add_issues_to_sprint(real_sprint_id, batch)
            log(f"Привязано к Sprint {sp.name!r} (id={real_sprint_id}): {len(batch)} WBS-Issue")


# ---------------------------------------------------------------------------
# Self-test -- полностью офлайн, через FakeJiraClient и фикстуры схемы.
# ---------------------------------------------------------------------------


def _load_client_abc_plan() -> dict:
    path = AGENT_DIR / "examples" / "client-abc.plan.json"
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
    plan = _load_client_abc_plan()
    report = validate_plan(plan)
    assert not report.findings, f"regression: базовый client-abc.plan.json должен быть чист: {report.findings}"

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
    print("[selftest] Sprint у Subtask -- имя спринта -- OK")

    # Epic "Поддержка" -- создаётся всегда (без флага), вне зависимости от
    # плана; ровно одна Task внутри, без Subtask/Sprint/timetracking, тот
    # же issuetype-паттерн (schema.epic_type/task_type), что у основного Epic.
    assert export_plan.support_epic.issue_type_name == schema.epic_type["name"]
    assert export_plan.support_epic.summary == SUPPORT_EPIC_SUMMARY
    assert export_plan.support_task.issue_type_name == schema.task_type["name"]
    assert export_plan.support_task.summary == SUPPORT_LOG_TASK_SUMMARY
    assert export_plan.support_task.parent_placeholder == export_plan.support_epic.placeholder_id
    assert export_plan.support_task.sprint_name is None
    assert export_plan.support_task.effort_hours is None
    assert export_plan.support_epic.placeholder_id not in {i.placeholder_id for i in export_plan.issues}
    assert export_plan.support_task.placeholder_id not in {s.placeholder_id for s in export_plan.subtasks}
    print("[selftest] Epic \"Поддержка\": создаётся всегда, 1 Task без Subtask/Sprint/timetracking -- OK")

    # plan["meta"]["lang"] == "ua" (assemble_plan.py --lang, CHANGELOG v3.6) --
    # Epic "Поддержка" не читается из milestones_wbs{.lang}.yaml (создаётся вне
    # plan["milestones"]), поэтому локализуется отдельно; build_export_plan()
    # обязан резолвить lang из plan["meta"], а не оставлять его всегда "ru".
    ua_plan = dict(plan)
    ua_plan["meta"] = {**plan["meta"], "lang": "ua"}
    ua_export_plan = build_export_plan(ua_plan, schema, flat_fallback=False)
    assert ua_export_plan.support_epic.summary == SUPPORT_EPIC_SUMMARY_BY_LANG["ua"] == "Підтримка"
    assert ua_export_plan.support_task.summary == SUPPORT_LOG_TASK_SUMMARY_BY_LANG["ua"] == "Журнал підтримки"
    assert ua_export_plan.support_epic.summary != export_plan.support_epic.summary
    missing_lang_plan = dict(plan)
    missing_lang_plan["meta"] = {k: v for k, v in plan["meta"].items() if k != "lang"}
    fallback_export_plan = build_export_plan(missing_lang_plan, schema, flat_fallback=False)
    assert fallback_export_plan.support_epic.summary == SUPPORT_EPIC_SUMMARY_BY_LANG["ru"], (
        "plan['meta'] без ключа 'lang' (старый plan.json до v3.6) должен фолбэчиться на ru, не падать"
    )
    print("[selftest] Epic \"Поддержка\"/\"Підтримка\": локализуется по plan['meta']['lang'], фолбэк ru при отсутствии ключа -- OK")

    # Epic description (текст, dry-run отчёт) -- риски очищены через
    # clean_business_text (переиспользован render_risks, не переизобретён),
    # присутствуют charter.description и charter.objective.
    assert "WBS-2.1)" not in export_plan.epic.description and "(WBS-2.1)" not in export_plan.epic.description
    assert "interview_checklist" not in export_plan.epic.description
    assert plan["charter"]["objective"] in export_plan.epic.description
    assert plan["charter"]["description"] in export_plan.epic.description
    print("[selftest] текстовое description Epic содержит charter.description + charter.objective + очищенные риски -- OK")

    # Epic description_adf (реальный ADF при --execute) -- настоящие таблицы,
    # не markdown-текст с '|' внутри параграфов.
    adf = export_plan.epic.description_adf
    assert adf is not None and adf["type"] == "doc"
    table_nodes = [n for n in adf["content"] if n["type"] == "table"]
    assert len(table_nodes) == 2, "ожидались ровно 2 таблицы (Риски + Критерии завершения) в ADF Epic"
    risks_table, criteria_table = table_nodes
    heading_texts = [n["content"][0]["text"] for n in adf["content"] if n["type"] == "heading"]
    assert heading_texts == ["Риски проекта", "Критерии завершения этапов"], heading_texts

    def _cell_text(row: dict, col: int) -> str:
        para = row["content"][col]["content"][0]
        return para["content"][0]["text"] if para.get("content") else ""

    risk_header = risks_table["content"][0]
    assert _cell_text(risk_header, 0) == "Риск" and _cell_text(risk_header, 1) == "Затрагивает"
    assert all(r["content"][0]["type"] == "tableHeader" for r in [risk_header])
    assert not any("|" in _cell_text(row, 0) for row in risks_table["content"][1:]), "риск не должен содержать '|' -- признак непревращённого markdown"

    criteria_header = criteria_table["content"][0]
    assert [_cell_text(criteria_header, i) for i in range(3)] == ["ID", "Название", "Описание"]
    milestone_ids = {m["id"] for m in plan["milestones"]}
    wbs_ids = {wbs["id"] for m in plan["milestones"] for wbs in m["wbs"]}
    task_ids_all = {t["id"] for t in flatten_tasks(plan)}
    row_ids = [_cell_text(row, 0) for row in criteria_table["content"][1:]]
    assert set(row_ids) == milestone_ids | wbs_ids, (set(row_ids) - (milestone_ids | wbs_ids), (milestone_ids | wbs_ids) - set(row_ids))
    assert not (set(row_ids) & task_ids_all), "в таблице критериев не должно быть строк Task"
    print(
        f"[selftest] description_adf Epic: настоящие ADF-таблицы Риски ({len(risks_table['content']) - 1} строк) "
        f"и Критерии завершения ({len(milestone_ids)} Milestone + {len(wbs_ids)} WBS, без Task) -- OK"
    )

    # Базовый client-abc.plan.json чист (validate_plan -- 0 находок выше) --
    # ни одна depends_on/used_by ссылка не должна быть пропущена как битая.
    assert not export_plan.skipped_links, export_plan.skipped_links
    print("[selftest] на чистом плане skipped_links пуст -- ни одна ссылка не потеряна -- OK")

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
    assert len(fake.created_issues) == 3 + len(export_plan.issues) + len(export_plan.subtasks), (
        len(fake.created_issues), 3, len(export_plan.issues), len(export_plan.subtasks)
    )
    assert len(fake.created_links) == len(export_plan.links)
    assert key_by_placeholder["EPIC"] == "ESK-1"
    wbs_issue = next(i for i in export_plan.issues)
    assert key_by_placeholder[wbs_issue.placeholder_id].startswith("ESK-")
    assert key_by_placeholder[SUPPORT_EPIC_PLACEHOLDER_ID].startswith("ESK-")
    assert key_by_placeholder[SUPPORT_LOG_TASK_PLACEHOLDER_ID].startswith("ESK-")
    support_task_created = next(
        i for i in fake.created_issues if i["key"] == key_by_placeholder[SUPPORT_LOG_TASK_PLACEHOLDER_ID]
    )
    assert support_task_created["fields"]["parent"]["key"] == key_by_placeholder[SUPPORT_EPIC_PLACEHOLDER_ID]
    assert "timetracking" not in support_task_created["fields"]
    print(
        f"[selftest] execute (FakeJiraClient): {len(fake.created_issues)} issue создано "
        f"(2 Epic + Issue + Subtask + 1 Task поддержки), {len(fake.created_links)} связей -- "
        "совпадает с dry-run -- OK"
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

    # --- 5a. timetracking (originalEstimate) -- из effort_estimates, без выдуманных оценок. ---
    sample_task_id = "T-1.1.1"
    expected_hours = plan["effort_estimates"][sample_task_id]["hours"]
    sample_subtask = next(s for s in export_plan.subtasks if s.placeholder_id == sample_task_id)
    assert sample_subtask.effort_hours == expected_hours, (sample_subtask.effort_hours, expected_hours)
    assert all(i.effort_hours is None for i in export_plan.issues), (
        "WBS-Issue не должен получать timetracking -- агрегированной оценки часов на уровне WBS в плане нет"
    )
    print("[selftest] effort_hours: обычная Task берёт часы из effort_estimates, WBS-Issue -- None -- OK")

    sample_key = key_by_placeholder[sample_task_id]
    sample_fields = created_by_key[sample_key]["fields"]
    assert sample_fields["timetracking"]["originalEstimate"] == hours_to_jira_duration(expected_hours), (
        sample_fields.get("timetracking")
    )
    print(
        "[selftest] originalEstimate: попадает в fields созданного issue как pretty duration "
        "(hours_to_jira_duration) -- OK"
    )

    # hours_to_jira_duration: Jira не принимает дробные единицы ("1.5h") -- обнаружено
    # на живом TPT (HTTP 400 "Określ prawidłową wartość dla rejestrowania czasu").
    assert hours_to_jira_duration(1.5) == "1h 30m"
    assert hours_to_jira_duration(2.0) == "2h"
    assert hours_to_jira_duration(0.75) == "45m"
    assert hours_to_jira_duration(0.5) == "30m"
    assert hours_to_jira_duration(0.25) == "15m"
    assert hours_to_jira_duration(10.0) == "10h"
    assert hours_to_jira_duration(1.25) == "1h 15m"
    assert "." not in hours_to_jira_duration(1.5) and "." not in hours_to_jira_duration(0.75), (
        "результат не должен содержать дробных единиц -- именно это отклонил живой TPT"
    )
    print(
        "[selftest] hours_to_jira_duration: дробные часы (1.5, 0.75, 1.25 и т.д.) -- в целые h/m без точки "
        "(закрывает находку с живого TPT) -- OK"
    )

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

    # --- 8. --create-sprints (opt-in): парсинг дат, поиск Scrum-доски, создание Sprint. ---
    planned_sprints = build_planned_sprints(plan)
    assert len(planned_sprints) == len(plan["sprint_plan"]["sprints"])
    assert planned_sprints[0].goal == plan["sprint_plan"]["sprints"][0]["name"], (
        "goal должен содержать полное имя из плана без изменений"
    )
    assert planned_sprints[0].name == "Спринт 1", planned_sprints[0].name
    assert all(len(sp.name) <= JIRA_SPRINT_NAME_MAX_LENGTH for sp in planned_sprints), (
        "короткое name не должно превышать лимит Jira -- обнаружено на живом TPT (HTTP 400 при полном имени)",
        [(sp.name, len(sp.name)) for sp in planned_sprints],
    )
    first_sprint_plan = plan["sprint_plan"]["sprints"][0]
    assert planned_sprints[0].start_date == first_sprint_plan["start_date"], planned_sprints[0]
    assert planned_sprints[0].end_date == first_sprint_plan["end_date"], planned_sprints[0]
    print(
        f"[selftest] build_planned_sprints: {len(planned_sprints)} спринтов, короткое name (<={JIRA_SPRINT_NAME_MAX_LENGTH} "
        f"симв.) + полное goal без изменений, даты распознаются из плана -- OK"
    )

    # "simple"-доска, которая реально поддерживает Sprint -- воспроизводит находку
    # на живом проекте TPT: `type` из Agile API не равен "scrum", но Sprint включены.
    team_managed_board = {"id": 6, "name": "TPT board", "type": "simple"}
    kanban_board = {"id": 43, "name": "TPT kanban", "type": "kanban"}

    fake_sprints = FakeJiraClient(
        _company_managed_issue_types(),
        board_candidates=[kanban_board, team_managed_board],
        sprint_capable_board_ids={team_managed_board["id"]},
    )
    board_found = require_sprint_capable_board(fake_sprints, fake_sprints.get_board_candidates(), "TPT")
    assert board_found == team_managed_board, board_found
    print(
        "[selftest] require_sprint_capable_board: находит доску по реальной поддержке Sprint, "
        "а не по полю type ('simple', как на живом TPT, а не 'scrum') -- OK"
    )

    try:
        require_sprint_capable_board(fake_sprints, [], "TPT")
    except BoardUnavailableError:
        print("[selftest] require_sprint_capable_board: досок нет -- остановлено явной ошибкой -- OK")
    else:
        raise AssertionError("отсутствие досок должно останавливать --create-sprints")

    fake_no_sprints = FakeJiraClient(
        _company_managed_issue_types(), board_candidates=[kanban_board], sprint_capable_board_ids=set()
    )
    try:
        require_sprint_capable_board(fake_no_sprints, fake_no_sprints.get_board_candidates(), "TPT")
    except BoardUnavailableError:
        print(
            "[selftest] require_sprint_capable_board: доска есть, но Sprint не поддерживает -- "
            "остановлено явной ошибкой, доска не включается сама -- OK"
        )
    else:
        raise AssertionError("отсутствие доски с Sprint должно останавливать --create-sprints")

    for sp in planned_sprints:
        fake_sprints.create_sprint(
            board_found["id"], sp.name, f"{sp.start_date}T00:00:00.000Z", f"{sp.end_date}T00:00:00.000Z", goal=sp.goal
        )
    assert len(fake_sprints.created_sprints) == len(planned_sprints)
    assert all(c["name"] == sp.name for c, sp in zip(fake_sprints.created_sprints, planned_sprints)), (
        "name созданного Sprint должен совпадать с коротким name из плана"
    )
    assert all(c["goal"] == sp.goal for c, sp in zip(fake_sprints.created_sprints, planned_sprints)), (
        "goal созданного Sprint должен совпадать с полным именем из плана без изменений"
    )
    print(
        f"[selftest] create_sprint (FakeJiraClient): {len(fake_sprints.created_sprints)} Sprint создано, "
        f"имена совпадают с планом без изменений -- OK (привязка -- отдельный вызов link_issues_to_sprints, ниже)"
    )

    sprint_wbs_ids = build_sprint_wbs_ids(plan)
    all_wbs_ids_in_plan = {wbs["id"] for m in plan["milestones"] for wbs in m["wbs"]}
    all_wbs_ids_grouped = {wid for ids in sprint_wbs_ids.values() for wid in ids}
    assert all_wbs_ids_grouped <= all_wbs_ids_in_plan, all_wbs_ids_grouped - all_wbs_ids_in_plan
    excluded_wbs = all_wbs_ids_in_plan - all_wbs_ids_grouped
    # С Этапа 5 v3 (schema/sprint_plan.yaml) каждый WBS лежит ровно в одном
    # спринте по построению -- исключений (WBS, расходящихся по нескольким
    # спринтам) больше не бывает.
    assert not excluded_wbs, excluded_wbs
    print(
        f"[selftest] build_sprint_wbs_ids: все {len(all_wbs_ids_grouped)} WBS сгруппированы "
        f"по {len(sprint_wbs_ids)} спринтам, исключений нет (каждый WBS лежит ровно в одном спринте) -- OK"
    )

    assert list(chunked([1, 2, 3, 4, 5], 2)) == [[1, 2], [3, 4], [5]]
    assert list(chunked([], 50)) == []
    big_batch = list(range(120))
    chunks = list(chunked(big_batch, MAX_ISSUES_PER_SPRINT_LINK_BATCH))
    assert [len(c) for c in chunks] == [50, 50, 20], [len(c) for c in chunks]
    assert sum(chunks, []) == big_batch
    print(
        f"[selftest] chunked: режет на батчи по <={MAX_ISSUES_PER_SPRINT_LINK_BATCH}, "
        "без потери и дублирования элементов -- OK"
    )

    sprint_report = format_sprint_dry_run_report(planned_sprints, board_found, project_key="TPT", sprint_wbs_ids=sprint_wbs_ids)
    assert "DRY-RUN" in sprint_report
    assert f"{len(planned_sprints)} Sprint" in sprint_report
    assert "POST /rest/agile/1.0/sprint/{id}/issue" in sprint_report
    for sp in planned_sprints:
        assert f"{len(sprint_wbs_ids.get(sp.number, []))} WBS" in sprint_report, sp.name
    print(
        "[selftest] --create-sprints dry-run отчёт: показывает превью привязки WBS-Issue (без POST) -- OK"
    )

    # link_issues_to_sprints: реально созданные WBS-Issue (не Subtask) -> реально созданные
    # Sprint, батчами <=MAX_ISSUES_PER_SPRINT_LINK_BATCH; пропавший ключ не привязывается молча.
    fake_link_client = FakeJiraClient(_company_managed_issue_types())
    real_sprint_id_by_number = {sp.number: 1000 + sp.number for sp in planned_sprints}
    key_by_placeholder_for_link = dict(key_by_placeholder)  # из шага 5 (execute через FakeJiraClient)
    sprint_with_wbs = next(sp.number for sp in planned_sprints if sprint_wbs_ids.get(sp.number))
    missing_wbs_id = next(iter(sprint_wbs_ids[sprint_with_wbs]))
    del key_by_placeholder_for_link[missing_wbs_id]  # симулирует issue, который не создался
    link_issues_to_sprints(
        fake_link_client, planned_sprints, sprint_wbs_ids, key_by_placeholder_for_link, real_sprint_id_by_number,
        verbose=False,
    )
    linked_by_sprint: dict[int, list[str]] = {}
    for sprint_id, keys in fake_link_client.sprint_issue_batches:
        linked_by_sprint.setdefault(sprint_id, []).extend(keys)
        assert len(keys) <= MAX_ISSUES_PER_SPRINT_LINK_BATCH, keys
    total_linked = sum(len(v) for v in linked_by_sprint.values())
    total_expected = sum(len(v) for v in sprint_wbs_ids.values()) - 1  # минус пропавший ключ
    assert total_linked == total_expected, (total_linked, total_expected)
    linking_sprint_id = real_sprint_id_by_number[sprint_with_wbs]
    assert missing_wbs_id not in [
        key_by_placeholder_for_link.get(w) for w in sprint_wbs_ids[sprint_with_wbs]
    ], "пропавший WBS не должен попасть в привязку"
    assert linking_sprint_id in linked_by_sprint, f"спринт {sprint_with_wbs} должен получить хотя бы одну привязку"
    print(
        f"[selftest] link_issues_to_sprints: {total_linked} WBS-Issue привязано батчами (макс. "
        f"{MAX_ISSUES_PER_SPRINT_LINK_BATCH}), issue без ключа пропущен явно, не молча -- OK"
    )

    # board_supports_sprints реального JiraClient -- различает "не поддерживает" (400 с
    # конкретным текстом) от прочих ошибок (не проглатывается как False молча).
    class _BoardSprintOpener:
        def __init__(self, responses: list) -> None:
            self.responses = list(responses)

        def __call__(self, req: urllib.request.Request):
            resp = self.responses.pop(0)
            if isinstance(resp, Exception):
                raise resp
            return _FakeResponse(resp)

    unsupported_error = urllib.error.HTTPError(
        "https://example.atlassian.net/rest/agile/1.0/board/1/sprint",
        400,
        "Bad Request",
        {},
        io.BytesIO(b'{"errorMessages":["The board does not support sprints"]}'),
    )
    board_opener = _BoardSprintOpener([unsupported_error, b'{"values": []}'])
    client_board_check = JiraClient("https://example.atlassian.net", "a@b.com", "token", "TPT", opener=board_opener)
    assert client_board_check.board_supports_sprints(1) is False
    assert client_board_check.board_supports_sprints(6) is True
    print(
        "[selftest] JiraClient.board_supports_sprints: различает HTTP 400 'does not support sprints' "
        "(False) от успешного ответа (True), не путает с type-полем -- OK"
    )

    print("[selftest] Все проверки Jira-экспорта сработали корректно -- OK")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def run_export(
    plan: dict,
    project_key: str,
    *,
    jira_url: str | None = None,
    email: str | None = None,
    api_token: str | None = None,
    schema_fixture: Path | None = None,
    allow_flat_fallback: bool = False,
    flat_child_link_type: str = DEFAULT_FLAT_CHILD_LINK_TYPE,
    output: Path | None = None,
    state_file: Path | None = None,
    execute: bool = False,
    confirm: bool = False,
    create_sprints: bool = False,
    plan_path: Path | None = None,
) -> None:
    """Этап 8 целиком -- используется и CLI (main(), ниже), и
    agent/create_project.py (единая точка входа "клиентский input -> Jira",
    без промежуточного --plan-файла для консультанта). `plan_path`, если
    передан, только для дефолтного имени `--state-file` (`<plan_path>.jira-
    export-state.json`) -- create_project.py передаёт свой собственный
    `state_file` явно (план хранится в agent/runs/{client_id}/, не рядом с
    произвольным --plan)."""
    if not schema_fixture and not (jira_url and project_key and email and api_token):
        print(
            "ОШИБКА: нужен либо schema_fixture, либо все из jira_url/project_key/email/api_token",
            file=sys.stderr,
        )
        sys.exit(2)

    report = validate_plan(plan)
    if report.findings:
        print(
            f"ПРЕДУПРЕЖДЕНИЕ: план не прошёл validate_plan.py начисто ({len(report.findings)} находок(и)) -- "
            f"экспорт продолжается, но рекомендуется сначала устранить находки",
            file=sys.stderr,
        )

    if schema_fixture:
        issue_types_raw, fields_raw = load_schema_fixture(schema_fixture)
        client = None
    else:
        client = JiraClient(jira_url, email, api_token, project_key)
        issue_types_raw = client.get_issue_types()
        fields_raw = client.get_fields()

    schema = build_project_schema(issue_types_raw, fields_raw)

    try:
        flat_fallback = require_subtask_or_flat_confirmation(schema, allow_flat_fallback)
    except SubtaskUnavailableError as exc:
        print(f"ОСТАНОВЛЕНО: {exc}", file=sys.stderr)
        sys.exit(2)
    except JiraApiError as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        sys.exit(2)

    export_plan = build_export_plan(plan, schema, flat_fallback, flat_child_link_type)

    planned_sprints: list[PlannedSprint] = []
    board: dict | None = None
    sprint_wbs_ids: dict[int, list[str]] = {}
    if create_sprints:
        if client is None:
            print(
                "ОШИБКА: --create-sprints требует живого проекта (jira_url/project_key/email/api_token), "
                "не schema_fixture",
                file=sys.stderr,
            )
            sys.exit(2)
        board_candidates = client.get_board_candidates()
        try:
            board = require_sprint_capable_board(client, board_candidates, project_key)
        except BoardUnavailableError as exc:
            print(f"ОСТАНОВЛЕНО: {exc}", file=sys.stderr)
            sys.exit(2)
        planned_sprints = build_planned_sprints(plan)
        sprint_wbs_ids = build_sprint_wbs_ids(plan)

    if not execute:
        report_text = format_dry_run_report(export_plan, schema, project_key or "(из schema_fixture)")
        if create_sprints:
            report_text += "\n" + format_sprint_dry_run_report(planned_sprints, board, project_key, sprint_wbs_ids)
        if output:
            output.write_text(report_text, encoding="utf-8")
            print(f"Записано: {output}", file=sys.stderr)
        else:
            print(report_text)
        return

    if client is None:
        print("ОШИБКА: --execute требует живого проекта (jira_url/project_key/email/api_token), не schema_fixture", file=sys.stderr)
        sys.exit(2)

    try:
        confirm_execution(project_key, export_plan, confirm, sys.stdin.isatty())
    except ExecutionNotConfirmed as exc:
        print(f"Отменено: {exc}", file=sys.stderr)
        sys.exit(1)

    if state_file is None and plan_path is not None:
        state_file = plan_path.with_name(plan_path.stem + ".jira-export-state.json")
    print(f"key_by_placeholder пишется по ходу создания в: {state_file}", file=sys.stderr)
    key_by_placeholder = execute_export(client, export_plan, project_key, state_path=state_file)

    if create_sprints:
        real_sprint_id_by_number: dict[int, int] = {}
        for sp in planned_sprints:
            created = client.create_sprint(
                board["id"], sp.name, f"{sp.start_date}T00:00:00.000Z", f"{sp.end_date}T00:00:00.000Z", goal=sp.goal
            )
            real_sprint_id_by_number[sp.number] = created["id"]
            print(f"Создан Sprint: {created.get('id')}  {sp.name}  (goal={sp.goal!r})")

        link_issues_to_sprints(client, planned_sprints, sprint_wbs_ids, key_by_placeholder, real_sprint_id_by_number)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plan", type=Path, help="Путь к плану (Этап 6, JSON), провалидированному Этапом 7")
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
    parser.add_argument(
        "--create-sprints",
        action="store_true",
        help="Опционально создать Sprint на доске проекта (с включённым Sprint) из sprint_plan.sprints[] "
             "(по умолчанию выключено, не меняет поведение без явного запроса; без привязки Issue/Subtask к спринту)",
    )
    parser.add_argument("--selftest", action="store_true", help="Прогнать самопроверку офлайн (FakeJiraClient)")
    args = parser.parse_args()

    if args.selftest:
        run_selftest()
        return

    if not args.plan:
        parser.error("--plan обязателен (или используйте --selftest)")

    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    run_export(
        plan,
        args.project_key,
        jira_url=args.jira_url,
        email=args.email,
        api_token=args.api_token,
        schema_fixture=args.schema_fixture,
        allow_flat_fallback=args.allow_flat_fallback,
        flat_child_link_type=args.flat_child_link_type,
        output=args.output,
        state_file=args.state_file,
        execute=args.execute,
        confirm=args.confirm,
        create_sprints=args.create_sprints,
        plan_path=args.plan,
    )


if __name__ == "__main__":
    main()
