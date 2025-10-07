# hybrid_pipeline.py
import hashlib
from pymongo import MongoClient
from real_estate_vector_db import RealEstateVectorDB

# Подключение к MongoDB
client = MongoClient("mongodb://localhost:27017/")
db = client["real_estate"]
collection_rent = db["rent_listings"]
collection_sale = db["sale_listings"]

class HybridMongoDBPipeline:
    """
    Pipeline который сохраняет данные одновременно в MongoDB и векторную БД
    """
    
    def open_spider(self, spider):
        """Инициализация при запуске спайдера"""
        self.collection = collection_rent if spider.name == 'RentSpider' else collection_sale
        self.collection_type = 'rent' if spider.name == 'RentSpider' else 'sale'
        
        # Инициализируем векторную БД
        try:
            self.vector_db = RealEstateVectorDB()
            print(f"✅ Векторная БД инициализирована для {spider.name}")
        except Exception as e:
            print(f"⚠️ Ошибка инициализации векторной БД: {e}")
            self.vector_db = None

    def process_item(self, item, spider):
        """Обработка каждого элемента - сохранение в MongoDB и векторную БД"""
        
        # 1. Сохраняем в MongoDB как обычно
        if not item.get('_id'):
            item['_id'] = hashlib.md5((item.get('link') or '').encode('utf-8')).hexdigest()

        try:
            # Используем upsert для избежания дубликатов
            result = self.collection.update_one(
                {'_id': item['_id']}, 
                {'$set': dict(item)}, 
                upsert=True
            )
            
            # Логируем результат MongoDB операции
            if result.upserted_id:
                print(f"✅ Новое объявление добавлено в MongoDB: {item['_id']}")
                is_new_item = True
            elif result.modified_count > 0:
                print(f"🔄 Объявление обновлено в MongoDB: {item['_id']}")
                is_new_item = False
            else:
                print(f"ℹ️ Объявление уже существует в MongoDB: {item['_id']}")
                is_new_item = False
                
        except Exception as e:
            print(f"❌ Ошибка при сохранении в MongoDB: {e}")
            return item

        # 2. Добавляем в векторную БД (только если есть текстовый контент)
        if self.vector_db and self._has_text_content(item):
            try:
                # Добавляем только новые или обновленные элементы
                if is_new_item or result.modified_count > 0:
                    self.vector_db.add_listing_to_vector_db(dict(item), self.collection_type)
                    print(f"✅ Объявление добавлено в векторную БД: {item['_id']}")
                else:
                    print(f"ℹ️ Объявление уже существует в векторной БД: {item['_id']}")
                    
            except Exception as e:
                print(f"⚠️ Ошибка при добавлении в векторную БД: {e}")
                # Продолжаем работу даже если векторная БД недоступна

        return item

    def _has_text_content(self, item):
        """
        Проверяет, есть ли у объявления текстовый контент для векторизации
        
        Args:
            item (dict): Данные объявления
            
        Returns:
            bool: True если есть описание или характеристики
        """
        return bool(
            item.get('description') or 
            item.get('features_by_category') or 
            item.get('title')
        )

    def close_spider(self, spider):
        """Завершение работы спайдера"""
        if self.vector_db:
            # Показываем статистику
            print(f"\n📊 Статистика векторной БД после работы {spider.name}:")
            self.vector_db.get_stats()


# Для использования в scarpy.py нужно будет заменить:
# 'ITEM_PIPELINES': {'__main__.MongoDBPipeline': 1}
# на:
# 'ITEM_PIPELINES': {'hybrid_pipeline.HybridMongoDBPipeline': 1}
