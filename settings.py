MONGO_URI = 'mongodb://localhost:27017' 
MONGO_DATABASE = 'real_estate'
MONGO_COLLECTION = 'apartments'

ITEM_PIPELINES = {
    '__main__.MongoDBPipeline': 1,
}
