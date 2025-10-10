#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Autonomous GitHub AI Agent (gpt-5)
- Анализирует Issue
- Генерирует план и правки (JSON) через OpenAI Chat Completions
- Создает ветку, коммиты, пушит и открывает Pull Request
- Пишет комментарии в Issue

Зависимости:
  - PyGithub
  - GitPython
"""

import os
import json
import sys
import logging
import traceback
from pathlib import Path
from datetime import datetime

import git
from github import Github, Auth
import urllib.request
import urllib.error

# ---------------------------- ЛОГИ ---------------------------------
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
log = logging.getLogger("agent")

# ------------------------- НАСТРОЙКИ/КОНСТ -------------------------
REPO_NAME = os.environ.get("REPO_NAME")                   # org/repo
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPEN_AI_TOKEN")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5")    # gpt-5 по умолчанию

# Ограничения безопасности на изменения
ALLOWED_MAX_FILES = 12
ALLOWED_MAX_BYTES_PER_FILE = 200_000  # ~= 200 KB на файл
FORBIDDEN_PATHS = {
    ".git", ".github/workflows", ".github/actions", ".gitignore",
    "/etc", "/usr", "/bin", "/sbin", "/var", "/tmp"
}

# --------------------------- УТИЛИТЫ --------------------------------
def gh_client() -> Github:
    if not GITHUB_TOKEN:
        raise RuntimeError("GITHUB_TOKEN is not set.")
    return Github(auth=Auth.Token(GITHUB_TOKEN))

def read_github_event_issue_number() -> int | None:
    """Пытается вытащить номер issue из файла события GitHub."""
    p = os.environ.get("GITHUB_EVENT_PATH")
    if not p or not Path(p).exists():
        return None
    try:
        data = json.loads(Path(p).read_text(encoding="utf-8"))
        if "issue" in data and "number" in data["issue"]:
            return int(data["issue"]["number"])
        if "inputs" in data and data["inputs"].get("issue_number"):
            return int(data["inputs"]["issue_number"])
    except Exception:
        log.exception("Failed to parse GITHUB_EVENT_PATH")
    return None

def get_issue_number() -> int | None:
    """Возвращает номер issue или None (если не удалось определить)."""
    v = os.environ.get("ISSUE_NUMBER")
    if v:
        try:
            return int(v)
        except ValueError:
            pass
    return read_github_event_issue_number()

def add_issue_comment(repo, issue_number: int, body: str):
    issue = repo.get_issue(number=issue_number)
    issue.create_comment(body)
    log.info("💬 Comment added to issue #%s", issue_number)

def extract_json_object(text: str) -> dict:
    """Извлекает первый валидный JSON-объект из произвольного текста."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in model response.")
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
    return json.loads(text[start:last])

def openai_chat_completion_json(system_prompt: str, user_prompt: str, model: str) -> dict:
    """
    Вызов OpenAI Chat Completions.
    Для gpt-5 используем max_completion_tokens; дополнительно:
    - temperature низкая (0.1) для детерминизма,
    - сокращен лимит, чтобы быстрее и компактнее,
    - многоступенчатый парсинг + автопочинка JSON.
    """
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY/OPEN_AI_TOKEN is not set.")

    url = "https://api.openai.com/v1/chat/completions"
    token_key = "max_completion_tokens" if model.startswith("gpt-5") else "max_tokens"

    payload = {
        "model": model,
        "temperature": 1,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
        token_key: 2500,   # было 3000 — уменьшаем, чтобы снизить риск «болтовни»
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
    )

    raw_content = None
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            raw = resp.read().decode("utf-8")
            obj = json.loads(raw)
            raw_content = obj["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", errors="ignore")
        log.error("OpenAI HTTPError: %s", msg)
        raise
    except TimeoutError:
        log.warning("⏳ Timeout waiting for OpenAI; retrying once with smaller completion limit...")
        # Одно повторение с ещё меньшим лимитом
        payload[token_key] = 1500
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, method="POST",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=900) as resp:
            raw = resp.read().decode("utf-8")
            obj = json.loads(raw)
            raw_content = obj["choices"][0]["message"]["content"]
    except Exception:
        log.exception("OpenAI request failed")
        raise

    # Попытка 1: прямой парсинг
    try:
        return json.loads(raw_content)
    except Exception:
        pass

    # Попытка 2: снять бэктики/ограды и распарсить
    try:
        candidate = _strip_code_fences(raw_content)
        return json.loads(candidate)
    except Exception:
        pass

    # Попытка 3: балансно извлечь первый объект {…}
    try:
        return extract_json_object(raw_content)
    except Exception:
        # Логируем усечённый ответ и просим модель «починить JSON»
        preview = (raw_content or "")[:800]
        log.warning("Model did not return clean JSON, trying to repair… Preview: %r", preview)
        fixed = _repair_json_with_llm(raw_content, model)
        return fixed


