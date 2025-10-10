#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Autonomous GitHub AI Agent (GPT-5 version)

ENV variables:
  GITHUB_TOKEN      - GitHub Personal Access Token (with repo, workflow permissions)
  OPENAI_API_KEY    - OpenAI API key (for GPT-5)
  REPO_NAME         - owner/repo (e.g., username/repository)
  ISSUE_NUMBER      - Issue number to process (optional; if not set, will search for 'ai-agent' label)

Features:
  - Analyzes GitHub issues automatically
  - Generates production-ready code changes using GPT-5
  - Creates pull requests with detailed plans
  - Handles fallback cases when no code changes are needed
  - Supports both manual and scheduled triggers
"""

import os
import json
import sys
import logging
import traceback
from pathlib import Path
from datetime import datetime

try:
    import git
    from github import Github, Auth
    from openai import OpenAI
except ImportError as e:
    print(f"ERROR: Missing package: {e}")
    print("Run: pip install PyGithub gitpython openai")
    sys.exit(1)

# ======================== ЛОГИРОВАНИЕ ==========================
LOG_DIR = Path("logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)
log_file = LOG_DIR / f"agent_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("agent")

# ======================== КОНСТАНТЫ ==========================
REPO_NAME = os.environ.get("REPO_NAME")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPEN_AI_TOKEN")

ALLOWED_MAX_FILES = 12
ALLOWED_MAX_BYTES_PER_FILE = 200_000
FORBIDDEN_PATHS = {".git", ".github/workflows", ".github/actions"}

# ======================== УТИЛИТЫ ==========================
def get_issue_number() -> int | None:
    """Получает номер issue из переменных окружения или GitHub события"""
    v = os.environ.get("ISSUE_NUMBER")
    if v:
        try:
            return int(v)
        except ValueError:
            pass
    
    # Пытаемся прочитать из GitHub события
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if event_path and Path(event_path).exists():
        try:
            data = json.loads(Path(event_path).read_text(encoding="utf-8"))
            if "issue" in data and "number" in data["issue"]:
                return int(data["issue"]["number"])
        except Exception:
            pass
    
    return None

def gh_client() -> Github:
    """Создаёт GitHub клиент"""
    if not GITHUB_TOKEN:
        raise RuntimeError("GITHUB_TOKEN is not set")
    return Github(auth=Auth.Token(GITHUB_TOKEN))

def add_issue_comment(repo, issue_number: int, body: str):
    """Добавляет комментарий к issue"""
    try:
        issue = repo.get_issue(number=issue_number)
        issue.create_comment(body)
        log.info("💬 Comment added to issue #%s", issue_number)
    except Exception as e:
        log.error("Failed to add comment: %s", e)

def _strip_code_fences(text: str) -> str:
    """Удаляет markdown ```блоки```"""
    t = (text or "").strip()
    if t.startswith("```"):
        lines = t.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return t

def extract_json_object(text: str) -> dict:
    """Извлекает JSON объект из текста (с поддержкой разных форматов)"""
    if not text:
        raise ValueError("Empty text, cannot extract JSON")
    
    # 1) Пробуем напрямую парсить
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
    # 2) Снимаем markdown коды-блоки
    s = _strip_code_fences(text)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    
    # 3) Ищем первый { и правильно считаем скобки
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in response")
    
    depth = 0
    last = start
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                last = i + 1
                break
    
    json_str = text[start:last]
    return json.loads(json_str)

def openai_api_call(system_prompt: str, user_prompt: str) -> dict:
    """Вызов OpenAI API (GPT-5) с парсингом JSON и ретраями"""
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set")
    
    client = OpenAI(api_key=OPENAI_API_KEY)
    
    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            response = client.chat.completions.create(
                model="gpt-5",
                temperature=1,
                max_completion_tokens=2000,  # GPT-5 использует max_completion_tokens
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
            )
            
            response_text = response.choices[0].message.content
            log.info("✓ GPT-5 API call successful (attempt %d/%d)", attempt + 1, max_retries + 1)
            
            # Извлекаем JSON
            try:
                result = extract_json_object(response_text)
                log.info("✓ JSON extracted successfully")
                return result
            except Exception as e:
                log.error("Failed to extract JSON: %s", e)
                preview = response_text[:1000] if response_text else "(empty)"
                log.error("Response preview:\n%s", preview)
                
                if attempt < max_retries:
                    log.warning("Retrying... (attempt %d/%d)", attempt + 2, max_retries + 1)
                    continue
                else:
                    raise ValueError(f"Invalid JSON in response after {max_retries + 1} attempts: {e}")
            
        except Exception as e:
            log.error("GPT-5 API error (attempt %d/%d): %s", attempt + 1, max_retries + 1, e)
            
            if attempt < max_retries:
                log.warning("Retrying...")
                continue
            else:
                raise

def safe_path(path_str: str) -> Path:
    """Проверяет путь на безопасность"""
    p = Path(path_str).as_posix().lstrip("/")
    p = Path(p)
    for f in FORBIDDEN_PATHS:
        if p.as_posix().startswith(f):
            raise ValueError(f"Path '{p}' is forbidden")
    if ".." in p.parts:
        raise ValueError(f"Path '{p}' escapes repo")
    return p

def apply_changes_locally(repo_root: Path, changes: list[dict]) -> list[str]:
    """Применяет изменения к файлам"""
    if not isinstance(changes, list):
        raise ValueError("Changes must be a list")
    
    if len(changes) > ALLOWED_MAX_FILES:
        raise ValueError(f"Too many files: {len(changes)} (max {ALLOWED_MAX_FILES})")

    changed_paths = []
    
    for ch in changes:
        if not isinstance(ch, dict):
            log.warning("Skipping non-dict change: %s", ch)
            continue
        
        path = safe_path((ch.get("path") or "").strip())
        op = (ch.get("op") or ch.get("action") or "update").lower()
        content = ch.get("content", "")

        if not path or not op:
            log.warning("Skipping invalid change (missing path or op)")
            continue

        # Готовим содержимое
        if isinstance(content, str):
            content_bytes = content.encode("utf-8")
        else:
            content_bytes = json.dumps(content, ensure_ascii=False, indent=2).encode("utf-8")

        if len(content_bytes) > ALLOWED_MAX_BYTES_PER_FILE:
            raise ValueError(f"File '{path}' too large ({len(content_bytes)} bytes)")

        # Создаём директории
        abs_path = repo_root / path
        abs_path.parent.mkdir(parents=True, exist_ok=True)

        # Если файл существует и это create - переключаемся на update
        if op == "create" and abs_path.exists():
            log.info("File %s exists; switching to update", path)
            op = "update"

        if op not in {"create", "update"}:
            raise ValueError(f"Invalid op '{op}' (use create|update)")

        # Пишем файл
        abs_path.write_bytes(content_bytes)
        changed_paths.append(path.as_posix())
        log.info("✏️  %s %s", op.upper(), path)

    if not changed_paths:
        raise ValueError("No files were changed")
    
    return changed_paths

def git_operations(branch: str, changed_paths: list[str], commit_message: str) -> None:
    """Создаёт ветку, коммитит и пушит"""
    repo = git.Repo(Path(".").resolve())
    
    # Переходим на main/master и обновляем
    default_branch = repo.default_branch or "main"
    repo.git.checkout(default_branch)
    repo.remotes.origin.fetch()
    repo.git.pull("--ff-only", "origin", default_branch)
    
    # Создаём новую ветку
    repo.git.checkout("-b", branch)
    log.info("✓ Branch created: %s", branch)
    
    # Коммитим
    repo.index.add(changed_paths)
    repo.index.commit(commit_message or "AI: apply changes")
    log.info("✓ Changes committed")
    
    # Пушим
    origin = repo.remote(name="origin")
    origin.push(refspec=f"{branch}:{branch}")
    log.info("⬆️  Pushed branch '%s'", branch)

def create_pull_request(gh_repo, branch: str, base: str, title: str, body: str):
    """Создаёт Pull Request"""
    pr = gh_repo.create_pull(
        title=title,
        body=body,
        head=branch,
        base=base
    )
    log.info("✅ PR created: #%s", pr.number)
    log.info("📍 %s", pr.html_url)
    return pr

def collect_repo_context(root: Path, files: list[str]) -> str:
    """Собирает контекст репо для промпта"""
    out = ["Repository context (truncated):"]
    for rel in files:
        p = root / rel
        if p.exists() and p.is_file():
            try:
                txt = p.read_text(encoding="utf-8", errors="ignore")[:3000]
            except Exception:
                txt = "(binary or unreadable)"
            out.append(f"\n--- FILE: {rel} ---\n{txt}\n--- END ---")
        else:
            out.append(f"\n--- FILE: {rel} (not found) ---")
    return "\n".join(out)

def fallback_change(issue_title: str) -> list[dict]:
    """Fallback: если агент ничего не вернул - создаём минимальный файл"""
    content = (
        "# AI Agent Plan\n\n"
        f"**Issue:** {issue_title}\n\n"
        "## What to do\n"
        "1. Review requirements\n"
        "2. Implement solution\n"
        "3. Add tests\n"
    )
    return [{
        "path": "docs/ai_plan.md",
        "op": "create",
        "content": content
    }]

# ======================== MAIN ==========================
def main():
    log.info("=" * 60)
    log.info("🚀 GitHub AI Agent Starting (GPT-5)")
    log.info("=" * 60)

    # Проверяем обязательные переменные
    if not REPO_NAME:
        raise RuntimeError("REPO_NAME is not set")
    if not GITHUB_TOKEN:
        raise RuntimeError("GITHUB_TOKEN is not set")
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set")

    log.info("Repository: %s", REPO_NAME)
    
    # Получаем номер issue
    issue_number = get_issue_number()
    
    if issue_number is None:
        log.info("ℹ️ ISSUE_NUMBER not provided - searching for open issues with label 'ai-agent'")
        gh = gh_client()
        gh_repo = gh.get_repo(REPO_NAME)
        
        try:
            label = gh_repo.get_label("ai-agent")
            issues = gh_repo.get_issues(state="open", labels=[label])
            
            if issues.totalCount == 0:
                log.info("ℹ️ No open issues with label 'ai-agent'. Exiting.")
                return
            
            issue = next(iter(issues))
            issue_number = issue.number
            log.info("🔎 Selected issue #%s: %s", issue_number, issue.title)
        except Exception as e:
            log.info("ℹ️ Cannot find issues: %s. Exiting.", e)
            return
    else:
        gh = gh_client()
        gh_repo = gh.get_repo(REPO_NAME)
        issue = gh_repo.get_issue(number=issue_number)
        log.info("Processing issue #%s: %s", issue_number, issue.title)

    issue_title = issue.title or ""
    issue_body = issue.body or ""
    base_branch = gh_repo.default_branch or "main"

    # Уведомляем что начали
    add_issue_comment(gh_repo, issue_number, "🤖 AI Agent начал анализ задачи…")

    # Собираем контекст репо
    repo_root = Path(".").resolve()
    context_text = collect_repo_context(repo_root, [
        "README.md",
        "requirements.txt",
        "setup.py",
    ])

    # Готовим промпты для GPT-5
    system_prompt = (
        "You are an expert autonomous Python engineer working as a GitHub CI bot.\n"
        "Your task: analyze GitHub issues and propose concrete, production-ready code changes.\n\n"
        "STRICT REQUIREMENTS:\n"
        "1. RETURN ONLY A VALID MINIFIED JSON OBJECT\n"
        "2. NO prose, NO markdown, NO backticks\n"
        "3. The JSON must have this exact schema:\n"
        '{\n'
        '  "plan_markdown": "string (brief markdown plan of what you will do)",\n'
        '  "changes": [{"path": "file_path", "op": "create|update", "content": "full file content"}],\n'
        '  "summary_commit_message": "string (descriptive git commit message)"\n'
        '}\n\n'
        "CRITICAL REQUIREMENTS:\n"
        "- changes array MUST contain at least 1 item (non-empty)\n"
        "- If no obvious code changes needed: create 'docs/ai_analysis.md' with detailed analysis\n"
        "- No more than 12 files per request\n"
        "- Each file content must be <= 200KB\n"
        "- Only create or update operations - NEVER delete\n"
        "- Include all necessary imports and complete, runnable code\n"
        "- Ensure paths use forward slashes and are relative to repo root\n"
        "- Return ONLY the JSON object - absolutely nothing else\n"
    )
    
    user_prompt = (
        f"Analyze this GitHub issue and provide concrete code changes.\n\n"
        f"ISSUE TITLE: {issue_title}\n\n"
        f"ISSUE BODY:\n{issue_body}\n\n"
        f"REPOSITORY CONTEXT:\n{context_text}\n\n"
        f"Your response MUST be a single, valid JSON object with no other text.\n"
        f"Ensure the 'changes' array has at least one item.\n"
        f"Return ONLY the JSON, nothing else."
    )

    # Вызываем GPT-5
    try:
        log.info("🧠 Calling GPT-5 API...")
        log.info("Model: gpt-5")
        log.info("Max tokens: 2000")
        llm_response = openai_api_call(system_prompt, user_prompt)
        log.info("✓ GPT-5 response received and parsed")
    except Exception as e:
        log.error("GPT-5 call failed: %s", e)
        add_issue_comment(gh_repo, issue_number, f"❌ GPT-5 API Error: {e}")
        raise

    # Извлекаем данные
    changes = llm_response.get("changes", [])
    plan_md = (llm_response.get("plan_markdown") or "").strip()
    summary_commit = (llm_response.get("summary_commit_message") or "AI: apply changes").strip()

    # Проверка: есть ли изменения?
    if not isinstance(changes, list) or not changes:
        log.warning("⚠️ No changes returned - using fallback")
        changes = fallback_change(issue_title)
        if not plan_md:
            plan_md = "Fallback: created docs/ai_plan.md"
        summary_commit = "docs: add ai_plan.md (fallback)"

    # Публикуем план
    if plan_md:
        add_issue_comment(gh_repo, issue_number, f"📊 **План:**\n\n{plan_md}")

    # Применяем изменения
    try:
        log.info("Applying %d changes...", len(changes))
        changed_paths = apply_changes_locally(repo_root, changes)
        log.info("✓ Changes applied: %s", changed_paths)
    except Exception as e:
        log.error("Failed to apply changes: %s", e)
        add_issue_comment(gh_repo, issue_number, f"❌ Failed to apply changes: {e}")
        raise

    # Git операции
    branch = f"ai-issue-{issue_number}"
    try:
        log.info("Performing git operations...")
        git_operations(branch, changed_paths, summary_commit)
    except Exception as e:
        log.error("Git operations failed: %s", e)
        add_issue_comment(gh_repo, issue_number, f"❌ Git error: {e}")
        raise

    # Создаём PR
    pr_title = f"[AI] {issue_title}".strip() or f"[AI] Issue #{issue_number}"
    pr_body = (
        f"🤖 Automated by AI Agent\n\n"
        f"**Linked issue:** #{issue_number}\n\n"
        f"### Plan\n{plan_md or '(no plan)'}\n\n"
        f"### Files changed\n" +
        "\n".join([f"- `{ch.get('path')}`" for ch in changes[:10]])
    )

    try:
        pr = create_pull_request(gh_repo, branch, base_branch, pr_title, pr_body)
        log.info("✓ PR created successfully")
    except Exception as e:
        log.error("Failed to create PR: %s", e)
        add_issue_comment(gh_repo, issue_number, f"❌ PR creation error: {e}")
        raise

    # Финальный комментарий
    add_issue_comment(
        gh_repo,
        issue_number,
        f"✅ **PR готов!**\n\n"
        f"[#{pr.number}]({pr.html_url})\n\n"
        f"Пожалуйста, проверьте изменения."
    )

    log.info("=" * 60)
    log.info("✅ Agent finished successfully")
    log.info("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.error("❌ Agent failed: %s", e)
        log.error(traceback.format_exc())
        sys.exit(1)


