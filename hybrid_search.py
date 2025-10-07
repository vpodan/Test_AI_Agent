# hybrid_search.py
from typing import List, Dict, Optional, Union
from pymongo import MongoClient
from real_estate_vector_db import RealEstateVectorDB

# Подключение к MongoDB
client = MongoClient("mongodb://localhost:27017/")
db = client["real_estate"]
collection_rent = db["rent_listings"]
collection_sale = db["sale_listings"]

class HybridRealEstateSearch:
    """
    Класс для выполнения гибридного поиска по объявлениям недвижимости
    Комбинирует структурированный поиск в MongoDB с семантическим поиском в векторной БД
    """
    
    def __init__(self):
        """Инициализация поисковой системы"""
        self.vector_db = RealEstateVectorDB()
        self.rent_collection = collection_rent
        self.sale_collection = collection_sale
    
    def search(self, 
               filters: Dict = None, 
               semantic_query: str = None,
               listing_type: str = "both",
               limit: int = 100) -> List[Dict]:
        """
        Основная функция гибридного поиска
        
        Args:
            filters (Dict): Структурированные фильтры для MongoDB
            semantic_query (str): Семантический запрос для векторного поиска
            listing_type (str): "rent", "sale" или "both"
            limit (int): Максимальное количество результатов
            
        Returns:
            List[Dict]: Результаты поиска
        """
        print(f"🔍 Начинаем гибридный поиск:")
        print(f"   Фильтры: {filters}")
        print(f"   Семантический запрос: '{semantic_query}'")
        print(f"   Тип объявлений: {listing_type}")
        
        # Определяем в каких коллекциях искать
        collections_to_search = self._get_collections_to_search(listing_type)
        
        all_results = []
        
        for collection_name, collection in collections_to_search.items():
            print(f"\n📊 Поиск в коллекции: {collection_name}")
            
            # Этап 1: Структурированная фильтрация в MongoDB
            # Если есть семантический запрос, ищем ВСЕ возможные результаты в MongoDB
            # чтобы потом провести семантический поиск по всем найденным
            if semantic_query and semantic_query.strip():
                mongo_limit = 10000  # Большой лимит для получения всех возможных результатов
            else:
                mongo_limit = limit  # Если нет семантического поиска, используем обычный лимит
            
            mongo_results = self._mongodb_filter(collection, filters, mongo_limit)
            mongo_ids = [str(result["_id"]) for result in mongo_results]
            

            
            if not mongo_ids:
                print(f"   Нет результатов в {collection_name}")
                continue
            
            # Этап 2: Семантический поиск (если есть запрос)
            if semantic_query and semantic_query.strip():
                print(f"   Выполняем семантический поиск...")
                
                vector_results = self.vector_db.semantic_search(
                    query=semantic_query,
                    collection_type=collection_name,
                    mongo_ids=mongo_ids,  # Ищем только среди отфильтрованных MongoDB
                    top_k=min(limit, len(mongo_ids))
                )
                
                print(f"   Векторный поиск нашел: {len(vector_results)} релевантных")
                
                # Объединяем данные из MongoDB с векторными результатами
                combined_results = self._combine_mongo_and_vector_results(
                    mongo_results, vector_results, collection_name
                )
                
            else:
                # Если нет семантического запроса, возвращаем только MongoDB результаты
                print(f"   Семантический поиск пропущен")
                combined_results = self._format_mongo_results(mongo_results, collection_name)
            
            all_results.extend(combined_results)
        
        # Сортируем и ограничиваем результаты
        final_results = self._rank_and_limit_results(all_results, limit)
        
        print(f"\n✅ Итого найдено: {len(final_results)} объявлений")
        return final_results
    
    def _get_collections_to_search(self, listing_type: str) -> Dict:
        """Определяет в каких коллекциях MongoDB искать"""
        if listing_type == "rent":
            return {"rent": self.rent_collection}
        elif listing_type == "sale":
            return {"sale": self.sale_collection}
        else:  # both
            return {"rent": self.rent_collection, "sale": self.sale_collection}
    
    def _mongodb_filter(self, collection, filters: Dict, limit: int) -> List[Dict]:
        """
        Выполняет структурированную фильтрацию в MongoDB
        
        Args:
            collection: MongoDB коллекция
            filters (Dict): Фильтры для поиска
            limit (int): Лимит результатов
            
        Returns:
            List[Dict]: Результаты из MongoDB
        """
        if not filters:
            filters = {}
        
        # Строим MongoDB запрос
        mongo_query = {}
        
        # Фильтр по городу
        if filters.get("city"):
            mongo_query["city"] = {"$regex": filters["city"], "$options": "i"}
        
        # Фильтр по району
        if filters.get("district"):
            mongo_query["district"] = {"$regex": filters["district"], "$options": "i"}
        
        # Фильтр по количеству комнат
        if filters.get("rooms"):
            if isinstance(filters["rooms"], list):
                mongo_query["room_count"] = {"$in": filters["rooms"]}
            else:
                mongo_query["room_count"] = filters["rooms"]
        
        # Фильтр по цене
        price_filter = {}
        if filters.get("min_price"):
            price_filter["$gte"] = filters["min_price"]
        if filters.get("max_price"):
            price_filter["$lte"] = filters["max_price"]
        if price_filter:
            mongo_query["price"] = price_filter
        
        # Фильтр по площади
        area_filter = {}
        if filters.get("min_area"):
            area_filter["$gte"] = filters["min_area"]
        if filters.get("max_area"):
            area_filter["$lte"] = filters["max_area"]
        if area_filter:
            mongo_query["space_sm"] = area_filter
        
        # Фильтр по типу здания
        if filters.get("building_type"):
            mongo_query["building_type"] = filters["building_type"]
        
        # Фильтр по году постройки
        if filters.get("min_year"):
            mongo_query["build_year"] = {"$gte": str(filters["min_year"])}
        
        # Новые фильтры для продажи
        if filters.get("market_type"):
            mongo_query["market_type"] = filters["market_type"]
        if filters.get("stan_wykonczenia"):
            mongo_query["stan_wykonczenia"] = filters["stan_wykonczenia"]
        if filters.get("building_material"):
            mongo_query["building_material"] = filters["building_material"]
        if filters.get("ogrzewanie"):
            mongo_query["ogrzewanie"] = filters["ogrzewanie"]
        
        # Фильтр по году постройки (расширенный)
        if filters.get("min_build_year") or filters.get("max_build_year"):
            build_year_filter = {}
            if filters.get("min_build_year"):
                build_year_filter["$gte"] = str(filters["min_build_year"])
            if filters.get("max_build_year"):
                build_year_filter["$lte"] = str(filters["max_build_year"])
            mongo_query["build_year"] = build_year_filter
        
        # Фильтр по czynszu (для аренды)
        if filters.get("max_czynsz"):
            mongo_query["czynsz"] = {"$lte": filters["max_czynsz"]}
        
        # Фильтры по дополнительным характеристикам
        if filters.get("has_garage") is not None:
            mongo_query["has_garage"] = filters["has_garage"]
        if filters.get("has_parking") is not None:
            mongo_query["has_parking"] = filters["has_parking"]
        if filters.get("has_balcony") is not None:
            mongo_query["has_balcony"] = filters["has_balcony"]
        if filters.get("has_elevator") is not None:
            mongo_query["has_elevator"] = filters["has_elevator"]
        if filters.get("has_air_conditioning") is not None:
            mongo_query["has_air_conditioning"] = filters["has_air_conditioning"]
        if filters.get("pets_allowed") is not None:
            mongo_query["pets_allowed"] = filters["pets_allowed"]
        if filters.get("furnished") is not None:
            mongo_query["furnished"] = filters["furnished"]
        
        # Выполняем запрос
        try:
            cursor = collection.find(mongo_query).limit(limit)
            results = list(cursor)
            print(f"   MongoDB запрос: {mongo_query}")
            print(f"   MongoDB нашел: {len(results)} объявлений")
            return results
        except Exception as e:
            print(f"❌ Ошибка MongoDB запроса: {e}")
            return []
    
    def _combine_mongo_and_vector_results(self, mongo_results: List[Dict], 
                                        vector_results: List[Dict], 
                                        collection_type: str) -> List[Dict]:
        """
        Объединяет результаты из MongoDB с векторными результатами
        
        Args:
            mongo_results: Результаты из MongoDB
            vector_results: Результаты из векторного поиска
            collection_type: Тип коллекции ('rent' или 'sale')
            
        Returns:
            List[Dict]: Объединенные результаты
        """
        # Создаем словарь для быстрого поиска MongoDB документов по ID
        mongo_dict = {str(doc["_id"]): doc for doc in mongo_results}
        
        combined = []
        for vector_result in vector_results:
            listing_id = vector_result["id"]
            
            if listing_id in mongo_dict:
                # Берем полные данные из MongoDB (уже отфильтрованные)
                full_listing = mongo_dict[listing_id].copy()
                
                # Добавляем информацию из векторного поиска
                # Score - косинусное расстояние: чем ближе к 1, тем лучше
                full_listing["semantic_score"] = float(vector_result["score"])
                full_listing["collection_type"] = collection_type
                full_listing["search_relevance"] = "hybrid_match"
                
                combined.append(full_listing)
        
        return combined
    
    def _format_mongo_results(self, mongo_results: List[Dict], collection_type: str) -> List[Dict]:
        """
        Форматирует результаты только из MongoDB (без семантического поиска)
        
        Args:
            mongo_results: Результаты из MongoDB
            collection_type: Тип коллекции
            
        Returns:
            List[Dict]: Отформатированные результаты
        """
        formatted = []
        for result in mongo_results:
            result_copy = result.copy()
            result_copy["collection_type"] = collection_type
            result_copy["search_relevance"] = "filter_match"
            result_copy["semantic_score"] = 0.0  # Нет семантического скора
            formatted.append(result_copy)
        
        return formatted
    
    def _rank_and_limit_results(self, results: List[Dict], limit: int) -> List[Dict]:
        """
        Ранжирует и ограничивает результаты
        
        Args:
            results: Все результаты поиска
            limit: Максимальное количество результатов
            
        Returns:
            List[Dict]: Отранжированные результаты
        """
        # Сортируем по семантическому скору (если есть), потом по цене
        def sort_key(item):
            semantic_score = item.get("semantic_score", 0.0)
            price = item.get("price", 0)
            
            # Приоритет семантическому поиску, потом по убыванию цены
            return (-semantic_score, -price)
        
        sorted_results = sorted(results, key=sort_key)
        return sorted_results[:limit]


