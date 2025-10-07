# 🏠 Примеры использования гибридного поиска

## 🎯 Результаты с реальными ссылками

Система теперь показывает **прямые ссылки на объявления Otodom**, чтобы вы могли сразу перейти и посмотреть как выглядит квартира!

---

## 📋 Примеры поиска

### 1. **Семантический поиск**: "современная квартира с балконом"

```bash
python real_estate_vector_db.py --search "современная квартира с балконом"
```

**Результат:**
```
1. ID: ID4xOnM (Score: 0.988) ⭐ САМЫЙ РЕЛЕВАНТНЫЙ
   Заголовок: Apartament z widokiem na odpływ Motławy
   Ссылка: https://www.otodom.pl/pl/oferta/apartament-z-widokiem-na-odplyw-motlawy-ID4xOnM
   
2. ID: ID4xCqG (Score: 0.997)
   Заголовок: Komfortowe mieszkanie z widokiem super lokalizacja  
   Ссылка: https://www.otodom.pl/pl/oferta/komfortowe-mieszkanie-z-widokiem-super-lokalizacja-ID4xCqG
```

### 2. **Гибридный поиск**: Фильтры + семантика

```python
from hybrid_search import HybridRealEstateSearch

search_engine = HybridRealEstateSearch()
results = search_engine.search(
    filters={"city": "Gdańsk", "rooms": 2},
    semantic_query="тихий район с парковкой и балконом",
    listing_type="rent"
)
```

**Результат:**
```
Первый результат:
ID: ID4xCqG
Заголовок: Komfortowe mieszkanie z widokiem super lokalizacja
Семантический скор: 1.387 ⭐ ВЫСОКАЯ РЕЛЕВАНТНОСТЬ
Цена: 3200.0 зл
Ссылка: https://www.otodom.pl/pl/oferta/komfortowe-mieszkanie-z-widokiem-super-lokalizacja-ID4xCqG
Описание: Oferujemy na wynajem nowoczesne, 2-pokojowe mieszkanie o powierzchni 40 m²...
```

### 3. **Только фильтры**: Структурированный поиск

```python
results = search_engine.search(
    filters={"city": "Gdańsk", "rooms": 2, "max_price": 4000},
    listing_type="rent"
)
```

**Результат:**
```
✅ Найдено: 5 объявлений

1. Os. tysiąclecia 2pok rok akademicki, niskie opłaty - 2500.0 зл
   Локация: Gdańsk, комнат: 2
   Ссылка: https://www.otodom.pl/pl/oferta/os-tysiaclecia-2pok-rok-akademicki-niskie-oplaty-ID4xRpd
   
2. Komfortowe mieszkanie z widokiem super lokalizacja - 3200.0 зл  
   Локация: Gdańsk, комнат: 2
   Ссылка: https://www.otodom.pl/pl/oferta/komfortowe-mieszkanie-z-widokiem-super-lokalizacja-ID4xCqG
```

---

## 🔗 Как работают ссылки

### Формат ссылок Otodom:
```
https://www.otodom.pl/pl/oferta/[название-объявления]-[ID]
```

### Примеры реальных ссылок:
- **Аренда**: `https://www.otodom.pl/pl/oferta/komfortowe-mieszkanie-z-widokiem-super-lokalizacja-ID4xCqG`
- **Продажа**: `https://www.otodom.pl/pl/oferta/trzypokojowe-mieszkanie-przy-stacji-metra-bemowo-ID4xjwl`

### Что вы увидите на Otodom:
✅ **Фотографии квартиры** - внутри и снаружи  
✅ **Детальное описание** - на польском языке  
✅ **Точная локация** - карта с адресом  
✅ **Контакты** - телефон агентства/владельца  
✅ **Дополнительные характеристики** - площадь, этаж, год постройки  
✅ **Цена и условия** - czynsz, kaucja, opłaty  

---

## 🤖 Интеграция в WhatsApp бота

### Пример функции для WhatsApp:

```python
def format_search_results_for_whatsapp(results, max_results=3):
    """Форматирует результаты поиска для WhatsApp"""
    if not results:
        return "😔 Не найдено объявлений по вашим критериям"
    
    message = f"🏠 Найдено {len(results)} подходящих объявлений:\n\n"
    
    for i, listing in enumerate(results[:max_results], 1):
        message += f"{i}. *{listing['title']}*\n"
        message += f"💰 {listing['price']} zł\n"
        message += f"📍 {listing['city']}, {listing.get('district', '')}\n"
        message += f"🏠 {listing['room_count']} комн., {listing['space_sm']} м²\n"
        
        if listing.get('semantic_score'):
            relevance = "🔥" if listing['semantic_score'] < 1.2 else "⭐" if listing['semantic_score'] < 1.5 else "✅"
            message += f"{relevance} Релевантность: {listing['semantic_score']:.2f}\n"
        
        # ГЛАВНОЕ - ссылка для просмотра!
        if listing.get('link'):
            message += f"👀 Посмотреть: {listing['link']}\n"
        
        message += "\n"
    
    if len(results) > max_results:
        message += f"... и еще {len(results) - max_results} объявлений"
    
    return message
```

### Пример использования в боте:

```python
# Пользователь: "найди тихую 2-комнатную квартиру в Гданьске с балконом до 4000 зл"

# Парсим запрос
filters = {"city": "Gdańsk", "rooms": 2, "max_price": 4000}
semantic_query = "тихий район с балконом"

# Ищем
results = search_engine.search(
    filters=filters,
    semantic_query=semantic_query,
    listing_type="rent",
    limit=5
)

# Отправляем в WhatsApp
message = format_search_results_for_whatsapp(results)
send_whatsapp_message(user_phone, message)
```

### Результат в WhatsApp:
```
🏠 Найдено 3 подходящих объявлений:

1. *Komfortowe mieszkanie z widokiem super lokalizacja*
💰 3200 zł
📍 Gdańsk, Śródmieście  
🏠 2 комн., 40 м²
🔥 Релевантность: 1.39
👀 Посмотреть: https://www.otodom.pl/pl/oferta/komfortowe-mieszkanie-z-widokiem-super-lokalizacja-ID4xCqG

2. *Os. tysiąclecia 2pok rok akademicki*
💰 2500 zł
📍 Gdańsk, Przymorze
🏠 2 комн., 35 м²
⭐ Релевантность: 1.42
👀 Посмотреть: https://www.otodom.pl/pl/oferta/os-tysiaclecia-2pok-rok-akademicki-niskie-oplaty-ID4xRpd
```

---

## 🔍 Команды для тестирования

```bash
# Семантический поиск
python real_estate_vector_db.py --search "новая квартира с парковкой"
python real_estate_vector_db.py --search "студия в центре города"
python real_estate_vector_db.py --search "семейная квартира с балконом"

# Статистика
python real_estate_vector_db.py --stats

# Демо поиск (без OpenAI)  
python demo_hybrid_system.py

# Полный гибридный тест
python hybrid_search.py
```

---

## 💡 Преимущества с ссылками

1. **Мгновенная проверка** - пользователь сразу видит фото и детали
2. **Доверие к результатам** - можно убедиться в релевантности  
3. **Прямой контакт** - телефоны агентств на Otodom
4. **Актуальность** - если ссылка не работает, объявление снято
5. **Полнота информации** - все детали на оригинальной странице

Теперь ваш бот не просто находит квартиры, а предоставляет **полноценную услугу поиска жилья**! 🏠✨



