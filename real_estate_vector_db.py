# real_estate_vector_db.py
import os
from typing import List, Dict, Optional
from langchain.schema import Document
from langchain_chroma import Chroma
from pymongo import MongoClient
from real_estate_embedding_function import get_embedding_function, create_listing_text_for_embedding

# Константы
CHROMA_PATH = "chroma_real_estate"

# Подключение к MongoDB
client = MongoClient("mongodb://localhost:27017/")
db = client["real_estate"]
collection_rent = db["rent_listings"]
collection_sale = db["sale_listings"]

class RealEstateVectorDB:
    def __init__(self, embedding_model: Optional[str] = None):
        """Инициализация векторной базы данных для недвижимости"""
        self.embedding_function = get_embedding_function(embedding_model)
        self.db = Chroma(
            persist_directory=CHROMA_PATH,
            embedding_function=self.embedding_function,
            collection_metadata={"hnsw:space": "cosine"}  # Используем косинусное расстояние
        )
    
    def add_listing_to_vector_db(self, listing_data: Dict, collection_type: str, prompt_style: int = 1):
        """
        Добавляет одно объявление в векторную базу данных
        
        Args:
            listing_data (dict): Данные объявления из MongoDB
            collection_type (str): 'rent' или 'sale'
            prompt_style (int): стиль формирования текста для embedding
        """
        # Создаем текст для embedding
        text_content = create_listing_text_for_embedding(listing_data, prompt_style=prompt_style)
        
        # Создаем уникальный ID
        listing_id = listing_data.get("_id")
        if not listing_id:
            print(f"Пропускаем объявление без ID: {listing_data}")
            return
        
        # Подготавливаем метаданные для фильтрации
        metadata = {
            "id": listing_id,
            "collection_type": collection_type,  # rent или sale
            "city": listing_data.get("city", ""),
            "district": listing_data.get("district", ""),
            "room_count": listing_data.get("room_count"),
            "price": listing_data.get("price"),
            "building_type": listing_data.get("building_type", ""),
            "has_description": bool(listing_data.get("description")),
            "has_features": bool(listing_data.get("features_by_category"))
        }
        
        # Создаем Document для Chroma
        document = Document(
            page_content=text_content,
            metadata=metadata
        )
        
        # Проверяем, существует ли уже такой документ
        existing = self.db.get(ids=[listing_id], include=[])
        
        if existing['ids']:
            print(f"Объявление {listing_id} уже существует в векторной БД")
            return
        
        # Добавляем в векторную БД
        try:
            self.db.add_documents([document], ids=[listing_id])
            print(f"✅ Добавлено объявление {listing_id} в векторную БД")
        except Exception as e:
            print(f"❌ Ошибка при добавлении {listing_id}: {e}")
    
    def populate_from_mongo(self, limit: Optional[int] = None, embedding_model: Optional[str] = None, prompt_style: int = 1):
        """
        Загружает все объявления из MongoDB в векторную БД
        
        Args:
            limit (int, optional): Ограничение количества записей для теста
            embedding_model (str, optional): модель для embeddings
            prompt_style (int): стиль формирования текста для embedding
        """
        print("🚀 Начинаем загрузку объявлений в векторную БД...")
        
        # Обновляем embedding function если модель указана
        if embedding_model:
            self.embedding_function = get_embedding_function(embedding_model)
            self.db.embedding_function = self.embedding_function
        
        # Загружаем объявления аренды
        print("📍 Загружаем объявления аренды...")
        rent_query = {}
        if limit:
            rent_listings = list(collection_rent.find(rent_query).limit(limit))
        else:
            rent_listings = list(collection_rent.find(rent_query))
        
        print(f"Найдено {len(rent_listings)} объявлений аренды")
        
        for listing in rent_listings:
            self.add_listing_to_vector_db(listing, "rent", prompt_style=prompt_style)
        
        # Загружаем объявления продажи
        print("\n📍 Загружаем объявления продажи...")
        sale_query = {}
        if limit:
            sale_listings = list(collection_sale.find(sale_query).limit(limit))
        else:
            sale_listings = list(collection_sale.find(sale_query))
        
        print(f"Найдено {len(sale_listings)} объявлений продажи")
        
        for listing in sale_listings:
            self.add_listing_to_vector_db(listing, "sale", prompt_style=prompt_style)
