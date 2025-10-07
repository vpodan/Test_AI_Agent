# real_estate_embedding_function.py
from dotenv import load_dotenv
load_dotenv()

import os
from langchain_openai import OpenAIEmbeddings

def get_embedding_function():
    """Создает функцию для генерации embeddings для объявлений недвижимости"""
    return OpenAIEmbeddings(
        model="text-embedding-3-large",  # Более новая и дешевая модель
        openai_api_key=os.getenv("OPENAI_API_KEY")
    )

def create_listing_text_for_embedding(listing_data):
    """
    Создает текст для embedding из данных объявления
    
    Args:
        listing_data (dict): Документ из MongoDB с данными объявления
        
    Returns:
        str: Подготовленный текст для создания embedding
    """
    text_parts = []
    
    # Заголовок объявления
    if listing_data.get("title"):
        text_parts.append(f"Заголовок: {listing_data['title']}")
    
    # Основное описание
    if listing_data.get("description"):
        text_parts.append(f"Описание: {listing_data['description']}")
    
    # Характеристики по категориям
    if listing_data.get("features_by_category"):
        text_parts.append(f"Характеристики: {listing_data['features_by_category']}")
    
    # Локация для контекста
    location_parts = []
    if listing_data.get("city"):
        location_parts.append(listing_data["city"])
    if listing_data.get("district"):
        location_parts.append(listing_data["district"])
    if listing_data.get("neighbourhood"):
        location_parts.append(listing_data["neighbourhood"])
    
    if location_parts:
        text_parts.append(f"Локация: {', '.join(location_parts)}")
    
    # Объединяем все части
    full_text = "\n".join(text_parts)
    
    return full_text
