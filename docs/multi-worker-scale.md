# Ko‘p worker / instansli deploy: umumiy rate limiter va pul qulfi

Hozir `core/rate_limit.py` (sliding window + per-user `asyncio.Lock`) va
`core/shop.py` dagi `ShopStore._lock` (`threading.RLock`) **faqat bitta jarayon
ichida** ishlaydi, `core/economy.py::spend_coins` esa “o‘qi → tekshir → yoz”
ketma-ketligini jarayon qulfi ostida bajaradi. `--workers N` yoki bir nechta
instansda bu uch qatlam umumiy emas: limit `N×2` bo‘ladi, qulflar esa boshqa
jarayondagi so‘rovni to‘xtatmaydi (jarayonlararo double-spend mumkin).

Maqsad — ikkita invariantni klaster bo‘ylab ta’minlash:

1. `scope:user_id` limiti **butun klaster** uchun amal qiladi;
2. `coins` hech qachon manfiy bo‘lmaydi va har bir spin/xarid **atomar** yechiladi.

---

## 1. Interfeys (yangi fayl: `core/limits.py`)

```python
class RateLimiterBackend(Protocol):
    def allow(self, key: str) -> bool: ...
    def retry_after(self, key: str) -> float: ...
    def reset(self) -> None: ...

class UserLockBackend(Protocol):
    async def acquire(self, key: str) -> None: ...
    async def release(self, key: str) -> None: ...

def build_limiter() -> RateLimiterBackend: ...      # RATE_LIMIT_BACKEND
def build_user_lock() -> UserLockBackend: ...       # WALLET_LOCK_BACKEND
```

`core/rate_limit.py` dagi mavjud `RateLimiter` shu protokolning **memory**
implementatsiyasi bo‘lib qoladi; `allow_request()` / `retry_after()` /
`user_lock()` nomlari o‘zgarmaydi (faqat ichida backend’ga delegatsiya).
`api/security.py` (`enforce_rate_limit`) chaqiruv joylarida o‘zgarydi:
`await enforce_rate_limit(...)` — 7 ta endpoint (`buy`, `spin`, `bonus`,
`promo`, `mission`, `quest`, `chest`).

Konfiguratsiya (env):

| Nom | Qiymat | Default |
|---|---|---|
| `RATE_LIMIT_BACKEND` | `auto` \| `memory` \| `redis` \| `db` | `auto` (Redis bo‘lsa redis, aks holda memory) |
| `REDIS_URL` | `rediss://…` | — |
| `WALLET_ATOMIC` | `off` \| `db` | `off` |
| `RATE_LIMIT_FAIL_OPEN` | `true` \| `false` | `true` |

---

## 2. Variant A — Redis (tavsiya: eng tez, DB’ni yuklamaydi)

| Fayl | Vazifa |
|---|---|
| `core/redis_client.py` | `get_redis()` singleton, `socket_timeout=0.25`, TLS, ping |
| `core/rate_limit_redis.py` | `RedisRateLimiter` — bitta `EVAL` (Lua) ichida sliding window: `ZREMRANGEBYSCORE` → `ZCARD` → `ZADD` → `PEXPIRE`; qaytaradi `allowed`, `retry_after_ms` |
| `core/redis_lock.py` | `RedisUserLock` — `SET rl:lock:{key} {token} NX PX 5000`, bo‘shatish Lua `compare-and-del` bilan (begona qulfni o‘chirmaslik uchun); kutish `asyncio.wait_for` + backoff |
| `core/rate_limit.py` | backend tanlash, memory fallback, `reset_*()` testlar uchun |
| `api/server.py` | startupda backend logi: `shared limiter: redis`; ko‘p worker ogohlantirishi **faqat memory** backend’da qoladi |
| `requirements.txt` | `redis>=5,<6` (import `try/except` bilan, ixtiyoriy bog‘liqlik) |

Redis yiqilsa: rate limit `RATE_LIMIT_FAIL_OPEN` bo‘yicha (default — o‘tkazib
yuborish + `logger.warning`), pul amallari esa DB atomikligi bilan himoyalangan
bo‘lib qolaveradi.

---

## 3. Variant B — DB (Supabase/Postgres, Redis bo‘lmasa)

Migratsiya: `sql/20261113_shared_limits.sql`

