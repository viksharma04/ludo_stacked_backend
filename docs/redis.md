# Redis Integration

Upstash Redis integration for distributed state management in Ludo Stacked.

## Overview

The backend uses [Upstash Redis](https://upstash.com/) for:
- WebSocket connection state across multiple server instances
- User presence/online status
- Future: game state caching, rate limiting, pub/sub for real-time updates

## Why Upstash?

Upstash provides a serverless Redis with REST API, ideal for:
- **Serverless deployments**: No persistent connections needed
- **Edge compatibility**: Works with edge functions and serverless platforms
- **Pay-per-request**: Cost-effective for variable traffic
- **Global replication**: Low latency worldwide

## Configuration

### Environment Variables

```env
UPSTASH_REDIS_REST_URL=https://your-instance.upstash.io
UPSTASH_REDIS_REST_TOKEN=your-token
```

Get these from your [Upstash Console](https://console.upstash.com/) after creating a Redis database.

### Settings

In `app/config.py`:
```python
class Settings(BaseSettings):
    # Upstash Redis
    UPSTASH_REDIS_REST_URL: str
    UPSTASH_REDIS_REST_TOKEN: str
```

## Client Usage

### Getting the Client

```python
from app.dependencies.redis import get_redis_client

redis = get_redis_client()
```

The client is a singleton - the same instance is returned on every call.

### Basic Operations

```python
# String operations
await redis.set("key", "value")
await redis.set("key", "value", ex=3600)  # With 1 hour expiry
value = await redis.get("key")

# Hash operations
await redis.hset("hash:key", {"field1": "value1", "field2": "value2"})
value = await redis.hget("hash:key", "field1")
all_fields = await redis.hgetall("hash:key")

# Set operations
await redis.sadd("set:key", "member1", "member2")
is_member = await redis.sismember("set:key", "member1")
members = await redis.smembers("set:key")
await redis.srem("set:key", "member1")
count = await redis.scard("set:key")

# Key operations
await redis.delete("key")
exists = await redis.exists("key")
await redis.expire("key", 3600)
```

### Lifecycle Management

The Redis client lifecycle is managed in `app/main.py`:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup - client initialized lazily on first use
    yield
    # Shutdown - close client
    await close_redis_client()
```

## Current Usage: User Presence

Redis tracks which users are currently online for presence features.

### Key Schema

| Key | Type | TTL | Purpose |
|-----|------|-----|---------|
| `ws:active_users` | Set | None | All online user IDs |

Connection details and heartbeats are managed locally per server instance. Redis is kept minimal - only storing what's needed for cross-server queries (user online status).

## Error Handling

Redis operations in the connection manager are wrapped in try/except to prevent Redis failures from crashing WebSocket connections:

```python
try:
    await redis.hset(key, data)
except Exception as e:
    logger.error("Redis operation failed: %s", e)
    # Connection continues to work with local state only
```

## Future Use Cases

### Game State Caching

```python
# Cache active game state
await redis.set(f"game:{game_id}:state", json.dumps(state), ex=3600)

# Retrieve cached state
cached = await redis.get(f"game:{game_id}:state")
if cached:
    state = json.loads(cached)
```

### Rate Limiting

```python
async def check_rate_limit(user_id: str, limit: int = 100) -> bool:
    key = f"ratelimit:{user_id}:{int(time.time()) // 60}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, 60)
    return count <= limit
```

### Pub/Sub for Real-time Updates

```python
# Publisher (when game state changes)
await redis.publish(f"game:{game_id}", json.dumps(update))

# Subscriber (in a background task)
async for message in redis.subscribe(f"game:{game_id}"):
    # Broadcast to WebSocket connections
    await manager.send_to_game(game_id, message)
```

## Monitoring

### Upstash Console

The Upstash console provides:
- Real-time metrics (commands/sec, memory usage)
- Slow query log
- Key browser
- CLI access

### Application Logging

Redis operations are logged at DEBUG level:
```
DEBUG - Initializing Upstash Redis client
DEBUG - Redis client initialized with URL: https://xxx.upstash.io
ERROR - Failed to store connection xxx in Redis: <error details>
```

Enable debug logging in `.env`:
```env
DEBUG=true
```

## Best Practices

1. **Use appropriate TTLs**: Set expiration on temporary data to prevent memory bloat
2. **Handle failures gracefully**: Redis should enhance, not break, core functionality
3. **Use pipelines for bulk operations**: Reduces round trips
4. **Keep keys organized**: Use consistent prefixes (`ws:`, `game:`, `cache:`)
5. **Monitor memory**: Check Upstash dashboard for memory usage trends
