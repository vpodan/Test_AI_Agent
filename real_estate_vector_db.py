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
    def __init__(self):
        """Инициализация векторной базы данных для недвижимости"""
        self.embedding_function = get_embedding_function()
        self.db = Chroma(
            persist_directory=CHROMA_PATH,
            embedding_function=self.embedding_function,
            collection_metadata={"hnsw:space": "cosine"}  # Используем косинусное расстояние
        )
    
    def add_listing_to_vector_db(self, listing_data: Dict, collection_type: str):
        """
        Добавляет одно объявление в векторную базу данных
        
        Args:
            listing_data (dict): Данные объявления из MongoDB
            collection_type (str): 'rent' или 'sale'
        """
        # Создаем текст для embedding
        text_content = create_listing_text_for_embedding(listing_data)
        
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
    
    def populate_from_mongo(self, limit: Optional[int] = None):
        """
        Загружает все объявления из MongoDB в векторную БД
        
        Args:
            limit (int, optional): Ограничение количества записей для теста
        """
        print("🚀 Начинаем загрузку объявлений в векторную БД...")
        
        # Загружаем объявления аренды
        print("📍 Загружаем объявления аренды...")
        rent_query = {}
        if limit:
            rent_listings = list(collection_rent.find(rent_query).limit(limit))
        else:
            rent_listings = list(collection_rent.find(rent_query))
        
        print(f"Найдено {len(rent_listings)} объявлений аренды")
        
        for listing in rent_listings:
            self.add_listing_to_vector_db(listing, "rent")
        
        # Загружаем объявления продажи
        print("\n📍 Загружаем объявления продажи...")
        sale_query = {}
        if limit:
            sale_listings = list(collection_sale.find(sale_query).limit(limit))
        else:
            sale_listings = list(collection_sale.find(sale_query))
        
        print(f"Найдено {len(sale_listings)} объявлений продажи")
        
        for listing in sale_listings:
            self.add_listing_to_vector_db(listing, "sale")
        
        print(f"\n✅ Загрузка завершена!")
        print(f"📊 Всего обработано: {len(rent_listings) + len(sale_listings)} объявлений")
    
    def semantic_search(self, query: str, collection_type: Optional[str] = None, 
                       mongo_ids: Optional[List[str]] = None, top_k: int = 10) -> List[Dict]:
        """
        Выполняет семантический поиск по объявлениям
        
        Args:
            query (str): Поисковый запрос
            collection_type (str, optional): 'rent' или 'sale'
            mongo_ids (List[str], optional): Список ID для фильтрации (из MongoDB)
            top_k (int): Количество результатов
            
        Returns:
            List[Dict]: Результаты поиска с метаданными
        """
        # Подготавливаем фильтр
        filter_dict = {}
        if collection_type:
            filter_dict["collection_type"] = collection_type
        
        # Временно отключаем сложную фильтрацию по ID - сделаем постфильтрацию
        # if mongo_ids:
        #     filter_dict["id"] = {"$in": mongo_ids}
        
        # Выполняем поиск
        try:
            # Если есть mongo_ids, значительно увеличиваем k для лучшей фильтрации
            search_k = top_k * 20 if mongo_ids else top_k
            results = self.db.similarity_search_with_score(
                query=query,
                k=search_k,
                filter=filter_dict if filter_dict else None
            )
            
            # Форматируем результаты с постфильтрацией по mongo_ids
            formatted_results = []
            for doc, score in results:
                doc_id = doc.metadata["id"]
                
                # Если указаны mongo_ids, фильтруем результаты
                if mongo_ids and doc_id not in mongo_ids:
                    continue
                
                result = {
                    "id": doc_id,
                    "score": score,  # Косинусное расстояние: чем ближе к 1, тем лучше
                    "content": doc.page_content,
                    "metadata": doc.metadata
                }
                formatted_results.append(result)
                
                # Ограничиваем результаты до top_k
                if len(formatted_results) >= top_k:
                    break
            
            return formatted_results
            
        except Exception as e:
            print(f"❌ Ошибка при поиске: {e}")
            return []
    
    def get_stats(self):
        """Получает статистику по векторной БД"""
        try:
            all_docs = self.db.get(include=['metadatas'])
            total_count = len(all_docs['ids'])
            
            # Подсчитываем по типам
            rent_count = sum(1 for meta in all_docs['metadatas'] 
                           if meta.get('collection_type') == 'rent')
            sale_count = sum(1 for meta in all_docs['metadatas'] 
                           if meta.get('collection_type') == 'sale')
            
            print(f"📊 Статистика векторной БД:")
            print(f"   Всего объявлений: {total_count}")
            print(f"   Аренда: {rent_count}")
            print(f"   Продажа: {sale_count}")
            
            return {
                "total": total_count,
                "rent": rent_count,
                "sale": sale_count
            }
        except Exception as e:
            print(f"❌ Ошибка при получении статистики: {e}")
            return {}
    
    def clear_database(self):
        """Очищает векторную базу данных"""
        if os.path.exists(CHROMA_PATH):
            import shutil
            shutil.rmtree(CHROMA_PATH)
            print("🗑️ Векторная база данных очищена")
        else:
            print("ℹ️ Векторная база данных не существует")


def main():
    """Основная функция для тестирования"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Управление векторной БД недвижимости")
    parser.add_argument("--reset", action="store_true", help="Очистить базу данных")
    parser.add_argument("--populate", action="store_true", help="Заполнить базу данных")
    parser.add_argument("--limit", type=int, help="Ограничить количество записей для теста")
    parser.add_argument("--stats", action="store_true", help="Показать статистику")
    parser.add_argument("--search", type=str, help="Выполнить поисковый запрос")
    
    args = parser.parse_args()
    
    vector_db = RealEstateVectorDB()
    
    if args.reset:
        vector_db.clear_database()
    
    if args.populate:
        vector_db.populate_from_mongo(limit=args.limit)
    
    if args.stats:
        vector_db.get_stats()
    
    if args.search:
        print(f"🔍 Поиск: '{args.search}'")
        results = vector_db.semantic_search(args.search, top_k=5)
        for i, result in enumerate(results, 1):
            print(f"\n{i}. ID: {result['id']} (Score: {result['score']:.3f})")
            print(f"   Контент: {result['content'][:200]}...")
            
            # Получаем полные данные из MongoDB для показа ссылки
            collection = collection_rent if result['metadata'].get('collection_type') == 'rent' else collection_sale
            full_data = collection.find_one({"_id": result['id']})
            if full_data and full_data.get('link'):
                print(f"   Ссылка: {full_data['link']}")


if __name__ == "__main__":
    main()
