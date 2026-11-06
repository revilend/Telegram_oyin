"""Revilend Mega Store: buyumlar, inventar, omad ğildiragi va jihozlash.

Do'kon uch bo'limdan iborat: tanga paketlari (chek orqali), buyumlar
(ramkalar, unvonlar, boosterlar, çiptalar) va omad ğildiragi.  Balans
:class:`core.economy.EconomyStore` da turadi; inventar ``user_inventory``
jadvalida, xarid tarixi esa ``transactions`` jadvalida saqlanadi.

Supabase sozlanmagan bo'lsa hammasi xotirada ishlaydi — testlar va lokal
ishga tushirish uchun qulay.
"""

from __future__ import annotations

import logging
import os
import random
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from core.db import safe_insert, safe_update, safe_upsert
from core.economy import (
    USERS_ID_COLUMN,
    USERS_TABLE,
    EconomyError,
    EconomyStore,
    UserAccount,
    get_economy,
)

logger = logging.getLogger(__name__)

INVENTORY_TABLE = "user_inventory"
TRANSACTIONS_TABLE = "transactions"

SPIN_COST = 20
SPIN_TICKET_SLUG = "spin_extra"
MAX_BUY_QUANTITY = 10

SPIN = "SPIN"
COSMETIC = "COSMETIC"
BOOSTER = "BOOSTER"
CLAN = "CLAN"
TICKET = "TICKET"

SECTION_ORDER = (SPIN, COSMETIC, BOOSTER, CLAN, TICKET)

SECTION_TITLES = {
    SPIN: "🎰 Omad ğildiragi",
    COSMETIC: "✨ Kosmetika",
    BOOSTER: "🚀 Boosterlar",
    CLAN: "🛡 Klan",
    TICKET: "🎟 Çiptalar",
}


@dataclass(frozen=True)
class ShopItem:
    """Do'kondagi bitta buyum."""

    slug: str
    section: str
    kind: str  # frame | title | booster | ticket | spin
    title: str
    description: str
    price: int
    emoji: str = "🛍"
    payload: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "section": self.section,
            "kind": self.kind,
            "title": self.title,
            "description": self.description,
            "price": self.price,
            "emoji": self.emoji,
            "payload": self.payload,
            "equippable": self.kind in {"frame", "title"},
        }


CATALOG: tuple[ShopItem, ...] = (
    ShopItem(
        slug=SPIN_TICKET_SLUG,
        section=SPIN,
        kind="spin",
        title="Omad ğildiragi çiptasi",
        description="Qoşimça bir marta aylantiriş uçun çipta.",
        price=40,
        emoji="🎰",
    ),
    ShopItem(
        slug="frame_gold",
        section=COSMETIC,
        kind="frame",
        title="Oltin ramka",
        description="Avataringiz atrofida oltin nur soçadi.",
        price=150,
        emoji="🥇",
        payload="gold",
    ),
    ShopItem(
        slug="frame_neon",
        section=COSMETIC,
        kind="frame",
        title="Neon ramka",
        description="Yorqin neon halqa — profil darağalanganda körinadi.",
        price=220,
        emoji="💠",
        payload="neon",
    ),
    ShopItem(
        slug="frame_fire",
        section=COSMETIC,
        kind="frame",
        title="Olov ramka",
        description="Qizil-olov halqasi eng faol öyinçilar uçun.",
        price=180,
        emoji="🔥",
        payload="fire",
    ),
    ShopItem(
        slug="title_don",
        section=COSMETIC,
        kind="title",
        title="«Don Krestniy» unvoni",
        description="Ismingiz ostida nufuzli unvon körinadi.",
        price=250,
        emoji="👑",
        payload="Don Krestniy",
    ),
    ShopItem(
        slug="title_boss",
        section=COSMETIC,
        kind="title",
        title="«Bunker Boshliği» unvoni",
        description="Bunkerni boshqarganlarga munosib unvon.",
        price=180,
        emoji="🛡",
        payload="Bunker Boshliği",
    ),
    ShopItem(
        slug="booster_shield",
        section=BOOSTER,
        kind="booster",
        title="Bunker Qalqoni",
        description="Haydalişdan bir marta saqlaydi.",
        price=50,
        emoji="🛡",
        payload="shield",
    ),
    ShopItem(
        slug="booster_double_vote",
        section=BOOSTER,
        kind="booster",
        title="2 karra ovoz",
        description="Bitta ovoz berişda ovozingizni ikkilantiradi.",
        price=15,
        emoji="✖️",
        payload="double_vote",
    ),
    ShopItem(
        slug="booster_kevlar",
        section=BOOSTER,
        kind="booster",
        title="Kevlar jilet",
        description="Mafiyada bir marta ölimdan saqlaydi.",
        price=40,
        emoji="🦺",
        payload="kevlar",
    ),
    ShopItem(
        slug="booster_spy_radar",
        section=BOOSTER,
        kind="booster",
        title="Josus radari",
        description="3 ta notöğri joyni öçiradi.",
        price=20,
        emoji="🛰",
        payload="spy_radar",
    ),
    ShopItem(
        slug="clan_emblem",
        section=CLAN,
        kind="frame",
        title="Klan emblemi",
        description="Klaningiz ramzi — avatar atrofida körinadi.",
        price=400,
        emoji="⚜️",
        payload="clan",
    ),
    ShopItem(
        slug="tournament_ticket",
        section=TICKET,
        kind="ticket",
        title="Turnir çiptasi",
        description="Haftalik turnirlarda qatnaşiş uçun çipta.",
        price=180,
        emoji="🎟",
        payload="tournament",
    ),
)

