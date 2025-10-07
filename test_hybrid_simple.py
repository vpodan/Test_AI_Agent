#!/usr/bin/env python3
"""
Тест гибридного поиска с простым запросом - УЛУЧШЕННАЯ ВЕРСИЯ
Ищет ВСЕ объявления в MongoDB, проводит семантический поиск по всем найденным,
возвращает топ-5 по семантическому скору
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from main import extract_criteria_from_prompt
from hybrid_search import HybridRealEstateSearch

def test_hybrid_simple():
    """Тестируем гибридный поиск с простым запросом"""
    
    print("🔍 ТЕСТ ГИБРИДНОГО ПОИСКА - УЛУЧШЕННАЯ ВЕРСИЯ")
    print("=" * 60)
    
    # Инициализируем гибридную систему
    hybrid_system = HybridRealEstateSearch()
    
    # Простой запрос
    query = "Ищу 2-комнатную квартиру в Варшаве до 800000 злотых с балконом и гаражом, не старше 2015 года постройки, с современным ремонтом и удобным быстрым проездом к центру."
    print(f"Запрос: '{query}'")
    print("-" * 60)
    
    # Шаг 1: Извлечение критериев
    print("📝 Шаг 1: Извлечение критериев через LLM...")
    try:
        criteria = extract_criteria_from_prompt(query)
        print(f"✅ Критерии извлечены:")
        for key, value in criteria.items():
            if value is not None:
                print(f"   {key}: {value}")
    except Exception as e:
        print(f"❌ Ошибка извлечения критериев: {e}")
        return
    
    # Шаг 2: Гибридный поиск
    print("\n🔍 Шаг 2: Гибридный поиск (MongoDB + семантический)...")
    try:
        # Определяем тип объявлений на основе критериев
        transaction_type = criteria.get("transaction_type")
        if transaction_type == "kupno":
            listing_type = "sale"
        elif transaction_type == "wynajem":
            listing_type = "rent"
        else:
            # Если не указан тип транзакции, ищем в обеих коллекциях
            listing_type = "both"
        
        print(f"🎯 Тип поиска: {listing_type}")
        
        # Подготавливаем фильтры из извлеченных критериев
        filters = {}
        
        # Основные фильтры
        if criteria.get("city"):
            filters["city"] = criteria["city"]
        if criteria.get("district"):
            filters["district"] = criteria["district"]
        if criteria.get("max_price"):
            filters["max_price"] = criteria["max_price"]
        if criteria.get("room_count"):
            filters["rooms"] = criteria["room_count"]  # Используем "rooms" для совместимости с hybrid_search
        if criteria.get("space_sm"):
            filters["min_area"] = criteria["space_sm"]
        
        # Дополнительные фильтры
        if criteria.get("market_type"):
            filters["market_type"] = criteria["market_type"]
        if criteria.get("stan_wykonczenia"):
            filters["stan_wykonczenia"] = criteria["stan_wykonczenia"]
        if criteria.get("building_material"):
            filters["building_material"] = criteria["building_material"]
        if criteria.get("building_type"):
            filters["building_type"] = criteria["building_type"]
        if criteria.get("ogrzewanie"):
            filters["ogrzewanie"] = criteria["ogrzewanie"]
        
        # Фильтры по году постройки
        if criteria.get("min_build_year"):
            filters["min_build_year"] = criteria["min_build_year"]
        if criteria.get("max_build_year"):
            filters["max_build_year"] = criteria["max_build_year"]
        
        # Фильтр по чиншу (для аренды)
        if criteria.get("max_czynsz"):
            filters["max_czynsz"] = criteria["max_czynsz"]
        
        # Boolean фильтры
        if criteria.get("has_garage") is not None:
            filters["has_garage"] = criteria["has_garage"]
        if criteria.get("has_parking") is not None:
            filters["has_parking"] = criteria["has_parking"]
        if criteria.get("has_balcony") is not None:
            filters["has_balcony"] = criteria["has_balcony"]
        if criteria.get("has_elevator") is not None:
            filters["has_elevator"] = criteria["has_elevator"]
        if criteria.get("has_air_conditioning") is not None:
            filters["has_air_conditioning"] = criteria["has_air_conditioning"]
        if criteria.get("pets_allowed") is not None:
            filters["pets_allowed"] = criteria["pets_allowed"]
        if criteria.get("furnished") is not None:
            filters["furnished"] = criteria["furnished"]
        
        print(f"🔍 Применяемые фильтры: {filters}")
        
        # Выполняем гибридный поиск с большим лимитом для MongoDB
        # Устанавливаем лимит 1000 для MongoDB, чтобы получить ВСЕ возможные результаты
        hybrid_results = hybrid_system.search(
            filters=filters,
            semantic_query=query,  # Используем оригинальный запрос для семантического поиска
            listing_type=listing_type,
            limit=1000  # Большой лимит для MongoDB
        )
        
        # Берем только топ-5 по семантическому скору
        top_results = hybrid_results[:5]
        
        print(f"✅ Гибридный поиск завершен. Найдено: {len(hybrid_results)} объявлений")
        print(f"🎯 Показываем топ-5 по семантическому скору")
        
        # Показываем результаты
        if top_results:
            print(f"\n📋 Топ 5 результатов:")
            for j, result in enumerate(top_results, 1):
                print(f"\n--- Результат {j} ---")
                print(f"ID: {result.get('_id', 'N/A')}")
                print(f"Заголовок: {result.get('title', 'N/A')}")
                
                # Показываем семантический скор если есть
                if 'semantic_score' in result:
                    print(f"Семантический скор: {result['semantic_score']:.3f} (косинусное расстояние: чем ближе к 1, тем лучше)")
                
                print(f"Цена: {result.get('price', 'N/A')} зл")
                print(f"Комнаты: {result.get('room_count', 'N/A')}")
                print(f"Площадь: {result.get('space_sm', 'N/A')} м²")
                print(f"Город: {result.get('city', 'N/A')}")
                print(f"Район: {result.get('district', 'N/A')}")
                print(f"Ссылка: {result.get('link', 'N/A')}")
                
                # Показываем дополнительные характеристики
                features = []
                if result.get('has_garage'):
                    features.append("гараж")
                if result.get('has_parking'):
                    features.append("парковка")
                if result.get('has_balcony'):
                    features.append("балкон")
                if result.get('has_elevator'):
                    features.append("лифт")
                if result.get('has_air_conditioning'):
                    features.append("кондиционер")
                if result.get('pets_allowed'):
                    features.append("животные разрешены")
                if result.get('furnished'):
                    features.append("меблированная")
                
                if features:
                    print(f"Характеристики: {', '.join(features)}")
                    
                # Показываем дополнительную информацию
                if result.get('market_type'):
                    print(f"Тип рынка: {result.get('market_type')}")
                if result.get('stan_wykonczenia'):
                    print(f"Состояние: {result.get('stan_wykonczenia')}")
                if result.get('build_year'):
                    print(f"Год постройки: {result.get('build_year')}")
                if result.get('building_material'):
                    print(f"Материал: {result.get('building_material')}")
                if result.get('ogrzewanie'):
                    print(f"Отопление: {result.get('ogrzewanie')}")
        else:
            print("❌ Результаты не найдены")
            
    except Exception as e:
        print(f"❌ Ошибка гибридного поиска: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_hybrid_simple()
