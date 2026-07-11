#!/usr/bin/env python3
"""Лаунчер локальной формы ввода клиентских данных + создания проекта в Jira.

Читает `.env` (`JIRA_BASE_URL`/`JIRA_EMAIL`/`JIRA_API_TOKEN`) рядом с этим
файлом, поднимает локальный HTTP-сервер (только стандартная библиотека,
без внешних зависимостей) и открывает браузер на `client-input-form.html`.

Credentials никогда не попадают в HTML/JS и не приходят в теле запроса --
консультант в форме указывает только Jira Project Key (обычный текстовый
инпут); email/токен/URL сервер сам достаёт из своего окружения (`.env`).

Кнопка «Скачать .json» в форме -- fallback на случай, если локальный сервер
не поднят (offline: ручная передача файла `assemble_plan.py --input` /
`create_project.py --input`). Основной путь:

  1. «Создать план (dry-run)» -> `POST /plan` -> `create_project.run_pipeline`
     без `--execute` (только сборка + валидация + dry-run Jira-экспорта,
     ни одного `POST` в Jira) -> текстовый отчёт показывается в форме.
  2. «Выполнить (создать в Jira)» -- отдельная кнопка, появляется только
     после dry-run-отчёта -> `POST /execute` -> `create_project.run_pipeline`
     с `--execute --confirm` (клик по кнопке в форме -- и есть явное
     подтверждение человеком, `--confirm` выставляется всегда, не через
     интерактивный `input()` в терминале) -> отчёт о реальном создании.
     После ответа на этот запрос сервер сам завершает процесс лаунчера --
     сессия (dry-run -> просмотр -> execute) закончена. Если консультант
     останавливается на dry-run и не нажимает «Выполнить», процесс остаётся
     работать, пока его не остановят вручную (Ctrl+C) -- это не отличается
     от обычного локального dev-сервера.

Запуск:
    python3 agent/run_form.py
    python3 agent/run_form.py --selftest
"""

from __future__ import annotations

import argparse
import contextlib
import http.server
import io
import json
import os
import sys
import threading
import urllib.request
import webbrowser
from pathlib import Path

import create_project
import jira_export

AGENT_DIR = Path(__file__).resolve().parent
FORM_HTML_PATH = AGENT_DIR / "client-input-form.html"
DOTENV_PATH = AGENT_DIR / ".env"
REQUIRED_ENV_KEYS = ["JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"]


# ---------------------------------------------------------------------------
# .env -- минимальный парсер (без внешних зависимостей типа python-dotenv,
# по духу repo -- только стандартная библиотека).
# ---------------------------------------------------------------------------


def load_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[key] = value
    return values


def resolve_env() -> dict[str, str]:
    """Реальный os.environ имеет приоритет над `.env` -- обычная конвенция
    (файл задаёт значения по умолчанию для локальной разработки, а не
    переопределяет уже экспортированные переменные окружения)."""
    dotenv_values = load_dotenv(DOTENV_PATH)
    return {key: os.environ.get(key) or dotenv_values.get(key, "") for key in REQUIRED_ENV_KEYS}


# ---------------------------------------------------------------------------
# HTTP-обработчик
# ---------------------------------------------------------------------------


