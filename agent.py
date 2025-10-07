"""
Simple AI Agent for GitHub
Версия для быстрого старта (OpenAI)
"""

import os
import sys
import logging
from pathlib import Path
from datetime import datetime

from github import Github
from openai import OpenAI

# === Логирование ===
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / f"agent_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


# === Утилиты модели ===
def resolve_openai_key() -> str:
    """
    Поддерживаем оба названия: OPENAI_API_KEY и OPEN_AI_TOKEN.
    Берём первое доступное.
    """
    key = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPEN_AI_TOKEN")
    if not key:
        raise RuntimeError("OpenAI API key not found. Set OPENAI_API_KEY or OPEN_AI_TOKEN.")
    return key


def resolve_model(name: str | None) -> str:
    """
    Алиас 'codex' маппится на актуальную кодовую модель OpenAI.
    При желании замени на gpt-4o-mini или gpt-4.1.
    """
    if not name:
        return "gpt-4.1-mini"
    n = name.strip().lower()
    if n in {"codex", "code-davinci", "code-davinci-002"}:
        return "gpt-4.1-mini"  # ← алиас под современную кодовую модель
    return name


class SimpleGitHubAgent:
    def __init__(self):
        # GitHub
        gh_token = os.environ["GITHUB_TOKEN"]
        repo_name = os.environ["REPO_NAME"]

        self.github = Github(gh_token)
        self.repo = self.github.get_repo(repo_name)

        # OpenAI
        api_key = resolve_openai_key()
        self.openai = OpenAI(api_key=api_key)

        # Опциональный номер issue
        self.issue_number = os.environ.get("ISSUE_NUMBER")

        # Модель (можно передать через ENV MODEL_NAME, например 'codex')
        self.model_name = resolve_model(os.environ.get("MODEL_NAME", "codex"))

        logger.info(f"🤖 Agent initialized for: {repo_name}")
        logger.info(f"🧠 Using OpenAI model: {self.model_name}")

    # ==== Основной цикл ====
    def run(self):
        try:
            if self.issue_number:
                issue = self.repo.get_issue(int(self.issue_number))
                self.process_issue(issue)
            else:
                self.process_all_issues()
        except Exception as e:
            logger.error(f"❌ Error in run(): {e}", exc_info=True)
            raise

    def process_all_issues(self):
        """Обрабатывает все open issues с label ai-agent."""
        try:
            label = self.repo.get_label("ai-agent")
        except Exception:
            logger.error("Label 'ai-agent' не найден! Создайте его в Settings → Labels")
            return

        issues = self.repo.get_issues(state="open", labels=[label])
        count = 0
        for issue in issues:
            if not self.is_processed(issue):
                count += 1
                logger.info(f"📋 Processing issue #{issue.number}")
                self.process_issue(issue)

        if count == 0:
            logger.info("ℹ️ Нет открытых issues с лейблом 'ai-agent' для обработки.")

    def process_issue(self, issue):
        """Обрабатывает один issue."""
        try:
            self.comment(issue, "🤖 AI Agent начинает анализ задачи...")

            logger.info("Analyzing task...")
            analysis = self.analyze_task(issue)
            self.comment(issue, f"**📊 Анализ:**\n\n{analysis}")

            logger.info("Generating solution...")
            solution = self.generate_solution(issue, analysis)
            self.comment(
                issue,
                f"**💡 Предлагаемое решение:**\n\n{solution}\n\n"
                f"---\n*Это демо-версия агента. Полная версия создаст PR с кодом.*",
            )

            logger.info(f"✅ Issue #{issue.number} processed")
        except Exception as e:
            logger.error(f"Error processing issue #{issue.number}: {e}", exc_info=True)
            self.comment(issue, f"❌ Ошибка: {str(e)}")

    # ==== Взаимодействие с OpenAI ====
    def _chat(self, prompt: str, max_tokens: int = 800) -> str:
        """
        Унифицированный вызов Chat Completions.
        """
        resp = self.openai.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content.strip()

    def analyze_task(self, issue):
        """Анализирует задачу."""
        prompt = f"""Проанализируй задачу для Python-проекта.

Заголовок: {issue.title}
Описание: {issue.body or 'Не указано'}

Дай краткий анализ (2-3 предложения):
- Что нужно сделать
- Какие файлы/модули вероятно затронуты
- Примерная сложность (низкая/средняя/высокая) и риски
"""
        return self._chat(prompt, max_tokens=500)

    def generate_solution(self, issue, analysis):
        """Генерирует решение."""
        prompt = f"""Предложи решение для задачи.

Задача: {issue.title}
{issue.body or ''}

Анализ: {analysis}

Напиши:
1) Пошаговый план решения (минимальные атомарные шаги)
2) Какой код нужно написать/изменить (краткое описание)
3) Какие файлы создать/изменить
4) Набор базовых тестов (кратко)
"""
        return self._chat(prompt, max_tokens=900)

    # ==== GitHub утилиты ====
    def comment(self, issue, text: str):
        issue.create_comment(text)
        logger.info(f"💬 Comment added to issue #{issue.number}")

    def is_processed(self, issue) -> bool:
        for comment in issue.get_comments():
            if "🤖 AI Agent начинает анализ" in comment.body:
                return True
        return False


def main():
    logger.info("=" * 50)
    logger.info("🚀 GitHub AI Agent Starting")
    logger.info("=" * 50)

    try:
        agent = SimpleGitHubAgent()
        agent.run()
        logger.info("✅ Agent finished successfully")
    except Exception as e:
        logger.error(f"❌ Agent failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
