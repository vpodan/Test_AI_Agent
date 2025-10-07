"""
Simple AI Agent for GitHub
Версия для быстрого старта
"""

import os
import sys
import json
import logging
from pathlib import Path
from datetime import datetime

from github import Github
from anthropic import Anthropic

# Настройка логирования
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / f"agent_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class SimpleGitHubAgent:
    def __init__(self):
        self.github = Github(os.environ['GITHUB_TOKEN'])
        self.repo = self.github.get_repo(os.environ['REPO_NAME'])
        self.claude = Anthropic(api_key=os.environ['OPEN_AI_TOKEN'])
        self.issue_number = os.environ.get('ISSUE_NUMBER')
        
        logger.info(f"🤖 Agent initialized for: {os.environ['REPO_NAME']}")
    
    def run(self):
        """Основной метод"""
        try:
            if self.issue_number:
                issue = self.repo.get_issue(int(self.issue_number))
                self.process_issue(issue)
            else:
                self.process_all_issues()
        except Exception as e:
            logger.error(f"❌ Error: {e}", exc_info=True)
            raise
    
    def process_all_issues(self):
        """Обрабатывает все open issues с label ai-agent"""
        try:
            label = self.repo.get_label('ai-agent')
        except:
            logger.error("Label 'ai-agent' не найден! Создайте его в Settings → Labels")
            return
        
        issues = self.repo.get_issues(state='open', labels=[label])
        
        for issue in issues:
            if not self.is_processed(issue):
                logger.info(f"📋 Processing issue #{issue.number}")
                self.process_issue(issue)
    
    def process_issue(self, issue):
        """Обрабатывает один issue"""
        try:
            # Отмечаем начало
            self.comment(issue, "🤖 AI Agent начинает анализ задачи...")
            
            # Анализ
            logger.info("Analyzing task...")
            analysis = self.analyze_task(issue)
            
            self.comment(issue, f"**📊 Анализ:**\n\n{analysis}")
            
            # Для демо просто создадим комментарий с решением
            logger.info("Generating solution...")
            solution = self.generate_solution(issue, analysis)
            
            self.comment(
                issue,
                f"**💡 Предлагаемое решение:**\n\n{solution}\n\n"
                f"---\n*Это демо-версия агента. Полная версия создаст PR с кодом.*"
            )
            
            logger.info(f"✅ Issue #{issue.number} processed")
            
        except Exception as e:
            logger.error(f"Error processing issue: {e}")
            self.comment(issue, f"❌ Ошибка: {str(e)}")
    
    def analyze_task(self, issue):
        """Анализирует задачу"""
        prompt = f"""Проанализируй эту задачу для Python проекта:

**Заголовок:** {issue.title}
**Описание:** {issue.body or 'Не указано'}

Напиши краткий анализ (2-3 предложения):
- Что нужно сделать
- Какие файлы затронуты
- Сложность задачи"""

        response = self.claude.messages.create(
            model="gpt-5-codex",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )
        
        return response.content[0].text
    
    def generate_solution(self, issue, analysis):
        """Генерирует решение"""
        prompt = f"""Предложи решение для этой задачи:

**Задача:** {issue.title}
{issue.body or ''}

**Анализ:** {analysis}

Напиши:
1. Пошаговый план решения
2. Какой код нужно написать (краткое описание)
3. Какие файлы создать/изменить

Будь кратким и конкретным."""

        response = self.claude.messages.create(
            model="gpt-5-codex",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )
        
        return response.content[0].text
    
    def comment(self, issue, text):
        """Добавляет комментарий"""
        issue.create_comment(text)
        logger.info(f"Comment added to issue #{issue.number}")
    
    def is_processed(self, issue):
        """Проверяет, был ли issue уже обработан"""
        comments = issue.get_comments()
        for comment in comments:
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