class FormRequestHandler(http.server.BaseHTTPRequestHandler):
    # Переопределяются per-сервер через make_handler_class() -- сам класс
    # ниже используется только как база (без этих значений сервер не
    # запускается на реальном окружении, только через фабрику).
    env: dict[str, str] = {}
    runs_dir: Path = create_project.RUNS_DIR
    create_sprints: bool = False

    def log_message(self, format: str, *args) -> None:  # noqa: A002 -- сигнатура stdlib
        pass  # тихий сервер -- не шуметь в консоли консультанта на каждый запрос

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 -- сигнатура stdlib
        if self.path in ("/", "/client-input-form.html"):
            html = FORM_HTML_PATH.read_text(encoding="utf-8").encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
        else:
            self.send_response(404)
            self.end_headers()

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def _run_pipeline_captured(self, *, execute: bool) -> dict:
        body = self._read_json_body()
        input_json = body.get("input_json")
        project_key = (body.get("project_key") or "").strip()
        if not input_json or not project_key:
            return {"ok": False, "report": "ОШИБКА: input_json и project_key обязательны в теле запроса"}

        buf = io.StringIO()
        ok = True
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                create_project.run_pipeline(
                    input_json,
                    project_key,
                    jira_url=self.env["JIRA_BASE_URL"],
                    email=self.env["JIRA_EMAIL"],
                    api_token=self.env["JIRA_API_TOKEN"],
                    runs_dir=self.runs_dir,
                    execute=execute,
                    confirm=execute,  # клик по кнопке «Выполнить» в форме -- и есть подтверждение человеком
                    create_sprints=self.create_sprints,
                )
        except SystemExit as exc:
            ok = False
            buf.write(f"\n[остановлено, код выхода {exc.code}]")
        except Exception as exc:  # noqa: BLE001 -- отчёт об ошибке идёт консультанту, не роняет сервер
            ok = False
            buf.write(f"\n[ошибка: {exc}]")
        return {"ok": ok, "report": buf.getvalue()}

    def do_POST(self) -> None:  # noqa: N802 -- сигнатура stdlib
        if self.path == "/plan":
            self._send_json(200, self._run_pipeline_captured(execute=False))
        elif self.path == "/execute":
            result = self._run_pipeline_captured(execute=True)
            self._send_json(200, result)
            # Сессия (dry-run -> просмотр -> execute) закончена -- лаунчер
            # завершает процесс. shutdown() блокирует до остановки
            # serve_forever(), поэтому вызывается из отдельного потока --
            # иначе он бы ждал сам себя (тот же поток, что обрабатывает
            # этот же запрос внутри ThreadingHTTPServer).
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        else:
            self._send_json(404, {"ok": False, "report": f"неизвестный путь: {self.path}"})


def make_handler_class(env: dict[str, str], runs_dir: Path, create_sprints: bool = False) -> type:
    return type(
        "BoundFormRequestHandler",
        (FormRequestHandler,),
        {"env": env, "runs_dir": runs_dir, "create_sprints": create_sprints},
    )


def make_server(
    env: dict[str, str],
    runs_dir: Path = create_project.RUNS_DIR,
    port: int = 0,
    create_sprints: bool = False,
) -> http.server.ThreadingHTTPServer:
    handler_cls = make_handler_class(env, runs_dir, create_sprints)
    return http.server.ThreadingHTTPServer(("127.0.0.1", port), handler_cls)


# ---------------------------------------------------------------------------
# Self-test -- офлайн: JiraClient подменён на FakeJiraClient (как везде в
# проекте, --selftest не должен трогать сеть), сервер поднимается на
# свободном порту, запросы идут через настоящий HTTP (urllib.request), не
# вызовом функций напрямую -- проверяется именно сервер, а не только
# create_project.run_pipeline (уже покрыт его собственным --selftest).
# ---------------------------------------------------------------------------


def _fake_jira_client_factory(base_url: str, email: str, api_token: str, project_key: str):
    return jira_export.FakeJiraClient(
        jira_export._company_managed_issue_types(),
        jira_export._fields_with_sprint_and_epic_link(),
    )


