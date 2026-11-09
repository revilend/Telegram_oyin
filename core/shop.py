"""Revilend Mega Store: buyumlar, inventar, omad ğildiragi va jihozlash.

Do'kon uch bo'limdan iborat: tanga paketlari (chek orqali), buyumlar
(ramkalar, unvonlar, boosterlar, çiptalar) va omad ğildiragi.  Balans
:class:`core.economy.EconomyStore` da turadi; inventar ``user_inventory``
jadvalida, xarid tarixi esa ``shop_transactions`` jadvalida saqlanadi.

Supabase sozlanmagan bo'lsa hammasi xotirada ishlaydi — testlar va lokal
ishga tushirish uchun qulay.
"""

from __future__ import annotations

import logging
import os
import random
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
TRANSACTIONS_TABLE = "shop_transactions"
LEGACY_TRANSACTIONS_TABLE = "transactions"

SPIN_COST = 20
TASHKENT = timezone(timedelta(hours=5))


def _history_bound(value: Any, *, end: bool = False) -> str:
    """Tarix filtri uchun sanani Toshkent kunidan UTC ISO ga aylantiradi."""
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        if len(text) == 10:
            moment = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=TASHKENT)
            if end:
                moment = moment.replace(hour=23, minute=59, second=59, microsecond=999999)
        else:
            moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=TASHKENT)
    except ValueError:
        return ""
    return moment.astimezone(timezone.utc).isoformat()


