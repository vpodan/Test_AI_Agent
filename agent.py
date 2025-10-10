#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Autonomous GitHub AI Agent (GPT-5 version) — self-contained

ENV variables:
  GITHUB_TOKEN      - GitHub Personal Access Token (repo + workflow)
  OPENAI_API_KEY    - OpenAI API key (optional if OPEN_AI_TOKEN is set)
  OPEN_AI_TOKEN     - OpenAI API key fallback
  OPENAI_MODEL      - model name (default: gpt-5)
  REPO_NAME         - owner/repo (e.g., username/repository)
  ISSUE_NUMBER      - Issue number to process (optional; if not set, will search label 'ai-agent')
"""

import os
import sys
import json
import logging
import traceback
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any

# ======================== УСТАНОВКА ЗАВИСИМОСТЕЙ ==========================
REQUIRED_PKGS = ["PyGithub>=2.3.0", "GitPython>=3.1.43", "openai>=1.53.0"]

def ensure_deps() -> None:
    missing = []
    try:
        import github  # noqa
    except Exception:
        missing.append("PyGithub>=2.3.0")
    try:
        import git  # noqa
    except Exception:
        missing.append("GitPython>=3.1.43")
    try:
        import openai  # noqa
    except Exception:
        missing.append("openai>=1.53.0")

    if missing:
        print(f"[deps] Installing missing packages: {', '.join(missing)}")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-U", *missing], stdout=sys.stdout)

ensure_deps()

# ======================== ИМПОРТЫ ПОСЛЕ УСТАНОВКИ =========================
import git
from github import Github, Auth  # type: ignore
from openai import OpenAI        # type: ignore

# ======================== ЛОГИРОВАНИЕ ==========================
LOG_DIR = Path("logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)
log_file = LOG_DIR / f"agent_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler(log_file, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("agent")

# ======================== КОНСТАНТЫ/ENV ==========================
REPO_NAME = os.environ.get("REPO_NAME")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
# корректная цепочка получения ключа
OPENAI_API_KEY = (
    os.environ.get("OPENAI_API_KEY") or
    os.environ.get("OPEN_AI_TOKEN") or
    os.environ.get("OPENAI") or
    os.environ.get("OPENAI_TOKEN")
)
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5")

ALLOWED_MAX_FILES = 12
ALLOWED_MAX_BYTES_PER_FILE = 200_000
FORBIDDEN_PATHS = {".git", ".github/workflows", ".github/actions"}

# ======================== УТИЛИТЫ ==========================
def get_issue_number() -> Optional[int]:
    v = os.environ.get("ISSUE_NUMBER")
    if v:
        try:
            return int(v)
        except ValueError:
            pass
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
    if not GITHUB_TOKEN:
        raise RuntimeError("GITHUB_TOKEN is not set")
    return Github(auth=Auth.Token(GITHUB_TOKEN))

def add_issue_comment(repo, issue_number: int, body: str) -> None:
    try:
        issue = repo.get_issue(number=issue_number)
        issue.create_comment(body)
        log.info("💬 Comment added to issue #%s", issue_number)
    except Exception as e:
        log.error("Failed to add comment: %s", e)

def _strip_code_fences(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        lines = t.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return t

def extract_json_object(text: str) -> Dict[str, Any]:
    if not text:
        raise ValueError("Empty text, cannot extract JSON")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    s = _strip_code_fences(text)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
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

def openai_api_call(system_prompt: str, user_prompt: str) -> Dict[str, Any]:
    """
    GPT-5 через chat.completions + tool calling (жёсткая схема).
    Возвращает dict из tool_calls[0].function.arguments.
    """
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY / OPEN_AI_TOKEN is not set")
    client = OpenAI(api_key=OPENAI_API_KEY)

    tool = {
        "type": "function",
        "function": {
            "name": "submit_agent_output",
            "description": "Return the agent's final JSON payload.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": ["plan_markdown", "changes", "summary_commit_message"],
                "properties": {
                    "plan_markdown": {"type": "string"},
                    "changes": {
                        "type": "array",
                        "maxItems": 12,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["path", "op", "content"],
                            "properties": {
                                "path": {"type": "string"},
                                "op": {"type": "string", "enum": ["create", "update"]},
                                # КРИТИЧЕСКОЕ ИЗМЕНЕНИЕ: только string
                                "content": {"type": "string", "description": "Full file content as UTF-8 text. If non-text, provide JSON-serialized string."}
                            },
                        },
                    },
                    "summary_commit_message": {"type": "string"},
                },
            },
        },
    }

    max_retries = 2
    last_err: Optional[Exception] = None

    for attempt in range(1, max_retries + 2):
        try:
            rsp = client.chat.completions.create(
                model=os.environ.get("OPENAI_MODEL", "gpt-5"),
                temperature=0,
                # для gpt-5 нужен именно max_completion_tokens
                max_completion_tokens=2000,
                tools=[tool],
                tool_choice={"type": "function", "function": {"name": "submit_agent_output"}},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                    # Можно дополнительно поджать требования:
                    {"role": "system", "content": "Return ONLY via the tool call. The tool's 'content' field must be a string (serialize any non-text to JSON)."}
                ],
            )

            choice = rsp.choices[0]
            tcs = getattr(choice.message, "tool_calls", None) or []
            if not tcs:
                raise ValueError("Model did not return tool_calls")

            fn = tcs[0].function
            args_raw = fn.arguments or ""
            if not isinstance(args_raw, str) or not args_raw.strip():
                raise ValueError("Empty tool call arguments")

            payload = json.loads(args_raw)

            # Быстрая валидация и принудительная сериализация (на всякий)
            changes = payload.get("changes", [])
            if not isinstance(changes, list) or len(changes) == 0:
                raise ValueError("changes must be a non-empty array")
            if len(changes) > ALLOWED_MAX_FILES:
                raise ValueError(f"Too many files: {len(changes)} (max {ALLOWED_MAX_FILES})")

            for ch in changes:
                if not isinstance(ch, dict):
                    raise ValueError("Invalid change item")
                c = ch.get("content", "")
                if not isinstance(c, str):
                    ch["content"] = json.dumps(c, ensure_ascii=False, indent=2)

            return payload

        except Exception as e:
            last_err = e
            log.error("OpenAI tool-calls error (attempt %d): %s", attempt, e)

    raise RuntimeError(f"OpenAI tool-calls failed after retries: {last_err}")


    def _extract_text_from_response(resp) -> str:
        # SDK v2: удобный хелпер
        txt = getattr(resp, "output_text", None)
        if isinstance(txt, str) and txt.strip():
            return txt
        # Универсальный обход структуры output
        out = getattr(resp, "output", None)
        if isinstance(out, list):
            for item in out:
                # Ожидаем item.type == "message"
                content = getattr(item, "content", None)
                if isinstance(content, list):
                    for c in content:
                        # c может иметь .text.value
                        text_obj = getattr(c, "text", None)
                        if isinstance(text_obj, dict):
                            val = text_obj.get("value") or text_obj.get("text")
                            if isinstance(val, str) and val.strip():
                                return val
                        elif isinstance(text_obj, str) and text_obj.strip():
                            return text_obj
        return ""

    last_err = None

    # Попытка через Responses API с json_schema
    try:
        resp = client.responses.create(
            model=os.environ.get("OPENAI_MODEL", "gpt-5"),
            reasoning={"effort": "medium"},
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_output_tokens=2000,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "AgentOutput",
                    "strict": True,
                    "schema": schema,
                },
            },
        )
        txt = _extract_text_from_response(resp)
        if not txt.strip():
            raise ValueError("Empty text from Responses API")
        return extract_json_object(txt)
    except Exception as e:
        last_err = e
        log.warning("Responses API failed, falling back to chat.completions: %s", e)

    # 2) Фолбэк: chat.completions с требованием JSON-объекта
    try:
        rsp = client.chat.completions.create(
            model=os.environ.get("OPENAI_MODEL", "gpt-5"),
            temperature=1,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            # у chat.completions корректный параметр — max_tokens:
            max_tokens=2000,
        )
        txt = (rsp.choices[0].message.content or "").strip()
        if not txt:
            raise ValueError("Empty content from chat.completions")
        return extract_json_object(txt)
    except Exception as e2:
        raise RuntimeError(f"OpenAI call failed (Responses + Chat fallback): {last_err} / {e2}")

def safe_path(path_str: str) -> Path:
    p = Path(path_str).as_posix().lstrip("/")
    p = Path(p)
    for f in FORBIDDEN_PATHS:
        if p.as_posix().startswith(f):
            raise ValueError(f"Path '{p}' is forbidden")
    if ".." in p.parts:
        raise ValueError(f"Path '{p}' escapes repo")
    return p

def apply_changes_locally(repo_root: Path, changes: List[Dict[str, Any]]) -> List[str]:
    if not isinstance(changes, list):
        raise ValueError("Changes must be a list")
    if len(changes) > ALLOWED_MAX_FILES:
        raise ValueError(f"Too many files: {len(changes)} (max {ALLOWED_MAX_FILES})")

    changed_paths: List[str] = []
    for ch in changes:
        if not isinstance(ch, dict):
            log.warning("Skip non-dict change: %s", ch)
            continue
        path = safe_path((ch.get("path") or "").strip())
        op = (ch.get("op") or ch.get("action") or "update").lower()
        content = ch.get("content", "")

        if not path or not op:
            log.warning("Skip invalid change (missing path/op)")
            continue

        if isinstance(content, str):
            content_bytes = content.encode("utf-8")
        else:
            content_bytes = json.dumps(content, ensure_ascii=False, indent=2).encode("utf-8")

        if len(content_bytes) > ALLOWED_MAX_BYTES_PER_FILE:
            raise ValueError(f"File '{path}' too large ({len(content_bytes)} bytes)")

        abs_path = repo_root / path
        abs_path.parent.mkdir(parents=True, exist_ok=True)

        if op == "create" and abs_path.exists():
            log.info("File %s exists; switching to update", path)
            op = "update"
        if op not in {"create", "update"}:
            raise ValueError(f"Invalid op '{op}' (use create|update)")

        abs_path.write_bytes(content_bytes)
        changed_paths.append(path.as_posix())
        log.info("✏️  %s %s", op.upper(), path)

    if not changed_paths:
        raise ValueError("No files were changed")
    return changed_paths

def git_operations(branch: str, changed_paths: List[str], commit_message: str, base_branch: str) -> None:
    repo = git.Repo(Path(".").resolve())
    # checkout & fast-forward base
    repo.git.fetch("origin", base_branch)
    repo.git.checkout(base_branch)
    repo.git.pull("--ff-only", "origin", base_branch)

    # new branch
    try:
        repo.git.checkout("-b", branch)
    except git.GitCommandError:
        # branch may already exist locally — reset to base
        repo.git.checkout(branch)
        repo.git.reset("--hard", f"origin/{base_branch}")
    log.info("✓ Branch ready: %s", branch)

    repo.index.add(changed_paths)
    repo.index.commit(commit_message or "AI: apply changes")
    log.info("✓ Changes committed")

    origin = repo.remote(name="origin")
    origin.push(refspec=f"{branch}:{branch}", force=True)
    log.info("⬆️  Pushed branch '%s'", branch)

def create_pull_request(gh_repo, branch: str, base: str, title: str, body: str):
    # Reuse existing PR if already open
    for pr in gh_repo.get_pulls(state="open", head=f"{gh_repo.owner.login}:{branch}", base=base):
        log.info("PR already exists: #%s %s", pr.number, pr.html_url)
        return pr
    pr = gh_repo.create_pull(title=title, body=body, head=branch, base=base)
    log.info("✅ PR created: #%s", pr.number)
    log.info("📍 %s", pr.html_url)
    return pr

def collect_repo_context(root: Path, files: List[str]) -> str:
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

def fallback_change(issue_title: str) -> List[Dict[str, Any]]:
    content = (
        "# AI Agent Plan\n\n"
        f"**Issue:** {issue_title}\n\n"
        "## What to do\n"
        "1. Review requirements\n"
        "2. Implement solution\n"
        "3. Add tests\n"
    )
    return [{"path": "docs/ai_plan.md", "op": "create", "content": content}]

# ======================== MAIN ==========================
def main():
    log.info("=" * 60)
    log.info("🚀 GitHub AI Agent Starting")
    log.info("=" * 60)

    if not REPO_NAME:
        raise RuntimeError("REPO_NAME is not set")
    if not GITHUB_TOKEN:
        raise RuntimeError("GITHUB_TOKEN is not set")
    if not OPENAI_API_KEY:
        # Отдельное лог-сообщение: в твоём логе OPENAI_API_KEY пустой, но есть OPEN_AI_TOKEN — мы это уже учли
        raise RuntimeError("No OpenAI key found in OPENAI_API_KEY/OPEN_AI_TOKEN")

    log.info("Repository: %s", REPO_NAME)
    log.info("OpenAI model: %s", OPENAI_MODEL)
    log.info("OpenAI key source: %s", "OPENAI_API_KEY" if os.environ.get("OPENAI_API_KEY") else "OPEN_AI_TOKEN/other")

    gh = gh_client()
    gh_repo = gh.get_repo(REPO_NAME)
    base_branch = gh_repo.default_branch or "main"

    issue_number = get_issue_number()
    if issue_number is None:
        log.info("ℹ️ ISSUE_NUMBER not provided - searching for open issues with label 'ai-agent'")
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
        issue = gh_repo.get_issue(number=issue_number)
        log.info("Processing issue #%s: %s", issue_number, issue.title)

    issue_title = issue.title or ""
    issue_body = issue.body or ""

    add_issue_comment(gh_repo, issue_number, "🤖 AI Agent начал анализ задачи…")

    repo_root = Path(".").resolve()
    context_text = collect_repo_context(repo_root, ["README.md", "requirements.txt", "setup.py"])

    system_prompt = (
        "You are an expert autonomous Python engineer working as a GitHub CI bot.\n"
        "Your task: analyze GitHub issues and propose concrete, production-ready code changes.\n\n"
        "STRICT REQUIREMENTS:\n"
        "1. RETURN ONLY A VALID MINIFIED JSON OBJECT\n"
        "2. NO prose, NO markdown, NO backticks\n"
        "3. The JSON must have this exact schema:\n"
        '{'
        '"plan_markdown":"string",'
        '"changes":[{"path":"file_path","op":"create|update","content":"full file content"}],'
        '"summary_commit_message":"string"'
        '}\n'
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

    try:
        log.info("🧠 Calling OpenAI...")
        llm_response = openai_api_call(system_prompt, user_prompt)
        log.info("✓ OpenAI response parsed")
    except Exception as e:
        log.error("GPT API failed: %s", e)
        add_issue_comment(gh_repo, issue_number, f"❌ GPT API Error: {e}")
        raise

    changes = llm_response.get("changes", [])
    plan_md = (llm_response.get("plan_markdown") or "").strip()
    summary_commit = (llm_response.get("summary_commit_message") or "AI: apply changes").strip()

    if not isinstance(changes, list) or not changes:
        log.warning("⚠️ No changes returned - using fallback")
        changes = fallback_change(issue_title)
        if not plan_md:
            plan_md = "Fallback: created docs/ai_plan.md"
        summary_commit = "docs: add ai_plan.md (fallback)"

    if plan_md:
        add_issue_comment(gh_repo, issue_number, f"📊 **План:**\n\n{plan_md}")

    try:
        log.info("Applying %d changes...", len(changes))
        changed_paths = apply_changes_locally(repo_root, changes)
        log.info("✓ Changes applied: %s", changed_paths)
    except Exception as e:
        log.error("Failed to apply changes: %s", e)
        add_issue_comment(gh_repo, issue_number, f"❌ Failed to apply changes: {e}")
        raise

    branch = f"ai-issue-{issue_number}"
    try:
        log.info("Performing git operations...")
        git_operations(branch, changed_paths, summary_commit, base_branch)
    except Exception as e:
        log.error("Git ops failed: %s", e)
        add_issue_comment(gh_repo, issue_number, f"❌ Git error: {e}")
        raise

    pr_title = f"[AI] {issue_title}".strip() or f"[AI] Issue #{issue_number}"
    pr_body = (
        f"🤖 Automated by AI Agent\n\n"
        f"**Linked issue:** #{issue_number}\n\n"
        f"### Plan\n{plan_md or '(no plan)'}\n\n"
        f"### Files changed\n" + "\n".join([f"- `{ch.get('path')}`" for ch in changes[:10]])
    )

    try:
        pr = create_pull_request(gh_repo, branch, base_branch, pr_title, pr_body)
        log.info("✓ PR created successfully")
    except Exception as e:
        log.error("Failed to create PR: %s", e)
        add_issue_comment(gh_repo, issue_number, f"❌ PR creation error: {e}")
        raise

    add_issue_comment(
        gh_repo,
        issue_number,
        f"✅ **PR готов!**\n\n[#{pr.number}]({pr.html_url})\n\nПожалуйста, проверьте изменения."
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