def _post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def run_selftest() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        env_path = Path(tmp) / ".env"
        env_path.write_text(
            'JIRA_BASE_URL=https://example.atlassian.net\n'
            'JIRA_EMAIL=consultant@example.com\n'
            '# комментарий -- должен игнорироваться\n'
            'JIRA_API_TOKEN="secret token"\n',
            encoding="utf-8",
        )
        parsed = load_dotenv(env_path)
        assert parsed == {
            "JIRA_BASE_URL": "https://example.atlassian.net",
            "JIRA_EMAIL": "consultant@example.com",
            "JIRA_API_TOKEN": "secret token",
        }, parsed
    print("[selftest] load_dotenv: комментарии/кавычки разобраны корректно -- OK")

    real_jira_client = jira_export.JiraClient
    jira_export.JiraClient = _fake_jira_client_factory
    try:
        env = {
            "JIRA_BASE_URL": "https://example.atlassian.net",
            "JIRA_EMAIL": "consultant@example.com",
            "JIRA_API_TOKEN": "token",
        }
        with tempfile.TemporaryDirectory() as tmp:
            runs_dir = Path(tmp) / "runs"
            server = make_server(env, runs_dir=runs_dir)
            host, port = server.server_address
            base = f"http://{host}:{port}"
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            html = urllib.request.urlopen(base + "/").read().decode("utf-8")
            assert "Jira Project Key" in html, "поле Jira Project Key должно быть в форме"
            print("[selftest] GET / -- отдаёт client-input-form.html с полем Jira Project Key -- OK")

            input_json = json.loads((AGENT_DIR / "examples" / "client-abc.input.json").read_text(encoding="utf-8"))

            missing_fields_resp = _post_json(base + "/plan", {"input_json": None, "project_key": ""})
            assert missing_fields_resp["ok"] is False
            print("[selftest] POST /plan без input_json/project_key -- явная ошибка в отчёте -- OK")

            plan_resp = _post_json(base + "/plan", {"input_json": input_json, "project_key": "ESK"})
            assert plan_resp["ok"] is True, plan_resp
            assert "DRY-RUN" in plan_resp["report"], plan_resp["report"]
            assert not (runs_dir / "abc-sp-z-o-o" / "jira-export-state.json").exists(), (
                "dry-run не должен писать state-файл -- ни одного create_issue не вызвано"
            )
            print("[selftest] POST /plan: dry-run отчёт получен (FakeJiraClient, без сети) -- OK")

            assert thread.is_alive(), "сервер не должен останавливаться после dry-run -- второй запрос ещё впереди"
            print("[selftest] сервер остаётся работать после /plan (ждёт возможного /execute) -- OK")

            execute_resp = _post_json(base + "/execute", {"input_json": input_json, "project_key": "ESK"})
            assert execute_resp["ok"] is True, execute_resp
            assert "Создан Epic" in execute_resp["report"], execute_resp["report"]
            print("[selftest] POST /execute: FakeJiraClient создал Epic/Issue/Subtask, отчёт получен -- OK")

            thread.join(timeout=5)
            assert not thread.is_alive(), "сервер должен завершить процесс после ответа на /execute"
            print("[selftest] сервер сам остановился после ответа на /execute -- OK")
    finally:
        jira_export.JiraClient = real_jira_client

    print("[selftest] Все проверки run_form.py сработали корректно -- OK")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=0, help="Порт локального сервера (по умолчанию -- свободный, выбирает ОС)")
    parser.add_argument("--selftest", action="store_true", help="Прогнать самопроверку офлайн (FakeJiraClient, без сети)")
    args = parser.parse_args()

    if args.selftest:
        run_selftest()
        return

    env = resolve_env()
    missing = [key for key in REQUIRED_ENV_KEYS if not env[key]]
    if missing:
        print(
            f"ОШИБКА: не заданы переменные окружения {missing} -- заполните {DOTENV_PATH} "
            f"(см. {AGENT_DIR / '.env.example'}) или экспортируйте их перед запуском.",
            file=sys.stderr,
        )
        sys.exit(1)

    server = make_server(env, port=args.port)
    host, port = server.server_address
    url = f"http://{host}:{port}/"
    print(f"Форма доступна на {url}")
    print("Ctrl+C -- остановить вручную (сервер сам остановится после «Выполнить»).")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    print("Сервер остановлен.")


if __name__ == "__main__":
    main()