CATALOG_BY_SLUG: dict[str, ShopItem] = {item.slug: item for item in CATALOG}


@dataclass(frozen=True)
class WheelSegment:
    """Omad ğildiragining bitta sektori."""

    key: str
    label: str
    weight: int
    coins: int = 0
    item_slug: str = ""
    emoji: str = "🎁"

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "emoji": self.emoji,
            "coins": self.coins,
            "item_slug": self.item_slug,
        }


WHEEL_SEGMENTS: tuple[WheelSegment, ...] = (
    WheelSegment("coins_10", "10 tanga", 26, coins=10, emoji="🪙"),
    WheelSegment("coins_50", "50 tanga", 20, coins=50, emoji="🪙"),
    WheelSegment("coins_100", "100 tanga", 10, coins=100, emoji="💰"),
    WheelSegment("coins_500", "500 tanga", 2, coins=500, emoji="💎"),
    WheelSegment("booster_shield", "Bunker Qalqoni", 8, item_slug="booster_shield", emoji="🛡"),
    WheelSegment("booster_kevlar", "Kevlar jilet", 8, item_slug="booster_kevlar", emoji="🦺"),
    WheelSegment("booster_spy_radar", "Josus radari", 8, item_slug="booster_spy_radar", emoji="🛰"),
    WheelSegment(
        "booster_double_vote", "2 karra ovoz", 8, item_slug="booster_double_vote", emoji="✖️"
    ),
    WheelSegment("frame_gold", "Oltin ramka", 5, item_slug="frame_gold", emoji="🥇"),
    WheelSegment("frame_neon", "Neon ramka", 3, item_slug="frame_neon", emoji="💠"),
    WheelSegment("title_boss", "Bunker Boshliği", 2, item_slug="title_boss", emoji="🛡"),
)


class ShopError(Exception):
    """Do'kon amali bajarilmadi."""


class UnknownItemError(ShopError):
    """Bunday buyum katalogda yo'q."""


class ShopInsufficientCoinsError(ShopError):
    """Balansda tanga yetmaydi."""


class SpinUnavailableError(ShopError):
    """Bepul aylantiriş ham, çipta ham, tanga ham yo'q."""


class EquipError(ShopError):
    """Buyumni taqish yoki yechish mumkin emas."""


