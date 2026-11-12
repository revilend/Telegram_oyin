"""Haqiqiy HTTP orqali (uvicorn) rate limit va double-spend tekshiruvi.

Ishga tushirish::

    BOT_TOKEN= ALLOW_GUEST_AUTH=true ALLOW_IN_MEMORY_FALLBACK=true \
        ADMIN_ID=900001 .venv/bin/uvicorn api.server:app --port 8077
    .venv/bin/python scripts/live_check_rate_limit.py
"""

from __future__ import annotations

import asyncio
import time

import httpx

BASE = "http://127.0.0.1:8077"
ADMIN_ID = 900001
SPIN_COST = 20
ITEM_SLUG, ITEM_PRICE = "booster_double_vote", 15
#: 203° — tanga bermaydigan "booster_kevlar" sektori (spin narxi aniq 20 bo'lsin).
NO_COIN_ANGLE = 203

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'OK  ' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(name)


async def coins(client: httpx.AsyncClient, user: int) -> int:
    response = await client.get(f"{BASE}/api/bootstrap", params={"user_id": user})
    response.raise_for_status()
    return int(response.json()["account"]["user"]["coins"])


async def fund(client: httpx.AsyncClient, user: int, amount: int) -> int:
    response = await client.post(
        f"{BASE}/api/admin/balance",
        json={"admin_id": ADMIN_ID, "user_id": user, "coins": amount, "reason": "live"},
    )
    response.raise_for_status()
    return int(response.json()["user"]["coins"])


async def burst(client: httpx.AsyncClient, path: str, body: dict, count: int):
    return await asyncio.gather(
        *(client.post(f"{BASE}{path}", json=body) for _ in range(count))
    )


async def phase_rate_limit(client: httpx.AsyncClient) -> None:
    print("\n== 1) Rate limit: bitta foydalanuvchidan 10 parallel so'rov ==")
    user = 910001
    start = await fund(client, user, 1000)
    started = time.perf_counter()
    responses = await burst(client, "/api/spin/wheel", {"user_id": user}, 10)
    elapsed = time.perf_counter() - started
    codes = [r.status_code for r in responses]
    ok = [r for r in responses if r.status_code == 200]
    limited = [r for r in responses if r.status_code == 429]
    print(f"     statuslar={codes} ({elapsed * 1000:.0f} ms)")

    check("faqat 2 ta so'rov o'tdi (limit 2/s)", len(ok) == 2, f"200={len(ok)}")
    check("qolgan 8 tasi 429", len(limited) == 8, f"429={len(limited)}")
    check(
        "429 javoblarida Retry-After bor",
        all(r.headers.get("Retry-After") for r in limited),
        str({r.headers.get("Retry-After") for r in limited}),
    )
    spent = sum(int(r.json()["expense"]) for r in ok)
    won = sum(int(r.json()["reward"]["coins"]) for r in ok)
    final = await coins(client, user)
    check(
        "balans faqat o'tgan spinlar hisobiga o'zgardi",
        final == start - spent + won,
        f"{start} - {spent} + {won} = {final}",
    )


async def set_coins(client: httpx.AsyncClient, user: int, target: int) -> int:
    """Balansni aniq ``target`` ga keltiradi (admin +/- yordamida)."""
    current = await coins(client, user)
    if target != current:
        await fund(client, user, target - current)
    final = await coins(client, user)
    assert final == target, f"balans {final} != {target}"
    return final