def _history_moment(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


SPIN_TICKET_SLUG = "spin_extra"
MAX_BUY_QUANTITY = 10

# Eski do'konda ishlatilgan nomlar yangi katalog sluglariga ko'chiriladi.
# Shu bilan avval sotib olingan ramkalar ham taqiladi va yo'qolmaydi.
LEGACY_SLUG_ALIASES = {
    "frame_cyber_glitch": "frame_cyber",
    "frame_fire_dragon": "frame_fire",
    "frame_diamond_vip": "frame_diamond",
    "cyber_glitch": "frame_cyber",
    "fire_dragon": "frame_fire",
    "diamond_vip": "frame_diamond",
}


def canonical_slug(slug: Any) -> str:
    """Eski buyum nomini joriy katalog slugiga aylantiradi."""
    value = str(slug or "").strip()
    return LEGACY_SLUG_ALIASES.get(value, value)

BOOSTER = "BOOSTER"
FRAME = "FRAME"
TITLE = "TITLE"
SPECIAL = "SPECIAL"

# Eski bo'lim nomlari (moslik uchun saqlanadi).
SPIN = "SPIN"
COSMETIC = "COSMETIC"
CLAN = "CLAN"
TICKET = "TICKET"

SECTION_ORDER = (BOOSTER, FRAME, TITLE, SPECIAL)

SECTION_TITLES = {
    BOOSTER: "🚀 Busterlar",
    FRAME: "🎨 Ramkalar",
    TITLE: "👑 Unvonlar",
    SPECIAL: "🎁 Maxsus",
}

LOOTBOX_SLUG = "lootbox"
SPIN_TICKET_PACK = 5
LOOTBOX_POOL = (
    "booster_shield",
    "booster_kevlar",
    "booster_double_vote",
    "booster_spy_radar",
    "booster_bomb_magnet",
    "booster_time_master",
    "booster_double_coins",
    "frame_gold",
    "frame_neon",
    "frame_cyber",
    "frame_fire",
    "frame_diamond",
    "title_boss",
    "title_shadow",
)


@dataclass(frozen=True)
class ShopItem:
    """Do'kondagi bitta buyum."""

    slug: str
    section: str
    kind: str  # frame | title | booster | ticket | spin | special
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
    # ---------------------------- Busterlar ----------------------------
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
        slug="booster_kevlar",
        section=BOOSTER,
        kind="booster",
        title="Kevlar Jilet",
        description="Mafiyada bir marta ölimdan saqlaydi.",
        price=40,
        emoji="🦺",
        payload="kevlar",
    ),
    ShopItem(
        slug="booster_double_vote",
        section=BOOSTER,
        kind="booster",
        title="2x Ovoz",
        description="Bitta ovoz berişda ovozingizni ikkilantiradi.",
        price=15,
        emoji="✖️",
        payload="double_vote",
    ),
    ShopItem(
        slug="booster_bomb_magnet",
        section=BOOSTER,
        kind="booster",
        title="Bomba Magniti",
        description="Bomba öyinida xavfli kartani bir marta chetlab ötadi.",
        price=60,
        emoji="🧲",
        payload="bomb_magnet",
    ),
    ShopItem(
        slug="booster_spy_radar",
        section=BOOSTER,
        kind="booster",
        title="Josus Radari",
        description="Josusda 3 ta notöğri joyni öçiradi.",
        price=20,
        emoji="🛰",
        payload="spy_radar",
    ),
    ShopItem(
        slug="booster_time_master",
        section=BOOSTER,
        kind="booster",
        title="Vaqt Ustasi",
        description="Aliasda raundga qoşimça vaqt qöşadi.",
        price=45,
        emoji="⏱",
        payload="time_master",
    ),
    ShopItem(
        slug="booster_double_coins",
        section=BOOSTER,
        kind="booster",
        title="2x Tanga Qopçiği",
        description="Keyingi ğalabada tanga mukofotini ikkilantiradi.",
        price=70,
        emoji="💰",
        payload="double_coins",
    ),
    # ----------------------------- Ramkalar -----------------------------
    ShopItem(
        slug="frame_gold",
        section=FRAME,
        kind="frame",
        title="Oltin",
        description="Avataringiz atrofida oltin nur soçadi.",
        price=150,
        emoji="🥇",
        payload="gold",
    ),
    ShopItem(
        slug="frame_neon",
        section=FRAME,
        kind="frame",
        title="Neon",
        description="Yorqin neon halqa — profilda yaqqol körinadi.",
        price=220,
        emoji="💠",
        payload="neon",
    ),
    ShopItem(
        slug="frame_cyber",
        section=FRAME,
        kind="frame",
        title="Kiber Glitch",
        description="Rağamli glitch effekti bilan kiber ramka.",
        price=320,
        emoji="🧬",
        payload="cyber",
    ),
    ShopItem(
        slug="frame_fire",
        section=FRAME,
        kind="frame",
        title="Olovli Ajdaho",
        description="Qizil-olov halqasi eng faol öyinçilar uçun.",
        price=260,
        emoji="🔥",
        payload="fire",
    ),
    ShopItem(
        slug="frame_diamond",
        section=FRAME,
        kind="frame",
        title="Olmos VIP",
        description="Olmos kabi yaltiraydigan premium VIP ramka.",
        price=500,
        emoji="💎",
        payload="diamond",
    ),
    # ----------------------------- Unvonlar -----------------------------
    ShopItem(
        slug="title_don",
        section=TITLE,
        kind="title",
        title="👑 Mafiya Otaxoni",
        description="Mafiya stolining eng nufuzli unvoni.",
        price=300,
        emoji="👑",
        payload="Mafiya Otaxoni",
    ),
    ShopItem(
        slug="title_boss",
        section=TITLE,
        kind="title",
        title="🛡 Daxlsiz",
        description="Sizga heç kim yeta olmaydi — daxlsiz unvon.",
        price=180,
        emoji="🛡",
        payload="Daxlsiz",
    ),
    ShopItem(
        slug="title_shadow",
        section=TITLE,
        kind="title",
        title="👻 Körinmas Soya",
        description="Reytingda soyadek sezilmas, lekin kuchli unvon.",
        price=280,
        emoji="👻",
        payload="Körinmas Soya",
    ),
    # ------------------------------ Maxsus ------------------------------
    ShopItem(
        slug=SPIN_TICKET_SLUG,
        section=SPECIAL,
        kind="spin",
        title="5x Omad Çiptasi",
        description="Bir xaridda 5 ta aylantiriş çiptasi.",
        price=160,
        emoji="🎁",
        payload="5",
    ),
    ShopItem(
        slug=LOOTBOX_SLUG,
        section=SPECIAL,
        kind="special",
        title="Sirli Quti",
        description="Ichida tasodifiy buster, ramka yoki unvon bor.",
        price=120,
        emoji="🎁",
        payload="lootbox",
    ),
    # -------------------- Eski buyumlar (moslik uchun) -------------------
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