def _strip_code_fences(text: str) -> str:
    """Снимает ```json ... ``` / ``` ... ``` и возвращает внутренность."""
    t = text.strip()
    if t.startswith("```"):
        # отрезаем первую строчку (```json или ```), и последнюю ```
        lines = t.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return t


def _repair_json_with_llm(bad_text: str, model: str) -> dict:
    """
    Просим модель вернуть ТОЛЬКО валидный JSON, починив формат.
    Используем тот же ключ API; лимит небольшой, температура минимальная.
    """
    url = "https://api.openai.com/v1/chat/completions"
    token_key = "max_completion_tokens" if model.startswith("gpt-5") else "max_tokens"

    system = (
        "You are a strict JSON repair tool. "
        "You receive a model output that should contain ONE JSON object. "
        "Return ONLY a valid, minified JSON object. No explanations, no backticks."
    )
    user = f"Fix and return only JSON object from the following text:\n\n{bad_text}"

    payload = {
        "model": model,
        "temperature": 0.0,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
        token_key: 800,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        raw = resp.read().decode("utf-8")
        obj = json.loads(raw)
        content = obj["choices"][0]["message"]["content"]

    # последняя попытка — прямой parse либо извлечение
    try:
        return json.loads(content)
    except Exception:
        return extract_json_object(content)

def safe_path(path_str: str) -> Path:
    """Проверяет путь и возвращает безопасный относительный Path внутри репозитория."""
    p = Path(path_str).as_posix().lstrip("/")
    p = Path(p)
    for f in FORBIDDEN_PATHS:
        if p.as_posix().startswith(f):
            raise ValueError(f"Path '{p}' is forbidden for modification.")
    if ".." in p.parts:
        raise ValueError(f"Path '{p}' escapes repo (..).")
    return p

def apply_changes_locally(repo_root: Path, changes: list[dict]) -> list[str]:
    """
    Применяет изменения.
    Элемент changes:
      { "path": "rel/file.py", "op": "create|update", "content": "…", "message": "…" }
    """
    if len(changes) > ALLOWED_MAX_FILES:
        raise ValueError(f"Too many files: {len(changes)} (limit {ALLOWED_MAX_FILES})")

    changed_paths = []
    for ch in changes:
        path = safe_path((ch.get("path") or "").strip())
        op = (ch.get("op") or ch.get("action") or "update").lower()
        content = ch.get("content", "")

        if not path or not op:
            raise ValueError("Each change must include 'path' and 'op'.")

        if isinstance(content, str):
            content_bytes = content.encode("utf-8")
        else:
            content_bytes = json.dumps(content, ensure_ascii=False, indent=2).encode("utf-8")

        if len(content_bytes) > ALLOWED_MAX_BYTES_PER_FILE:
            raise ValueError(f"File '{path}' is too large ({len(content_bytes)} bytes).")

        abs_path = (repo_root / path)
        abs_path.parent.mkdir(parents=True, exist_ok=True)

        if op == "create" and abs_path.exists():
            log.info("File %s exists; switching to update.", path)
            op = "update"

        if op not in {"create", "update"}:
            raise ValueError(f"Unsupported op '{op}' (allowed: create|update).")

        abs_path.write_bytes(content_bytes)
        changed_paths.append(path.as_posix())
        log.info("✏️  %s %s", op.upper(), path)

    return changed_paths

def git_create_branch_commit_push(branch: str, changed_paths: list[str], commit_message: str) -> None:
    repo = git.Repo(Path(".").resolve())
    if branch in [h.name for h in repo.heads]:
        repo.git.checkout(branch)
    else:
        repo.git.checkout("-b", branch)

    repo.index.add(changed_paths)
    repo.index.commit(commit_message or "AI: apply changes")

    origin = repo.remote(name="origin")
    try:
        origin.push(refspec=f"{branch}:{branch}")
    except Exception:
        repo.git.push("--set-upstream", "origin", branch)
    log.info("⬆️  Pushed branch '%s'", branch)

def create_pull_request(gh_repo, branch: str, base: str, title: str, body: str):
    pr = gh_repo.create_pull(title=title, body=body, head=branch, base=base)
    log.info("✅ PR created: #%s %s", pr.number, pr.html_url)
    return pr

def collect_repo_context_for_prompt(root: Path, interesting_files: list[str], max_chars_per_file: int = 4000) -> str:
    out = ["Repository brief context (truncated files):"]
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

# ---------------------------- ОСНОВНОЕ --------------------------------
def main():
    log.info("==================================================")
    log.info("🚀 GitHub AI Agent Starting")
    log.info("==================================================")

    if not REPO_NAME:
        raise RuntimeError("REPO_NAME is not set.")
    if not GITHUB_TOKEN:
        raise RuntimeError("GITHUB_TOKEN is not set.")

    issue_number = get_issue_number()
    log.info("🤖 Agent initialized for: %s", REPO_NAME)
    log.info("🧠 Using OpenAI model: %s", OPENAI_MODEL)

    gh = gh_client()
    gh_repo = gh.get_repo(REPO_NAME)
    base_branch = gh_repo.default_branch or "main"

    # Если номер не указан — берём самый свежий open issue с лейблом ai-agent
    if issue_number is None:
        log.info("ℹ️ ISSUE_NUMBER not provided — searching for open issues with label 'ai-agent'.")
        try:
            label = gh_repo.get_label("ai-agent")
            issues = gh_repo.get_issues(state="open", labels=[label])
            if issues.totalCount == 0:
                log.info("ℹ️ No open issues with label 'ai-agent'. Exiting.")
                return
            issue = next(iter(issues))
            issue_number = issue.number
            log.info("🔎 Selected issue #%s", issue_number)
        except Exception:
            log.info("ℹ️ Label 'ai-agent' not found or no issues. Exiting.")
            return
    else:
        issue = gh_repo.get_issue(number=issue_number)

    issue_title = issue.title or ""
    issue_body = issue.body or ""
    add_issue_comment(gh_repo, issue_number, "🤖 AI Agent начал анализ задачи…")

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

 system_prompt = (
    "You are an autonomous senior Python engineer inside a CI bot for GitHub.\n"
    "Given an issue (title + body) and a brief repo context, you must propose a minimal,\n"
    "safe and incremental solution and PRODUCE CONCRETE CODE CHANGES.\n\n"
    "Return ONLY a **valid, minified JSON object** with this exact schema:\n"
    "{\n"
    "  \"plan_markdown\": \"string\",\n"
    "  \"changes\": [ { \"path\": \"string\", \"op\": \"create|update\", \"content\": \"string\", \"message\": \"string(optional)\" } ],\n"
    "  \"summary_commit_message\": \"string\"\n"
    "}\n"
    "- No prose, no backticks, no markdown fences. Output must be a single JSON object.\n"
    f"- No more than {ALLOWED_MAX_FILES} files; each file <= {ALLOWED_MAX_BYTES_PER_FILE} bytes.\n"
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

    plan_md = (llm_json.get("plan_markdown") or "").strip()
    changes = llm_json.get("changes", [])
    summary_commit = (llm_json.get("summary_commit_message") or "AI: apply changes").strip()

    if not isinstance(changes, list) or not changes:
        add_issue_comment(gh_repo, issue_number, "ℹ️ Модель не предложила изменений. Уточни формулировку Issue.")
        log.info("No changes proposed by model.")
        return

    if plan_md:
        add_issue_comment(gh_repo, issue_number, f"🧠 Анализ и план:\n\n{plan_md}")

    branch = f"ai-issue-{issue_number}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    log.info("📦 Creating branch: %s (base=%s)", branch, base_branch)

    repo = git.Repo(repo_root)
    repo.git.checkout(base_branch)
    repo.remotes.origin.fetch()
    repo.git.pull("--ff-only", "origin", base_branch)

    changed_paths = apply_changes_locally(repo_root, changes)

    detailed_msgs = []
    for ch in changes:
        p = ch.get("path")
        m = ch.get("message") or ""
        if p:
            detailed_msgs.append(f"* {p} — {m}".strip())
    commit_message = summary_commit + ("\n\n" + "\n".join(detailed_msgs) if detailed_msgs else "")

    git_create_branch_commit_push(branch, changed_paths, commit_message)

    pr_title = f"[AI] {issue_title}".strip() or f"[AI] Changes for issue #{issue_number}"
    pr_body = (
        f"🤖 This PR was generated automatically by the AI Agent.\n\n"
        f"Linked issue: #{issue_number}\n\n"
        f"### Plan\n{plan_md or '(no plan provided)'}\n"
    )
    pr = create_pull_request(gh_repo, branch=branch, base=base_branch, title=pr_title, body=pr_body)

    add_issue_comment(
        gh_repo,
        issue_number,
        f"✅ Готов PR: #{pr.number}\n{pr.html_url}\n\n"
        "Проверь изменения. Если всё ок — мержи. "
        "Если нужны правки — напиши в этом issue, агент попробует дополнить."
    )

    log.info("✅ Issue #%s processed", issue_number)
    log.info("✅ Agent finished successfully")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.error("❌ Unhandled error: %s", e)
        traceback.print_exc()
        # Попробуем оставить след в issue
        try:
            if REPO_NAME and GITHUB_TOKEN:
                gh = gh_client()
                repo = gh.get_repo(REPO_NAME)
                n = get_issue_number()
                if n is not None:
                    add_issue_comment(repo, n, f"❌ Агент упал с ошибкой:\n```\n{e}\n```")
        except Exception:
            pass
        sys.exit(1)