```sql
create table if not exists rate_limit_hits (
  scope text not null,
  user_id bigint not null,
  window_start timestamptz not null,
  hits int not null default 0,
  primary key (scope, user_id, window_start)
);

create or replace function increment_rate_limit(
  p_scope text, p_user bigint, p_limit int, p_window_ms int
) returns table (allowed boolean, retry_after_ms int) as $$
  -- window_start = to_timestamp(floor(extract(epoch from now())*1000/p_window_ms)*p_window_ms/1000)
  -- INSERT ... ON CONFLICT DO UPDATE SET hits = rate_limit_hits.hits + 1 RETURNING hits
$$ language sql;

create or replace function spend_coins(p_user bigint, p_amount int)
returns bigint as $$
  update users set coins = coins - p_amount
   where user_id = p_user and coins >= p_amount
  returning coins;   -- 0 qator → InsufficientCoinsError
$$ language sql;
```

| Fayl | O‘zgarish |
|---|---|
| `core/rate_limit_db.py` | `client.rpc("increment_rate_limit", {...})` (sync, `safe_*` uslubida) |
| `core/economy.py` | `spend_coins()` — `WALLET_ATOMIC=db` bo‘lsa `rpc("spend_coins")`, aks holda eski yo‘l |
| `core/shop.py` | `buy`/`spin` atomar `spend_coins` dan foydalanadi; ko‘p qatorli invariantlar (bepul spin + inventar) uchun `reserve_free_spin(user_id, day)` RPC |
| `core/wallet_lock.py` | DB advisory lock (`pg_try_advisory_lock(hashtext('wallet:'||user_id))`) — faqat haqiqiy serializatsiya kerak bo‘lsa |

DB varianti sekinroq (har pul amaliga bitta RPC, ~5–15 ms), lekin Redis’siz
ham to‘g‘ri ishlaydi va qo‘shimcha infratuzilma talab qilmaydi.

---

## 4. Migratsiya qadamlari

1. **Interfeys + memory backend** (xatti-harakat o‘zgarmaydi): `core/limits.py`,
   `core/rate_limit.py` delegatsiyasi, `enforce_rate_limit` → `async`.
   Kontrakt testlari (`tests/test_rate_limit_backends.py`) memory ustida yashil.
2. **Redis backend**: `fakeredis` bilan testlar — 2/s limit, `Retry-After`,
   qulfning o‘zaro istisnosi, TTL tugashi, Redis uzilishida fail-open.
3. **DB backend**: SQL migratsiya staging’da; `increment_rate_limit` va
   `spend_coins` RPC’lari; `WALLET_ATOMIC=db` ni **shadow** rejimda yoqish
   (RPC natijasini eski hisob bilan solishtirib log yozish) — 3–7 kun.
4. **Staging’da ikki worker**: `uvicorn --workers 2` + `scripts/live_check_rate_limit.py`
   — 5 parallel xariddan faqat bittasi o‘tishi, `429` butun klaster bo‘ylab.
5. **Prod switch**: `RATE_LIMIT_BACKEND=redis`, `WALLET_ATOMIC=db`; startupda
   `shared limiter: redis` logi, ogohlantirish yo‘q.
6. **Tozalash**: README’dagi “faqat bitta jarayon” cheklovi “umumiy backend”
   bandiga almashtiriladi; memory backend faqat test/dev uchun qoladi.

Har bosqichda qabul mezoni: `python -m unittest discover -s tests` yashil,
`scripts/i18n_audit.py` `exit 0`, `--workers 2` bilan live-check o‘tadi.

---

## 5. Testlar

| Test | Nima tekshiradi |
|---|---|
| `tests/test_rate_limit_backends.py` | bir xil kontrakt: memory / redis(fakeredis) / db(fake rpc) |
| `tests/test_wallet_atomic.py` | 5 parallel `buy`, balans faqat bittasiga yetadi → 1 muvaffaqiyat; `coins >= 0` |
| `tests/test_redis_lock.py` | ikki “jarayon” (ikki klient) uchun `SET NX` qulfi, TTL, noto‘g‘ri token bilan bo‘shatilmasligi |
| `scripts/live_check_rate_limit.py` | `--workers 2` bilan haqiqiy HTTP: `429` va double-spend |

---

## 6. Risklar va qarorlar

- **Redis down** → rate limit fail-open (log bilan), wallet DB atomikligi bilan
  himoyalangan; `RATE_LIMIT_FAIL_OPEN=false` bilan fail-closed (503) mumkin.
- **DB latency** → hozirgi “select + update” o‘rniga bitta RPC: regressiya yo‘q.
- **Bepul spin / inventar** kabi ko‘p qatorli invariantlar uchun RPC yoki
  advisory lock; Redis qulfi faqat Redis mavjud bo‘lsa.
- **Vaqt** manbai — server (`now()` / Redis TTL), mijoz soati ishlatilmaydi.

**Taxminiy hajm:** interfeys 0.5 kun, Redis 1 kun, SQL+RPC integratsiya 1–1.5 kun,
staging sinov va prod switch 0.5 kun.
