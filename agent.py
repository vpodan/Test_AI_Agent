#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Autonomous GitHub AI Agent
- Анализирует Issue
- Генерирует план и правки кода (JSON) через OpenAI Chat Completions
- Создает ветку, коммиты, пушит и открывает Pull Request
- Пишет комментарии в Issue

Зависимости, уже есть в workflow:
  - PyGithub
  - GitPython

Нужные секреты:
  - GH_TOKEN
  - OPENAI_API_KEY
  - (опц.) OPENAI_MODEL, default: gpt-4.1-mini
"""

import os
import re
import json
import sys
import time
import shutil
import logging
import traceback
from pathlib import Path
from datetime import datetime

import git
from github import Github

import urllib.request
import urllib.error

# ---------- Логирование ----------
LOG_DIR = Path("logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)
log_file = LOG_DIR / "agent.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)

# ---------- Константы ----------
REPO_NAME = os.environ.get("REPO_NAME")  # org/repo
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")

# Безопасность: ограничим, куда можно писать
ALLOWED_MAX_FILES = 12
ALLOWED_MAX_BYTES_PER_FILE = 200_000  # ~200 KB
FORBIDDEN_PATHS = {
    ".git", ".github/workflows", ".github/actions", ".gitignore",
    "/etc", "/usr", "/bin", "/sbin", "/var", "/tmp"
}

# ---------- Утилиты ----------
def read_github_event_issue_number() -> int | None:
    """Пытается вытащить номер issue из GITHUB_EVENT_PATH (fallback для workflow_dispatch)."""
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path or not Path(event_path).exists():
        return None
    try:
        data = json.loads(Path(event_path).read_text(encoding="utf-8"))
        if "issue" in data and "number" in data["issue"]:
            return int(data["issue"]["number"])
        # workflow_dispatch input
        if "inputs" in data and "issue_number" in data["inputs"] and data["inputs"]["issue_number"]:
            return int(data["inputs"]["issue_number"])
    except Exception:
        logging.exception("Failed to parse GITHUB_EVENT_PATH")
    return None


def get_issue_number() -> int:
    val = os.environ.get("ISSUE_NUMBER")
    if val:
        try:
            return int(val)
        except ValueError:
            pass
    n = read_github_event_issue_number()
    if n is None:
        raise RuntimeError("ISSUE_NUMBER not provided and could not be inferred from GITHUB_EVENT_PATH.")
    return n


def gh_client() -> Github:
    if not GITHUB_TOKEN:
        raise RuntimeError("GITHUB_TOKEN is not set.")
    return Github(GITHUB_TOKEN)


def openai_chat_completion_json(system_prompt: str, user_prompt: str, model: str) -> dict:
    """
    Делает вызов OpenAI Chat Completions и возвращает JSON-объект.
    Не требует пакета openai (использует urllib).

    Возвращаем строго dict. Если модель вернула текст с обертками — пытаемся распарсить.
    """
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set.")

    url = "https://api.openai.com/v1/chat/completions"
    payload = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        # Подсказываем желаемый формат ответа
        "response_format": {"type": "json_object"},
        "max_tokens": 3500,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = resp.read().decode("utf-8")
            obj = json.loads(raw)
            content = obj["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", errors="ignore")
        logging.error("OpenAI HTTPError: %s", msg)
        raise
    except Exception:
        logging.exception("OpenAI request failed")
        raise

    # Модель должна вернуть JSON-объект строкой; парсим надежно.
    try:
        return json.loads(content)
    except Exception:
        # fallback: вытащим JSON по фигурным скобкам
        logging.warning("Model did not return clean JSON, trying to extract object...")
        return extract_json_object(content)


def extract_json_object(text: str) -> dict:
    """Извлекает первый валидный JSON-объект из произвольного текста."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in model response.")
    candidate = text[start : end + 1]
    # Баланс скобок
    depth = 0
    last = start
    for i, ch in enumerate(text[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                last = i + 1
                break
    candidate = text[start:last]
    return json.loads(candidate)


def add_issue_comment(repo, issue_number: int, body: str):
    issue = repo.get_issue(number=issue_number)
    issue.create_comment(body)
    logging.info("💬 Comment added to issue #%s", issue_number)


def safe_path(path_str: str) -> Path:
    """Проверяет путь и возвращает безопасный Path внутри репозитория."""
    p = Path(path_str).as_posix().lstrip("/")  # убираем лидирующий /
    p = Path(p)
    # Запреты
    for f in FORBIDDEN_PATHS:
        if p.as_posix().startswith(f):
            raise ValueError(f"Path '{p}' is forbidden for modification.")
    # Запрет на выход вверх
    if ".." in p.parts:
        raise ValueError(f"Path '{p}' escapes repo (..).")
    return p


def apply_changes_locally(repo_root: Path, changes: list[dict]) -> list[str]:
    """
    Применяет изменения к файловой системе.
    Формат каждого элемента:
      { "path": "some/file.py", "op": "create|update", "content": "..." , "message": "Commit msg (optional)" }
    Возвращает список измененных относительных путей.
    """
    if len(changes) > ALLOWED_MAX_FILES:
        raise ValueError(f"Too many files to change: {len(changes)} (limit {ALLOWED_MAX_FILES})")

    changed_paths = []

    for ch in changes:
        path = safe_path(ch.get("path", "").strip())
        op = (ch.get("op") or ch.get("action") or "update").lower()
        content = ch.get("content", "")

        if not path or not op:
            raise ValueError("Change item must include 'path' and 'op'.")

        if isinstance(content, str):
            content_bytes = content.encode("utf-8")
        else:
            content_bytes = json.dumps(content, ensure_ascii=False, indent=2).encode("utf-8")

        if len(content_bytes) > ALLOWED_MAX_BYTES_PER_FILE:
            raise ValueError(f"File '{path}' is too large ({len(content_bytes)} bytes).")

        abs_path = repo_root / path
        abs_path.parent.mkdir(parents=True, exist_ok=True)

        if op == "create" and abs_path.exists():
            logging.info("File %s already exists; switching to update.", path)
            op = "update"

        if op not in {"create", "update"}:
            raise ValueError(f"Unsupported op '{op}'. Only 'create' or 'update' allowed.")

        abs_path.write_bytes(content_bytes)
        changed_paths.append(path.as_posix())
        logging.info("✏️  %s %s", op.upper(), path)

    return changed_paths


def git_create_branch_commit_push(branch: str, changed_paths: list[str], commit_message: str) -> None:
    repo = git.Repo(Path(".").resolve())
    # Создаём ветку от текущего HEAD
    if branch in repo.heads:
        repo.git.checkout(branch)
    else:
        repo.git.checkout("-b", branch)

    repo.index.add(changed_paths)
    repo.index.commit(commit_message or "AI: apply changes")

    # Пушим
    origin = repo.remote(name="origin")
    # Иногда первый пуш требует установки upstream
    try:
        origin.push(refspec=f"{branch}:{branch}")
    except Exception:
        repo.git.push("--set-upstream", "origin", branch)
    logging.info("⬆️  Pushed branch '%s'", branch)


def create_pull_request(gh_repo, branch: str, base: str, title: str, body: str):
    pr = gh_repo.create_pull(
        title=title,
        body=body,
        head=branch,
        base=base,
    )
    logging.info("✅ PR created: #%s %s", pr.number, pr.html_url)
    return pr


def collect_repo_context_for_prompt(root: Path, interesting_files: list[str], max_chars_per_file: int = 4000) -> str:
    """Собирает краткий контекст по ключевым файлам (если есть) для LLM."""
    out = []
    out.append("Repository brief context (truncated files):")
    for rel in interesting_files:
        p = root / rel
        if p.exists() and p.is_file():
            try:
                txt = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                txt = p.read_bytes()[:max_chars_per_file].decode("utf-8", errors="ignore")
            snippet = txt[:max_chars_per_file]
            out.append(f"\n--- FILE: {rel} (first {len(snippet)} chars) ---\n{snippet}\n--- END FILE {rel} ---")
        else:
            out.append(f"\n--- FILE: {rel} (not found) ---")
    return "\n".join(out)


# ---------- Основной сценарий ----------
def main():
    logging.info("==================================================")
    logging.info("🚀 GitHub AI Agent Starting")
    logging.info("==================================================")

    if not REPO_NAME:
        raise RuntimeError("REPO_NAME is not set.")
    if not GITHUB_TOKEN:
        raise RuntimeError("GITHUB_TOKEN is not set.")

    issue_number = get_issue_number()
    logging.info("🤖 Agent initialized for: %s", REPO_NAME)
    logging.info("🧠 Using OpenAI model: %s", OPENAI_MODEL)

    gh = gh_client()
    gh_repo = gh.get_repo(REPO_NAME)
    base_branch = gh_repo.default_branch or "main"

    # Читаем Issue
    issue = gh_repo.get_issue(number=issue_number)
    issue_title = issue.title or ""
    issue_body = issue.body or ""
    add_issue_comment(gh_repo, issue_number, "🤖 AI Agent начал анализ задачи…")

    # Контекст из репо (адаптируй под свой проект)
    repo_root = Path(".").resolve()
    context_text = collect_repo_context_for_prompt(
        repo_root,
        interesting_files=[
            "hybrid_search.py",
            "real_estate_vector_db.py",
            "real_estate_embedding_function.py",
            "test_hybrid_simple.py",
            "README.md",
        ],
    )

    # Запрос к LLM
system_prompt = (
    "You are an autonomous senior Python engineer working inside a CI bot for GitHub.\n"
    "Given an issue (title + body) and a brief repo context, you must propose a minimal,\n"
    "safe and incremental solution and PRODUCE CONCRETE CODE CHANGES.\n\n"
    "Return ONLY a valid JSON object with this schema:\n"
    "{\n"
    "  \"plan_markdown\": \"string (markdown with short step-by-step plan)\",\n"
    "  \"changes\": [\n"
    "    {\n"
    "      \"path\": \"relative/path.ext\",\n"
    "      \"op\": \"create\" | \"update\",\n"
    "      \"content\": \"full file content as UTF-8 text\",\n"
    "      \"message\": \"short commit message for this file (optional)\"\n"
    "    }\n"
    "  ],\n"
    "  \"summary_commit_message\": \"short general commit message\"\n"
    "}\n\n"
    "Constraints:\n"
    f"- No more than {ALLOWED_MAX_FILES} files.\n"
    f"- Each file must be <= {ALLOWED_MAX_BYTES_PER_FILE} bytes of content.\n"
    "- Do not delete files. Only create or update.\n"
    "- Keep code self-contained and runnable. Include imports if needed.\n"
    "- Prefer small, atomic changes and add/update tests when reasonable.\n"
    "- Keep paths inside repo; never use absolute or parent paths.\n"
)

    user_prompt = (
        f"Issue Title:\n{issue_title}\n\n"
        f"Issue Body:\n{issue_body}\n\n"
        f"{context_text}\n\n"
        "Now, produce the JSON as specified. No prose, no backticks."
    )

    try:
        llm_json = openai_chat_completion_json(system_prompt, user_prompt, OPENAI_MODEL)
    except Exception as e:
        add_issue_comment(gh_repo, issue_number, f"⚠️ Ошибка LLM: {e}")
        raise

    # Валидация ответа
    plan_md = llm_json.get("plan_markdown", "").strip()
    changes = llm_json.get("changes", [])
    summary_commit = (llm_json.get("summary_commit_message") or "AI: apply changes").strip()

    if not isinstance(changes, list) or not changes:
        add_issue_comment(gh_repo, issue_number, "ℹ️ Модель не предложила изменений в коде. Проверь формулировку Issue.")
        logging.info("No changes proposed by model.")
        return

    # Публикуем план
    if plan_md:
        add_issue_comment(gh_repo, issue_number, f"🧠 Анализ и план:\n\n{plan_md}")

    # Ветка
    branch = f"ai-issue-{issue_number}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    logging.info("📦 Creating branch: %s (base=%s)", branch, base_branch)

    # Готовим рабочее состояние git
    repo = git.Repo(repo_root)
    # Обновим базовую ветку (на всякий)
    repo.git.checkout(base_branch)
    repo.remotes.origin.fetch()
    repo.git.pull("--ff-only", "origin", base_branch)

    # Применяем изменения на диске
    changed_paths = apply_changes_locally(repo_root, changes)

    # Сводный commit msg
    detailed_msgs = []
    for ch in changes:
        p = ch.get("path")
        m = ch.get("message") or ""
        if p:
            detailed_msgs.append(f"* {p} — {m}".strip())
    commit_message = summary_commit + ("\n\n" + "\n".join(detailed_msgs) if detailed_msgs else "")

    # Коммит и пуш
    git_create_branch_commit_push(branch, changed_paths, commit_message)

    # Создаем PR
    pr_title = f"[AI] {issue_title}".strip() or f"[AI] Changes for issue #{issue_number}"
    pr_body = (
        f"🤖 This PR was generated automatically by the AI Agent.\n\n"
        f"Linked issue: #{issue_number}\n\n"
        f"### Plan\n{plan_md or '(no plan provided)'}\n"
    )
    pr = create_pull_request(gh_repo, branch=branch, base=base_branch, title=pr_title, body=pr_body)

    # Комментарий в issue
    add_issue_comment(
        gh_repo,
        issue_number,
        f"✅ Готов PR: #{pr.number}\n{pr.html_url}\n\n"
        "Проверь изменения. Если всё ок — можно мержить. "
        "Если нужны правки — добавь комментарий, агент попробует дополнить."
    )

    logging.info("✅ Issue #%s processed", issue_number)
    logging.info("✅ Agent finished successfully")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logging.error("❌ Unhandled error: %s", e)
        traceback.print_exc()
        # Падение — тоже оставим след в логах и, если возможно, в Issue
        try:
            if REPO_NAME and GITHUB_TOKEN:
                gh = gh_client()
                repo = gh.get_repo(REPO_NAME)
                n = get_issue_number()
                add_issue_comment(repo, n, f"❌ Агент упал с ошибкой:\n```\n{e}\n```\nСмотри artifact logs/ для подробностей.")
        except Exception:
            pass
        sys.exit(1)

