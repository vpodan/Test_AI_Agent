# test_embedding_models.py
"""
Скрипт для тестирования качества разных моделей embeddings и промптов
"""

import os
from real_estate_embedding_function import get_embedding_function, create_listing_text_for_embedding
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

# Пример данных для теста
sample_listing = {
    "title": "Просторная 3-комнатная квартира в центре",
    "description": "Квартира с ремонтом, балконом и видом на парк.",
    "features_by_category": {"балкон": True, "ремонт": "современный"},
    "city": "Варшава",
    "district": "Мокотов",
    "neighbourhood": "",
}

sample_queries = [
    "Ищу квартиру с балконом и ремонтом в Варшаве",
    "3-комнатная квартира в центре с видом на парк",
    "Квартира с современным ремонтом и балконом"
]

embedding_models = [
    "text-embedding-3-large",
    "text-embedding-3-small",
    "text-embedding-ada-002"
]

prompt_styles = [1, 2]


def embed_texts(embedding_func, texts):
    embeddings = []
    for text in texts:
        emb = embedding_func.embed_query(text) if hasattr(embedding_func, 'embed_query') else embedding_func.embed_documents([text])[0]
        embeddings.append(emb)
    return np.array(embeddings)


def main():
    print("🚀 Тестируем разные модели embeddings и стили промптов")
    
    for model in embedding_models:
        print(f"\n=== Модель: {model} ===")
        embedding_func = get_embedding_function(model)
        
        for style in prompt_styles:
            print(f"Промпт стиль: {style}")
            # Создаем embedding для листинга
            listing_text = create_listing_text_for_embedding(sample_listing, prompt_style=style)
            listing_emb = embed_texts(embedding_func, [listing_text])[0]
            
            # Создаем embedding для запросов
            query_embs = embed_texts(embedding_func, sample_queries)
            
            # Считаем косинусное сходство
            sims = cosine_similarity([listing_emb], query_embs)[0]
            for q, sim in zip(sample_queries, sims):
                print(f"Запрос: '{q}' -> Косинусное сходство: {sim:.4f}")

if __name__ == "__main__":
    main()
