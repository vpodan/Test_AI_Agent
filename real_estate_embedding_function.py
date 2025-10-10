# real_estate_embedding_function.py
from dotenv import load_dotenv
load_dotenv()

import os
from langchain_openai import OpenAIEmbeddings

# Supported embedding models
EMBEDDING_MODELS = [
    "text-embedding-3-large",
    "text-embedding-3-small",
    "text-embedding-ada-002"
]

# Default embedding model
DEFAULT_EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-large")


def get_embedding_function(model_name: str = None):
    """Создает функцию для генерации embeddings для объявлений недвижимости"""
    model = model_name or DEFAULT_EMBEDDING_MODEL
    if model not in EMBEDDING_MODELS:
        print(f"[Warning] Model {model} not in supported list, falling back to default {DEFAULT_EMBEDDING_MODEL}")
        model = DEFAULT_EMBEDDING_MODEL
    return OpenAIEmbeddings(
        model=model,  # Выбранная модель
        openai_api_key=os.getenv("OPENAI_API_KEY")
    )


def create_listing_text_for_embedding(listing_data, prompt_style: int = 1):
    """
    Создает текст для embedding из данных объявления
    Args:
        listing_data (dict): Документ из MongoDB с данными объявления
        prompt_style (int): стиль формирования текста (для экспериментов)
    Returns:
        str: Подготовленный текст для создания embedding
    """
    text_parts = []

    if prompt_style == 1:
        # Стандартный стиль
        if listing_data.get("title"):
            text_parts.append(f"Заголовок: {listing_data['title']}")
        if listing_data.get("description"):
            text_parts.append(f"Описание: {listing_data['description']}")
        if listing_data.get("features_by_category"):
            text_parts.append(f"Характеристики: {listing_data['features_by_category']}")
        location_parts = []
        if listing_data.get("city"):
            location_parts.append(listing_data["city"])
        if listing_data.get("district"):
            location_parts.append(listing_data["district"])
        if listing_data.get("neighbourhood"):
            location_parts.append(listing_data["neighbourhood"])
        if location_parts:
            text_parts.append(f"Локация: {', '.join(location_parts)}")

    elif prompt_style == 2:
        # Альтернативный стиль с вопросами
        if listing_data.get("title"):
            text_parts.append(f"Объявление: {listing_data['title']}")
        if listing_data.get("description"):
            text_parts.append(f"Детали: {listing_data['description']}")
        if listing_data.get("features_by_category"):
            text_parts.append(f"Особенности: {listing_data['features_by_category']}")
        location_parts = []
        if listing_data.get("city"):
            location_parts.append(listing_data["city"])
        if listing_data.get("district"):
            location_parts.append(listing_data["district"])
        if listing_data.get("neighbourhood"):
            location_parts.append(listing_data["neighbourhood"])
        if location_parts:
            text_parts.append(f"Расположение: {', '.join(location_parts)}")

    else:
        # По умолчанию fallback к стиль 1
        return create_listing_text_for_embedding(listing_data, prompt_style=1)

    full_text = "\n".join(text_parts)
    return full_text