@dataclass(frozen=True)
class InventoryEntry:
    """Foydalanuvchi inventaridagi bitta buyum."""

    item_slug: str
    quantity: int
    is_equipped: bool = False

    @property
    def item(self) -> ShopItem | None:
        return CATALOG_BY_SLUG.get(self.item_slug)

    def as_dict(self) -> dict[str, Any]:
        item = self.item
        return {
            "slug": self.item_slug,
            "quantity": self.quantity,
            "is_equipped": self.is_equipped,
            "title": item.title if item else self.item_slug,
            "kind": item.kind if item else "",
            "section": item.section if item else "",
            "emoji": item.emoji if item else "🛍",
        }


@dataclass(frozen=True)
class PurchaseResult:
    """Xarid natijasi."""

    item: ShopItem
    quantity: int
    total_price: int
    account: UserAccount
    entry: InventoryEntry

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "item": self.item.as_dict(),
            "quantity": self.quantity,
            "total_price": self.total_price,
            "coins": self.account.coins,
            "inventory": self.entry.as_dict(),
        }


@dataclass(frozen=True)
class SpinResult:
    """Aylantiriş natijasi."""

    segment: WheelSegment
    free: bool
    ticket_used: bool
    expense: int
    account: UserAccount
    entry: InventoryEntry | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "segment": self.segment.as_dict(),
            "free": self.free,
            "ticket_used": self.ticket_used,
            "expense": self.expense,
            "coins": self.account.coins,
            "reward": {
                "kind": "coins" if self.segment.coins else "item",
                "coins": self.segment.coins,
                "item": self.entry.as_dict() if self.entry else None,
            },
        }


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_moment(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        moment = value
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            moment = datetime.fromisoformat(text)
        except ValueError:
            return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def pick_segment(rng: random.Random | None = None) -> WheelSegment:
    """Og'irlik bo'yicha ğildirak sektorini tanlaydi."""
    generator = rng or random
    total = sum(segment.weight for segment in WHEEL_SEGMENTS)
    roll = generator.uniform(0, total)
    upto = 0.0
    for segment in WHEEL_SEGMENTS:
        upto += segment.weight
        if roll <= upto:
            return segment
    return WHEEL_SEGMENTS[-1]


class ShopStore:
    """Buyumlar, inventar va omad ğildiragini boshqaradi."""

    def __init__(
        self,
        economy: EconomyStore | None = None,
        client: Any | None = None,
    ) -> None:
        self.economy = economy if economy is not None else get_economy()
        self._client = client
        self._lock = threading.RLock()
        # user_id -> item_slug -> {"quantity": int, "is_equipped": bool}
        self._inventory: dict[int, dict[str, dict[str, Any]]] = {}
        self._last_spin: dict[int, datetime] = {}
        self._transactions: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Supabase bilan ishlash
    # ------------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return self._client is not None or self.economy.enabled

    @property
    def client(self) -> Any:
        if self._client is not None:
            return self._client
        return self.economy.client

    def _rows(self, user_id: int) -> list[dict[str, Any]]:
        """Foydalanuvchi inventar qatorlarini qaytaradi (baza yoki xotira)."""
        uid = int(user_id)
        if not self.enabled:
            return [
                {"item_slug": slug, **values}
                for slug, values in self._inventory.get(uid, {}).items()
            ]
        try:
            return (
                self.client.table(INVENTORY_TABLE)
                .select("*")
                .eq("user_id", uid)
                .execute()
                .data
                or []
            )
        except Exception:
            logger.exception("Inventarni öqib bölmadi: %s", uid)
            return []

    def _save_entry(self, user_id: int, entry: InventoryEntry) -> None:
        uid = int(user_id)
        with self._lock:
            bucket = self._inventory.setdefault(uid, {})
            bucket[entry.item_slug] = {
                "quantity": entry.quantity,
                "is_equipped": entry.is_equipped,
            }
        if not self.enabled:
            return
        try:
            safe_upsert(
                self.client,
                INVENTORY_TABLE,
                {
                    "user_id": uid,
                    "item_slug": entry.item_slug,
                    "quantity": entry.quantity,
                    "is_equipped": entry.is_equipped,
                },
                on_conflict="user_id,item_slug",
            )
        except Exception:
            logger.exception("Inventarga yozib bölmadi: %s %s", uid, entry.item_slug)

    def _record_transaction(
        self, user_id: int, item: ShopItem, quantity: int, total: int
    ) -> None:
        row = {
            "user_id": int(user_id),
            "item_slug": item.slug,
            "quantity": int(quantity),
            "unit_price": int(item.price),
            "total_price": int(total),
            "currency": "coins",
        }
        with self._lock:
            self._transactions.append({**row, "created_at": _now().isoformat()})
            if len(self._transactions) > 500:
                self._transactions = self._transactions[-500:]
        if not self.enabled:
            return
        try:
            safe_insert(self.client, TRANSACTIONS_TABLE, row)
        except Exception:
            logger.exception("Xarid tarixini yozib bölmadi: %s", user_id)

    # ------------------------------------------------------------------
    # Katalog va inventar
    # ------------------------------------------------------------------
    def items_payload(self, user_id: int | None = None) -> dict[str, Any]:
        """Bölumlar bo'yicha buyumlar, inventar va ğildirak holati."""
        sections: list[dict[str, Any]] = []
        for section in SECTION_ORDER:
            items = [item for item in CATALOG if item.section == section]
            if not items:
                continue
            sections.append(
                {
                    "key": section,
                    "title": SECTION_TITLES[section],
                    "items": [item.as_dict() for item in items],
                }
            )
        payload: dict[str, Any] = {
            "sections": sections,
            "wheel": {
                "cost": SPIN_COST,
                "segments": [segment.as_dict() for segment in WHEEL_SEGMENTS],
            },
        }
        if user_id is not None:
            payload["inventory"] = [entry.as_dict() for entry in self.inventory(user_id)]
            payload["equipped"] = self.equipped(user_id)
            payload["spin"] = self.spin_status(user_id)
            payload["coins"] = self.economy.ensure_user(user_id).coins
        return payload

    def inventory(self, user_id: int) -> list[InventoryEntry]:
        """Foydalanuvchi inventari."""
        entries: dict[str, InventoryEntry] = {}
        for row in self._rows(user_id):
            slug = str(row.get("item_slug") or "")
            if slug not in CATALOG_BY_SLUG:
                continue
            entries[slug] = InventoryEntry(
                item_slug=slug,
                quantity=int(row.get("quantity") or 0),
                is_equipped=bool(row.get("is_equipped")),
            )
        return sorted(entries.values(), key=lambda entry: entry.item_slug)

    def entry(self, user_id: int, slug: str) -> InventoryEntry:
        """Bitta buyum bo'yicha inventar yozuvi (yo'q bo'lsa 0 dona)."""
        for row in self._rows(user_id):
            if str(row.get("item_slug") or "") == slug:
                return InventoryEntry(
                    item_slug=slug,
                    quantity=int(row.get("quantity") or 0),
                    is_equipped=bool(row.get("is_equipped")),
                )
        return InventoryEntry(item_slug=slug, quantity=0)

    def equipped(self, user_id: int) -> dict[str, str]:
        """Taqilgan ramka va unvon: ``{"frame": slug, "title": slug}``."""
        result = {"frame": "", "title": ""}
        for entry in self.inventory(user_id):
            item = entry.item
            if item is None or not entry.is_equipped:
                continue
            if item.kind in {"frame", "title"} and not result[item.kind]:
                result[item.kind] = entry.item_slug
        return result

    def spin_status(self, user_id: int, now: datetime | None = None) -> dict[str, Any]:
        """Bepul aylantiriş, çipta va narx haqida ma'lumot."""
        moment = now or _now()
        last = self._last_free_spin(user_id)
        free = last is None or last.date() != moment.date()
        return {
            "free": free,
            "cost": SPIN_COST,
            "ticket_slug": SPIN_TICKET_SLUG,
            "tickets": self.entry(user_id, SPIN_TICKET_SLUG).quantity,
            "last_free_spin_at": last.isoformat() if last else "",
        }

    # ------------------------------------------------------------------
    # Xarid
    # ------------------------------------------------------------------
    def buy(self, user_id: int, slug: str, quantity: int = 1) -> PurchaseResult:
        """Buyumni tangalarga sotib oladi va inventarga qo'shadi."""
        item = CATALOG_BY_SLUG.get(str(slug or ""))
        if item is None:
            raise UnknownItemError("Bunday buyum dökonda yöq")
        try:
            count = int(quantity)
        except (TypeError, ValueError):
            raise ShopError("Miqdor butun son bölmadi") from None
        if count < 1 or count > MAX_BUY_QUANTITY:
            raise ShopError(f"Miqdor 1 dan {MAX_BUY_QUANTITY} gacha böladi")

        uid = int(user_id)
        total = item.price * count
        account = self.economy.ensure_user(uid)
        if account.coins < total:
            raise ShopInsufficientCoinsError(
                f"Balansda yetarli tanga yöq: {account.coins} ta bor, "
                f"{total} ta kerak"
            )

        current = self.entry(uid, item.slug)
        updated = InventoryEntry(
            item_slug=item.slug,
            quantity=current.quantity + count,
            is_equipped=current.is_equipped,
        )
        self._save_entry(uid, updated)
        try:
            account = self.economy.spend_coins(uid, total)
        except EconomyError:
            # Tanga yechilmadi — inventar yozuvini qaytaramiz.
            self._save_entry(
                uid,
                InventoryEntry(
                    item_slug=item.slug,
                    quantity=current.quantity,
                    is_equipped=current.is_equipped,
                ),
            )
            raise
        self._record_transaction(uid, item, count, total)
        return PurchaseResult(
            item=item,
            quantity=count,
            total_price=total,
            account=account,
            entry=updated,
        )

    # ------------------------------------------------------------------
    # Omad ğildiragi
    # ------------------------------------------------------------------
    def _last_free_spin(self, user_id: int) -> datetime | None:
        uid = int(user_id)
        if not self.enabled:
            return self._last_spin.get(uid)
        try:
            rows = (
                self.client.table(USERS_TABLE)
                .select(f"{USERS_ID_COLUMN},last_free_spin_at")
                .eq(USERS_ID_COLUMN, uid)
                .limit(1)
                .execute()
                .data
                or []
            )
        except Exception:
            logger.exception("Oxirgi aylantiriş vaqtini öqib bölmadi: %s", uid)
            return self._last_spin.get(uid)
        if not rows:
            return None
        parsed = _parse_moment(rows[0].get("last_free_spin_at"))
        if parsed is not None:
            self._last_spin[uid] = parsed
        return parsed

    def _mark_free_spin(self, user_id: int, moment: datetime) -> None:
        uid = int(user_id)
        with self._lock:
            self._last_spin[uid] = moment
        if not self.enabled:
            return
        try:
            safe_update(
                self.client,
                USERS_TABLE,
                {"last_free_spin_at": moment.isoformat()},
                {USERS_ID_COLUMN: uid},
            )
        except Exception:
            logger.exception("Aylantiriş vaqtini saqlab bölmadi: %s", uid)

    def spin(
        self,
        user_id: int,
        *,
        now: datetime | None = None,
        rng: random.Random | None = None,
    ) -> SpinResult:
        """Ğildirakni aylantiradi: kuniga bir bepul, keyin çipta yoki 20 tanga."""
        uid = int(user_id)
        moment = now or _now()
        status = self.spin_status(uid, moment)
        free = bool(status["free"])
        ticket_used = False
        expense = 0

        if free:
            self._mark_free_spin(uid, moment)
        else:
            ticket = self.entry(uid, SPIN_TICKET_SLUG)
            if ticket.quantity > 0:
                self._save_entry(
                    uid,
                    InventoryEntry(
                        item_slug=SPIN_TICKET_SLUG,
                        quantity=ticket.quantity - 1,
                        is_equipped=ticket.is_equipped,
                    ),
                )
                ticket_used = True
            else:
                account = self.economy.ensure_user(uid)
                if account.coins < SPIN_COST:
                    raise SpinUnavailableError(
                        "Bepul aylantiriş işlatilgan. Çipta yöq va "
                        f"{SPIN_COST} tanga ham yetarli emas."
                    )
                self.economy.spend_coins(uid, SPIN_COST)
                expense = SPIN_COST

        segment = pick_segment(rng)
        entry: InventoryEntry | None = None
        if segment.coins:
            account = self.economy.add_coins(uid, segment.coins)
        else:
            item = CATALOG_BY_SLUG[segment.item_slug]
            current = self.entry(uid, item.slug)
            entry = InventoryEntry(
                item_slug=item.slug,
                quantity=current.quantity + 1,
                is_equipped=current.is_equipped,
            )
            self._save_entry(uid, entry)
            account = self.economy.ensure_user(uid)

        return SpinResult(
            segment=segment,
            free=free,
            ticket_used=ticket_used,
            expense=expense,
            account=account,
            entry=entry,
        )

    # ------------------------------------------------------------------
    # Jihozlash
    # ------------------------------------------------------------------
    def equip(self, user_id: int, slug: str, equip: bool = True) -> dict[str, Any]:
        """Ramka yoki unvonni taqadi/yeçadi va profil holatini qaytaradi."""
        item = CATALOG_BY_SLUG.get(str(slug or ""))
        if item is None:
            raise UnknownItemError("Bunday buyum dökonda yöq")
        if item.kind not in {"frame", "title"}:
            raise EquipError("Faqat ramka va unvonni taqiş mumkin")

        uid = int(user_id)
        entry = self.entry(uid, item.slug)
        if entry.quantity <= 0:
            raise EquipError("Avval bu buyumni sotib oling")

        if equip:
            for other in self.inventory(uid):
                other_item = other.item
                if (
                    other_item is not None
                    and other_item.kind == item.kind
                    and other.is_equipped
                    and other.item_slug != item.slug
                ):
                    self._save_entry(
                        uid,
                        InventoryEntry(
                            item_slug=other.item_slug,
                            quantity=other.quantity,
                            is_equipped=False,
                        ),
                    )
        self._save_entry(
            uid,
            InventoryEntry(
                item_slug=item.slug,
                quantity=entry.quantity,
                is_equipped=bool(equip),
            ),
        )
        return {
            "ok": True,
            "item": item.as_dict(),
            "is_equipped": bool(equip),
            "equipped": self.equipped(uid),
        }

    def transactions(self) -> list[dict[str, Any]]:
        """Xotiradagi xarid tarixi (testlar va diagnostika uchun)."""
        return list(self._transactions)


_store: ShopStore | None = None
_store_lock = threading.Lock()


def get_shop_store() -> ShopStore:
    """Umumiy ShopStore nusxasini qaytaradi."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = ShopStore()
    return _store


def set_shop_store(store: ShopStore | None) -> None:
    """Global do'kon omborini almashtiradi (testlar uchun)."""
    global _store
    _store = store


def shop_enabled() -> bool:
    """Do'kon Supabase'da ishlayaptimi (diagnostika uchun)."""
    return get_shop_store().enabled


def booster_payload_options() -> list[dict[str, Any]]:
    """Do'kondagi boosterlarni bot uchun qulay ko'rinishda qaytaradi."""
    return [item.as_dict() for item in CATALOG if item.section == BOOSTER]


def seller_username() -> str:
    """Karta egasi/bot nomi uchun yordamchi."""
    return (os.getenv("BOT_USERNAME") or "revilend_gamesbot").strip().lstrip("@")


__all__ = [
    "BOOSTER",
    "CATALOG",
    "CATALOG_BY_SLUG",
    "CLAN",
    "COSMETIC",
    "EquipError",
    "InventoryEntry",
    "MAX_BUY_QUANTITY",
    "PurchaseResult",
    "SECTION_ORDER",
    "SECTION_TITLES",
    "SPIN",
    "SPIN_COST",
    "SPIN_TICKET_SLUG",
    "ShopError",
    "ShopInsufficientCoinsError",
    "ShopItem",
    "ShopStore",
    "SpinResult",
    "SpinUnavailableError",
    "TICKET",
    "UnknownItemError",
    "WHEEL_SEGMENTS",
    "WheelSegment",
    "booster_payload_options",
    "get_shop_store",
    "pick_segment",
    "set_shop_store",
    "shop_enabled",
]
