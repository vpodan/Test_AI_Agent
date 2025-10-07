#!/usr/bin/env python3
"""
Тестовый скрипт для проверки работы LLM извлечения критериев и поиска
"""

import json
import logging
from main import extract_criteria_from_prompt, search_listings
from pymongo import MongoClient

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_llm_extraction_and_search(prompt_text):
    """
    Тестирует полную цепочку: LLM извлечение критериев -> поиск в MongoDB
    """
    print(f"🔍 Тестируем запрос: '{prompt_text}'")
    print("=" * 80)
    
    # Шаг 1: Извлекаем критерии через LLM
    print("📝 Шаг 1: Извлечение критериев через LLM...")
    try:
        criteria_result = extract_criteria_from_prompt(prompt_text)
        print(f"✅ Критерии извлечены: {json.dumps(criteria_result, indent=2, ensure_ascii=False)}")
    except Exception as e:
        print(f"❌ Ошибка извлечения критериев: {e}")
        return
    
    # Шаг 2: Выполняем поиск
    print("\n🔍 Шаг 2: Поиск объявлений...")
    try:
        search_result = search_listings(criteria_result)
        print(f"✅ Поиск завершен. Найдено объявлений: {len(search_result.get('listings', []))}")
        
        # Показываем результаты
        listings = search_result.get('listings', [])
        if listings:
            print(f"\n📋 Первые {min(3, len(listings))} результатов:")
            for i, listing in enumerate(listings[:3], 1):
                print(f"\n--- Результат {i} ---")
                print(f"ID: {listing.get('_id', 'N/A')}")
                print(f"Заголовок: {listing.get('title', 'N/A')}")
                print(f"Цена: {listing.get('price', 'N/A')} зл")
                print(f"Комнаты: {listing.get('room_count', 'N/A')}")
                print(f"Площадь: {listing.get('space_sm', 'N/A')} м²")
                print(f"Город: {listing.get('city', 'N/A')}")
                print(f"Район: {listing.get('district', 'N/A')}")
                print(f"Ссылка: {listing.get('link', 'N/A')}")
                
                # Показываем дополнительные поля если есть
                if listing.get('market_type'):
                    print(f"Тип рынка: {listing.get('market_type')}")
                if listing.get('stan_wykonczenia'):
                    print(f"Состояние: {listing.get('stan_wykonczenia')}")
                if listing.get('build_year'):
                    print(f"Год постройки: {listing.get('build_year')}")
                if listing.get('building_material'):
                    print(f"Материал: {listing.get('building_material')}")
                if listing.get('ogrzewanie'):
                    print(f"Отопление: {listing.get('ogrzewanie')}")
                if listing.get('czynsz'):
                    print(f"Чинш: {listing.get('czynsz')} зл")
                
                # Показываем дополнительные характеристики
                features = []
                if listing.get('has_garage'):
                    features.append("гараж")
                if listing.get('has_parking'):
                    features.append("парковка")
                if listing.get('has_balcony'):
                    features.append("балкон")
                if listing.get('has_elevator'):
                    features.append("лифт")
                if listing.get('has_air_conditioning'):
                    features.append("кондиционер")
                if listing.get('pets_allowed'):
                    features.append("животные разрешены")
                if listing.get('furnished'):
                    features.append("меблированное")
                
                if features:
                    print(f"Характеристики: {', '.join(features)}")
        else:
            print("❌ Объявления не найдены")
            
    except Exception as e:
        print(f"❌ Ошибка поиска: {e}")

def test_multiple_queries():
    """
    Тестирует несколько различных запросов
    """
    test_queries = [
        "Ищу 2-комнатную квартиру в Варшаве до 800000 злотых",
        "Нужна квартира в Гданьске с балконом, до 3000 злотых в месяц",
        "Хочу купить 3-комнатную квартиру в кирпичном доме, построенную после 2010 года, до 1.5 млн злотых",
        "Ищу квартиру в новостройке (PRIMARY) в состоянии готовом к заселению, до 2 млн злотых",
        "Нужна квартира с газовым отоплением, до 4000 злотых в месяц, включая чинш до 800 злотых",
        "Ищу квартиру с гаражом и лифтом, до 1 млн злотых",
        "Нужна меблированная квартира с балконом, где разрешены животные, до 2500 злотых в месяц",
        "Хочу квартиру с кондиционером и парковкой, до 600000 злотых"
    ]
    
    for i, query in enumerate(test_queries, 1):
        print(f"\n{'='*100}")
        print(f"ТЕСТ {i}")
        print(f"{'='*100}")
        test_llm_extraction_and_search(query)
        print("\n" + "="*100)

if __name__ == "__main__":
    print("🚀 Запуск тестирования LLM извлечения критериев и поиска")
    print("="*100)
    
    # Проверяем подключение к MongoDB
    try:
        client = MongoClient('mongodb://localhost:27017/')
        db = client['real_estate']
        rent_count = db.rent_listings.count_documents({})
        sale_count = db.sale_listings.count_documents({})
        print(f"📊 База данных: {rent_count} объявлений аренды, {sale_count} объявлений продажи")
    except Exception as e:
        print(f"❌ Ошибка подключения к MongoDB: {e}")
        exit(1)
    
    # Запускаем тесты
    test_multiple_queries()
    
    print("\n🎉 Тестирование завершено!")