async def phase_cross_scope(client: httpx.AsyncClient) -> None:
    print("\n== 2) Cross-scope double-spend: buy (15) + spin (20), balans faqat 20 ==")
    for round_no in range(5):
        user = 920100 + round_no
        free = await client.post(f"{BASE}/api/spin/wheel", json={"user_id": user})
        check(f"[{round_no + 1}] bepul spin ishlatildi", free.status_code == 200 and free.json()["free"] is True)
        await asyncio.sleep(1.05)
        balance = await set_coins(client, user, SPIN_COST)

        buy, spin = await asyncio.gather(
            client.post(
                f"{BASE}/api/shop/buy",
                json={"user_id": user, "item_slug": ITEM_SLUG},
            ),
            client.post(
                f"{BASE}/api/spin/wheel",
                json={"user_id": user, "stop_angle": NO_COIN_ANGLE},
            ),
        )
        codes = sorted([buy.status_code, spin.status_code])
        spent = 0
        if buy.status_code == 200:
            spent += int(buy.json()["total_price"])
        if spin.status_code == 200:
            spent += int(spin.json()["expense"])
        final = await coins(client, user)
        check(
            f"[{round_no + 1}] faqat bitta amal bajarildi, balans {balance} -> {final}",
            codes.count(200) == 1 and max(codes) == 402 and final == balance - spent,
            f"buy={buy.status_code}, spin={spin.status_code}, spent={spent}, coins={final}",
        )


async def phase_same_scope_burst(client: httpx.AsyncClient) -> None:
    print("\n== 2b) Bir xil scope: 4 parallel xarid, balans faqat bittasiga yetadi ==")
    user = 920200
    await set_coins(client, user, ITEM_PRICE)
    responses = await burst(
        client, "/api/shop/buy", {"user_id": user, "item_slug": ITEM_SLUG}, 4
    )
    codes = [r.status_code for r in responses]
    purchased = [r for r in responses if r.status_code == 200]
    final = await coins(client, user)
    check(
        "faqat 1 ta xarid o'tdi (qolganlari 402/429)",
        len(purchased) == 1 and final == 0,
        f"statuslar={codes}, coins={final}",
    )
    check(
        "5xx javob yo'q",
        all(code < 500 for code in codes),
        f"{codes}",
    )


async def phase_sequential(client: httpx.AsyncClient) -> None:
    print("\n== 3) Ketma-ket xarid: balans faqat bittasiga yetadi ==")
    user = 920004
    await set_coins(client, user, ITEM_PRICE)
    first = await client.post(
        f"{BASE}/api/shop/buy", json={"user_id": user, "item_slug": ITEM_SLUG}
    )
    await asyncio.sleep(1.15)
    second = await client.post(
        f"{BASE}/api/shop/buy", json={"user_id": user, "item_slug": ITEM_SLUG}
    )
    check("birinchi xarid o'tdi", first.status_code == 200, f"status={first.status_code}")
    check("ikkinchisi 402 (429 emas)", second.status_code == 402, f"status={second.status_code}")
    final = await coins(client, user)
    check("balans 0, qarz yo'q", final == 0, f"coins={final}")


async def phase_isolation(client: httpx.AsyncClient) -> None:
    print("\n== 4) Limitlar foydalanuvchilar bo'yicha ajratilgan ==")
    noisy, quiet = 920005, 920006
    await set_coins(client, noisy, 1000)
    await set_coins(client, quiet, ITEM_PRICE)
    responses = await burst(
        client, "/api/shop/buy", {"user_id": noisy, "item_slug": ITEM_SLUG}, 6
    )
    ok = sum(1 for r in responses if r.status_code == 200)
    limited = sum(1 for r in responses if r.status_code == 429)
    check("shovqinli foydalanuvchida 2 ta o'tdi, 4 ta 429", (ok, limited) == (2, 4), f"200={ok}, 429={limited}")
    response = await client.post(
        f"{BASE}/api/shop/buy", json={"user_id": quiet, "item_slug": ITEM_SLUG}
    )
    check("boshqa foydalanuvchi 429 olmadi", response.status_code == 200, f"status={response.status_code}")


async def main() -> None:
    async with httpx.AsyncClient(timeout=20.0) as client:
        await phase_rate_limit(client)
        await phase_cross_scope(client)
        await phase_same_scope_burst(client)
        await phase_sequential(client)
        await phase_isolation(client)

    print()
    if failures:
        print(f"XATO: {len(failures)} ta tekshiruv yiqildi: {failures}")
        raise SystemExit(1)
    print("Barcha tekshiruvlar o'tdi.")


if __name__ == "__main__":
    asyncio.run(main())