# G'ildirakda aynan 8 ta sektor: har biri 45°, mini app ham shu tartibda chizadi.
WHEEL_SEGMENTS: tuple[WheelSegment, ...] = (
    WheelSegment("coins_20", "20 tanga", 22, coins=20, emoji="🪙"),
    WheelSegment("booster_shield", "Qalqon", 8, item_slug="booster_shield", emoji="🛡"),
    WheelSegment("coins_50", "50 tanga", 14, coins=50, emoji="🪙"),
    WheelSegment("booster_kevlar", "Jilet", 8, item_slug="booster_kevlar", emoji="🦺"),
    WheelSegment("coins_100", "100 tanga", 7, coins=100, emoji="💰"),
    WheelSegment(
        "booster_double_vote", "2 karra ovoz", 8, item_slug="booster_double_vote", emoji="📢"
    ),
    WheelSegment("mystery", "Sirli sovg'a", 5, emoji="🎁"),
    WheelSegment("coins_10", "10 tanga", 28, coins=10, emoji="🪙"),
)

# "Sirli sovg'a" sektori tasodifiy noyob buyumni beradi.
MYSTERY_SLUGS: tuple[str, ...] = (
    "booster_spy_radar",
    "frame_gold",
    "frame_neon",
    "title_boss",
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
    loot: tuple[ShopItem, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "item": self.item.as_dict(),
            "quantity": self.quantity,
            "total_price": self.total_price,
            "coins": self.account.coins,
            "inventory": self.entry.as_dict(),
            "loot": [prize.as_dict() for prize in self.loot],
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


def _normalize_transaction(row: dict[str, Any]) -> dict[str, Any]:
    """Tranzaksiya qatorini eski va yangi Supabase sxemalaridan bir ko'rinishga keltiradi.

    Ba'zi o'rnatishlarda ``shop_transactions`` ustunlari ``item_id``,
    ``item_title`` va ``price_coins`` deb nomlangan. Kod ikkala nomlash
    uslubini ham o'qiydi, shuning uchun xaridlar tarixi bo'sh ko'rinmaydi.
    """
    result = dict(row)
    slug = str(result.get("item_slug") or result.get("item_id") or "")
    try:
        quantity = int(result.get("quantity") or 1)
    except (TypeError, ValueError):
        quantity = 1
    total = result.get("total_price")
    if total is None:
        total = result.get("price_coins")
    if total is None:
        total = result.get("amount")
    try:
        total_price = int(total or 0)
    except (TypeError, ValueError):
        total_price = 0
    unit = result.get("unit_price")
    if unit is None:
        unit = result.get("price_coins")
    try:
        unit_price = int(unit or 0)
    except (TypeError, ValueError):
        unit_price = 0
    result.update(
        {
            "item_slug": slug,
            "item_id": slug,
            "item_title": str(result.get("item_title") or ""),
            "quantity": max(1, quantity),
            "unit_price": unit_price,
            "total_price": total_price,
            "price_coins": total_price,
        }
    )
    return result


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

    def _memory_rows(self, user_id: int) -> list[dict[str, Any]]:
        """Joriy jarayondagi inventar nusxasini qaytaradi."""
        return [
            {"item_slug": slug, **values}
            for slug, values in self._inventory.get(int(user_id), {}).items()
        ]

    def _rows(self, user_id: int) -> list[dict[str, Any]]:
        """Foydalanuvchi inventar qatorlarini qaytaradi (baza + xotira)."""
        uid = int(user_id)
        if not self.enabled:
            return self._memory_rows(uid)
        try:
            rows = (
                self.client.table(INVENTORY_TABLE)
                .select("*")
                .eq("user_id", uid)
                .execute()
                .data
                or []
            )
        except Exception:
            logger.exception("Inventarni öqib bölmadi: %s", uid)
            return self._memory_rows(uid)

        # Supabase javobi bir zum kechiksa ham, shu jarayonda yozilgan
        # xarid profilda darhol ko'rinadi. Bazadagi qator ustuvor turadi.
        merged = {
            str(row.get("item_slug") or ""): dict(row)
            for row in rows
            if isinstance(row, dict) and row.get("item_slug")
        }
        for row in self._memory_rows(uid):
            slug = str(row.get("item_slug") or "")
            if slug in merged:
                # Joriy jarayondagi taqish/yeçish eng so'nggi holat. Supabase
                # yozuvi kechiksa yoki xato bersa, eski `is_equipped` yangi
                # tanlovni bosib ketmasligi kerak.
                merged[slug]["is_equipped"] = bool(row.get("is_equipped"))
            elif slug:
                merged[slug] = row
        return list(merged.values())

    def _save_entry(
        self, user_id: int, entry: InventoryEntry, *, strict: bool = False
    ) -> None:
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
        except Exception as exc:
            logger.exception("Inventarga yozib bölmadi: %s %s", uid, entry.item_slug)
            if strict:
                raise ShopError(
                    "Taqilgan buyumni Supabase'ga saqlab bo'lmadi. "
                    "Qayta urinib köring."
                ) from exc

    def _record_transaction(
        self, user_id: int, item: ShopItem, quantity: int, total: int
    ) -> None:
        # Ikkala Supabase sxemasini ham qo'llab-quvvatlaymiz: joriy
        # `item_slug/total_price` va eski `item_id/item_title/price_coins`.
        # `safe_insert` mavjud bo'lmagan ustunlarni avtomatik olib tashlaydi.
        row = {
            "user_id": int(user_id),
            "item_slug": item.slug,
            "item_id": item.slug,
            "item_title": item.title,
            "quantity": int(quantity),
            "unit_price": int(item.price),
            "total_price": int(total),
            "price_coins": int(total),
            "currency": "coins",
            "kind": "buy",
        }
        with self._lock:
            self._transactions.append({**row, "created_at": _now().isoformat()})
            if len(self._transactions) > 500:
                self._transactions = self._transactions[-500:]
        if not self.enabled:
            return
        legacy_row = {
            "user_id": int(user_id),
            "item_slug": item.slug,
            "kind": "buy",
            "amount": int(total),
        }
        # Yangi `shop_transactions` jadvali; eski o'rnatishlar uchun
        # `transactions`ga ham qayta urinamiz.
        for table, payload in (
            (TRANSACTIONS_TABLE, row),
            (LEGACY_TRANSACTIONS_TABLE, legacy_row),
        ):
            try:
                safe_insert(self.client, table, payload)
                return
            except Exception:
                logger.warning(
                    "Xarid tarixini %s jadvaliga yozib bo'lmadi: %s",
                    table,
                    user_id,
                )
        logger.error("Xarid tarixi saqlanmadi: %s", user_id)

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
        """Foydalanuvchi inventari (eski sluglar yangisiga ko'çiriladi)."""
        entries: dict[str, InventoryEntry] = {}
        for row in self._rows(user_id):
            slug = canonical_slug(row.get("item_slug"))
            if slug not in CATALOG_BY_SLUG:
                continue
            raw_slug = str(row.get("item_slug") or "")
            legacy = raw_slug != slug
            quantity = int(row.get("quantity") or 0)
            equipped = bool(row.get("is_equipped"))
            current = entries.get(slug)
            if current is not None:
                quantity += current.quantity
                # Joriy slug qatori ustuvor: eski qatordagi eskirgan
                # is_equipped belgisi yangi ramkani qayta yoqib yubormasin.
                equipped = (
                    current.is_equipped
                    if legacy
                    else bool(row.get("is_equipped"))
                )
            entries[slug] = InventoryEntry(
                item_slug=slug,
                quantity=quantity,
                is_equipped=equipped,
            )
        return sorted(entries.values(), key=lambda entry: entry.item_slug)

    def entry(self, user_id: int, slug: str) -> InventoryEntry:
        """Bitta buyum bo'yicha inventar yozuvi (yo'q bo'lsa 0 dona)."""
        wanted = canonical_slug(slug)
        for entry in self.inventory(user_id):
            if entry.item_slug == wanted:
                return entry
        return InventoryEntry(item_slug=wanted, quantity=0)

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
        item = CATALOG_BY_SLUG.get(canonical_slug(slug))
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

        if item.slug == LOOTBOX_SLUG:
            bag: dict[str, int] = {}
            for _ in range(count):
                prize = CATALOG_BY_SLUG[random.choice(LOOTBOX_POOL)]
                bag[prize.slug] = bag.get(prize.slug, 0) + 1
            account = self.economy.spend_coins(uid, total)
            last_entry: InventoryEntry | None = None
            for prize_slug, extra in bag.items():
                prize_current = self.entry(uid, prize_slug)
                last_entry = InventoryEntry(
                    item_slug=prize_slug,
                    quantity=prize_current.quantity + extra,
                    is_equipped=prize_current.is_equipped,
                )
                self._save_entry(uid, last_entry)
            self._record_transaction(uid, item, count, total)
            prizes = tuple(CATALOG_BY_SLUG[slug] for slug in bag)
            assert last_entry is not None
            return PurchaseResult(
                item=item,
                quantity=count,
                total_price=total,
                account=account,
                entry=last_entry,
                loot=prizes,
            )

        current = self.entry(uid, item.slug)
        grant = count * SPIN_TICKET_PACK if item.slug == SPIN_TICKET_SLUG else count
        updated = InventoryEntry(
            item_slug=item.slug,
            quantity=current.quantity + grant,
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
        if segment.key == "mystery":
            generator = rng or random
            segment = WheelSegment(
                key=segment.key,
                label=segment.label,
                weight=segment.weight,
                item_slug=generator.choice(MYSTERY_SLUGS),
                emoji=segment.emoji,
            )
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
        item = CATALOG_BY_SLUG.get(canonical_slug(slug))
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
        equipped = self.equipped(uid)
        self._sync_equipped_columns(uid, equipped)
        return {
            "ok": True,
            "item": item.as_dict(),
            "is_equipped": bool(equip),
            "equipped": equipped,
        }

    def _sync_equipped_columns(
        self, user_id: int, equipped: dict[str, str]
    ) -> None:
        """Ramka/unvon nusxasini ``users`` jadvaliga ham yozadi."""
        if not self.enabled:
            return
        try:
            safe_update(
                self.client,
                USERS_TABLE,
                {
                    "equipped_frame": equipped.get("frame", ""),
                    "equipped_title": equipped.get("title", ""),
                },
                {USERS_ID_COLUMN: int(user_id)},
            )
        except Exception:
            logger.exception(
                "Taqilgan kosmetikani saqlab bo'lmadi: %s", user_id
            )

    def transactions(self) -> list[dict[str, Any]]:
        """Xotiradagi xarid tarixi (testlar va diagnostika uchun)."""
        return list(self._transactions)

    def transactions_page(
        self,
        user_id: int,
        limit: int = 10,
        offset: int = 0,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Xaridlar sahifasi va yana natija borligini qaytaradi."""
        uid = int(user_id)
        cap = max(1, min(int(limit), 50))
        start = max(0, int(offset or 0))
        from_bound = _history_bound(from_date)
        to_bound = _history_bound(to_date, end=True)
        fetch = cap + 1
        rows: list[dict[str, Any]] = []
        if self.enabled:
            # Yangi va eski jadvalni birgalikda o'qiymiz: ba'zi o'rnatishlarda
            # tarix faqat `transactions`da qolgan bo'lishi mumkin.
            for table in (TRANSACTIONS_TABLE, LEGACY_TRANSACTIONS_TABLE):
                try:
                    query = self.client.table(table).select("*").eq("user_id", uid)
                    if from_bound:
                        query = query.gte("created_at", from_bound)
                    if to_bound:
                        query = query.lte("created_at", to_bound)
                    query = query.order("created_at", desc=True).limit(start + fetch)
                    rows.extend(query.execute().data or [])
                except Exception:
                    logger.exception(
                        "Xarid tarixini %s jadvalidan öqib bölmadi: %s", table, uid
                    )
            if rows:
                unique: dict[tuple[str, str, int], dict[str, Any]] = {}
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    if int(row.get("user_id") or 0) != uid:
                        continue
                    clean_row = _normalize_transaction(row)
                    key = (
                        str(clean_row.get("item_slug") or ""),
                        str(clean_row.get("created_at") or ""),
                        int(clean_row.get("total_price") or 0),
                    )
                    unique.setdefault(key, clean_row)
                clean = list(unique.values())
                clean.sort(
                    key=lambda row: str(row.get("created_at") or ""), reverse=True
                )
                return clean[start : start + cap], len(clean) > start + cap
        with self._lock:
            rows = [
                dict(row) for row in self._transactions
                if int(row.get("user_id") or 0) == uid
            ]
        if from_bound or to_bound:
            from_moment = _history_moment(from_bound)
            to_moment = _history_moment(to_bound)
            filtered = []
            for row in rows:
                moment = _history_moment(row.get("created_at"))
                if moment is None:
                    continue
                if from_moment is not None and moment < from_moment:
                    continue
                if to_moment is not None and moment > to_moment:
                    continue
                filtered.append(row)
            rows = filtered
        rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
        selected = rows[start : start + fetch]
        return selected[:cap], len(selected) > cap

    def transactions_for_user(self, user_id: int, limit: int = 10) -> list[dict[str, Any]]:
        """Foydalanuvchi xaridlari: baza yoqilgan bo'lsa jadvaldan, aks holda xotiradan."""
        rows, _ = self.transactions_page(user_id, limit=limit)
        return rows


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
