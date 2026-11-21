import os

import redis

queue = redis.Redis.from_url(os.getenv('REDIS_URL', 'redis://redis:6379/0'), decode_responses=True)
