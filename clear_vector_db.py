#!/usr/bin/env python3
"""
Скрипт для очистки векторной базы данных Chroma
"""

from real_estate_vector_db import RealEstateVectorDB
import os

def clear_vector_database():
    """Очищает векторную базу данных"""
    print("🗑️ Очистка векторной базы данных...")
    
    vector_db = RealEstateVectorDB()
    vector_db.clear_database()
    
    print("✅ Векторная база данных очищена!")

def clear_and_rebuild():
    """Очищает и пересоздает векторную БД"""
    print("🔄 Очистка и пересоздание векторной БД...")
    
    vector_db = RealEstateVectorDB()
    
    # Очищаем
    vector_db.clear_database()
    print("✅ Очистка завершена")
    
    # Пересоздаем
    print("🚀 Заполняем базу данных...")
    vector_db.populate_from_mongo()
    
    print("✅ Векторная БД пересоздана!")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--rebuild":
        clear_and_rebuild()
    else:
        clear_vector_database()