def test_hybrid_search():
    """Функция для тестирования гибридного поиска"""
    search_engine = HybridRealEstateSearch()
    
    # Тест 1: Только структурированные фильтры
    print("=== Тест 1: Только фильтры ===")
    results1 = search_engine.search(
        filters={"city": "Warszawa",  "max_price": 8000000},
        listing_type="buy",
        limit=1000
    )
    print(f"Найдено: {len(results1)} объявлений")
    
    # Показываем результаты первого теста
    if results1:
        print(f"\nПервые {min(3, len(results1))} результатов (только фильтры):")
        for i, result in enumerate(results1[:3], 1):
            print(f"\n--- Результат {i} ---")
            print(f"ID: {result['_id']}")
            print(f"Заголовок: {result.get('title', 'N/A')}")
            print(f"Цена: {result.get('price', 'N/A')} зл")
            print(f"Комнаты: {result.get('room_count', 'N/A')}")
            print(f"Площадь: {result.get('space_sm', 'N/A')} м²")
            print(f"Город: {result.get('city', 'N/A')}")
            if result.get('district'):
                print(f"Район: {result.get('district', 'N/A')}")
            print(f"Ссылка: {result.get('link', 'N/A')}")
    
    # Тест 2: Семантический поиск + фильтры
    print("\n=== Тест 2: Фильтры + семантика ===")
    results2 = search_engine.search(
        filters={"city": "Warszawa", "max_price": 8000000},
        semantic_query="blizko centrum",
        listing_type="buy",
        limit=1000
    )
    print(f"Найдено: {len(results2)} объявлений")
    
    # Показываем первые 5 результатов
    if results2:
        print(f"\nПервые {min(5, len(results2))} результатов:")
        for i, result in enumerate(results2[:5], 1):
            print(f"\n--- Результат {i} ---")
            print(f"ID: {result['_id']}")
            print(f"Заголовок: {result.get('title', 'N/A')}")
            print(f"Семантический скор: {result.get('semantic_score', 0):.3f} (косинусное расстояние: чем ближе к 1, тем лучше)")
            print(f"Цена: {result.get('price', 'N/A')} зл")
            print(f"Комнаты: {result.get('room_count', 'N/A')}")
            print(f"Площадь: {result.get('space_sm', 'N/A')} м²")
            print(f"Город: {result.get('city', 'N/A')}")
            if result.get('district'):
                print(f"Район: {result.get('district', 'N/A')}")
            print(f"Ссылка: {result.get('link', 'N/A')}")
            if result.get('description'):
                desc_preview = result['description'][:200] + "..." if len(result['description']) > 200 else result['description']
                print(f"Описание: {desc_preview}")


if __name__ == "__main__":
    test_hybrid_search()
