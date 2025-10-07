#!/usr/bin/env python3
"""
Тест полной связки: словесный запрос → LLM → MongoDB → семантический поиск → результаты
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from main import extract_criteria_from_prompt, search_listings
from hybrid_search import HybridRealEstateSearch

def test_full_pipeline():
    """Тестирует полную связку от словесного запроса до результатов"""
    
    print("🚀 ТЕСТ ПОЛНОЙ СВЯЗКИ: СЛОВЕСНЫЙ ЗАПРОС → LLM → MONGODB → СЕМАНТИЧЕСКИЙ ПОИСК")
    print("=" * 80)
    
    # Инициализируем гибридную систему поиска
    hybrid_system = HybridRealEstateSearch()
    
    # Тестовые запросы
    test_queries = [
        "Ищу 2-комнатную квартиру в Варшаве с балконом, до 800000 злотых",
        "Нужна квартира в Гданьске с гаражом и лифтом, до 3000 злотых в месяц",
        "Хочу купить 3-комнатную квартиру в кирпичном доме, построенную после 2010 года, до 1.5 млн злотых",
        "Ищу квартиру с кондиционером и парковкой, до 600000 злотых"
    ]
    
    for i, query in enumerate(test_queries, 1):
        print(f"\n{'='*20} ТЕСТ {i} {'='*20}")
        print(f"🔍 Словесный запрос: '{query}'")
        print("-" * 60)
        
        # Шаг 1: Извлечение критериев через LLM
        print("📝 Шаг 1: Извлечение критериев через LLM...")
        try:
            criteria = extract_criteria_from_prompt(query)
            print(f"✅ Критерии извлечены: {criteria}")
        except Exception as e:
            print(f"❌ Ошибка извлечения критериев: {e}")
            continue
        
        # Шаг 2: Поиск через MongoDB (структурированный)
        print("\n🔍 Шаг 2: Структурированный поиск через MongoDB...")
        try:
            mongo_results = search_listings(criteria)
            print(f"✅ MongoDB нашел: {mongo_results['total']} объявлений")
            
            if mongo_results['total'] == 0:
                print("❌ Объявления не найдены в MongoDB")
                continue
                
        except Exception as e:
            print(f"❌ Ошибка MongoDB поиска: {e}")
            continue
        
        # Шаг 3: Гибридный поиск (MongoDB + семантический)
        print("\n🔍 Шаг 3: Гибридный поиск (MongoDB + семантический)...")
        try:
            # Определяем тип объявлений
            listing_type = "buy" if criteria.get("transaction_type") == "kupno" else "rent"
            
            # Подготавливаем фильтры для гибридного поиска
            filters = {}
            if criteria.get("city"):
                filters["city"] = criteria["city"]
            if criteria.get("max_price"):
                filters["max_price"] = criteria["max_price"]
            if criteria.get("room_count"):
                filters["room_count"] = criteria["room_count"]
            if criteria.get("market_type"):
                filters["market_type"] = criteria["market_type"]
            if criteria.get("stan_wykonczenia"):
                filters["stan_wykonczenia"] = criteria["stan_wykonczenia"]
            if criteria.get("min_build_year"):
                filters["min_build_year"] = criteria["min_build_year"]
            if criteria.get("max_build_year"):
                filters["max_build_year"] = criteria["max_build_year"]
            if criteria.get("building_material"):
                filters["building_material"] = criteria["building_material"]
            if criteria.get("building_type"):
                filters["building_type"] = criteria["building_type"]
            if criteria.get("ogrzewanie"):
                filters["ogrzewanie"] = criteria["ogrzewanie"]
            if criteria.get("max_czynsz"):
                filters["max_czynsz"] = criteria["max_czynsz"]
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
            
            # Выполняем гибридный поиск
            hybrid_results = hybrid_system.search(
                filters=filters,
                semantic_query=query,  # Используем оригинальный запрос для семантического поиска
                listing_type=listing_type,
                limit=5
            )
            
            print(f"✅ Гибридный поиск завершен. Найдено: {len(hybrid_results)} объявлений")
            
            # Показываем результаты
            if hybrid_results:
                print(f"\n📋 Топ {len(hybrid_results)} результатов:")
                for j, result in enumerate(hybrid_results, 1):
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
                    
                    # Показываем дополнительные поля
                    if result.get('market_type'):
                        print(f"Тип рынка: {result['market_type']}")
                    if result.get('stan_wykonczenia'):
                        print(f"Состояние: {result['stan_wykonczenia']}")
                    if result.get('build_year'):
                        print(f"Год постройки: {result['build_year']}")
                    if result.get('building_material'):
                        print(f"Материал: {result['building_material']}")
                    if result.get('ogrzewanie'):
                        print(f"Отопление: {result['ogrzewanie']}")
                    if result.get('czynsz'):
                        print(f"Чинш: {result['czynsz']} зл")
            else:
                print("❌ Результаты не найдены")
                
        except Exception as e:
            print(f"❌ Ошибка гибридного поиска: {e}")
            continue
        
        print(f"\n{'='*60}")
    
    print("\n🎉 Тестирование полной связки завершено!")

if __name__ == "__main__":
    test_full_pipeline()
