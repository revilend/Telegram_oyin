"""«Bunker» o'yini uchun tasodifiy, ammo balansli personaj generatori.

Generator ``data/cards.json`` katalogidan foydalanadi. Har bir personaj uchun
kasb, biologiya, sog'liq, mashg'ulot, yuk va fakt kartalari beriladi, ba'zi
o'yinchilarga esa qo'shimcha maxsus karta tushadi.

Balanslash ikki darajada ishlaydi:

* har bir karta navbatma-navbat ishlatiladi (takrorlanish eng kam bo'lgan
  kartalar orasidan tanlanadi), shu sababli bir xil karta qisqa vaqt ichida
  ikki marta tushmaydi;
* kasblar yo'nalish (tibbiyot, texnika, oziq-ovqat va h.k.), biologiyalar esa
  jinsi bo'yicha guruhlanadi va guruhlar bo'ylab teng taqsimlanadi.
"""

from __future__ import annotations

import json
import random
import threading
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Sequence

from models.game import CardType, PlayerCard

DEFAULT_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "cards.json"

# Har bir personaj oladigan majburiy kartalar va ularning katalog kalitlari.
CHARACTER_CATEGORIES: dict[CardType, str] = {
    CardType.PROFESSION: "professions",
    CardType.BIOLOGY: "biologies",
    CardType.HEALTH: "health",
    CardType.HOBBY: "hobbies",
    CardType.LUGGAGE: "luggage",
    CardType.FACT: "facts",
}
SPECIAL_CATEGORY = "special_actions"

# Guruh bo'yicha balanslash uchun ishlatiladigan maydonlar.
GROUP_KEYS: dict[str, str] = {
    "professions": "tag",
    "biologies": "gender",
}


def load_catalog(path: str | Path | None = None) -> dict[str, list[dict[str, Any]]]:
    """Katalog faylini o'qib, tekshirib qaytaradi."""
    data_path = Path(path) if path is not None else DEFAULT_DATA_PATH
    try:
        with data_path.open(encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Katalog fayli topilmadi: {data_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Katalog fayli noto'g'ri JSON: {data_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError("Katalog ildizi obyekt bo'lishi kerak")

    catalog: dict[str, list[dict[str, Any]]] = {}
    required = [*CHARACTER_CATEGORIES.values(), SPECIAL_CATEGORY, "catastrophes"]
    for category in required:
        items = raw.get(category)
        if not isinstance(items, list) or not items:
            raise ValueError(f"Katalogda '{category}' ro'yxati bo'sh yoki yo'q")
        seen_ids: set[str] = set()
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                raise ValueError(f"'{category}'[{index}] obyekt bo'lishi kerak")
            title_field = "name" if category == "catastrophes" else "title"
            for field in ("id", title_field, "description"):
                value = item.get(field)
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"'{category}'[{index}] uchun '{field}' to'ldirilmagan")
            if category == "catastrophes":
                for field in ("bunker_supplies", "survival_requirements"):
                    value = item.get(field)
                    if not isinstance(value, list) or not value:
                        raise ValueError(
                            f"'catastrophes'[{index}] uchun '{field}' ro'yxati bo'sh"
                        )
            if item["id"] in seen_ids:
                raise ValueError(f"'{category}' ichida takrorlangan id: {item['id']}")
            seen_ids.add(item["id"])
            group_key = GROUP_KEYS.get(category)
            if group_key is not None and not isinstance(item.get(group_key), str):
                raise ValueError(
                    f"'{category}'[{index}] uchun '{group_key}' maydoni kerak"
                )
        if category == "biologies":
            for index, item in enumerate(items):
                age = item.get("age")
                if not isinstance(age, int) or not 18 <= age <= 75:
                    raise ValueError(
                        f"'biologies'[{index}] yoshi 18–75 oralig'ida bo'lishi kerak"
                    )
                if not isinstance(item.get("can_have_children"), bool):
                    raise ValueError(
                        f"'biologies'[{index}] uchun 'can_have_children' mantiqiy qiymat bo'lishi kerak"
                    )
        catalog[category] = items

    return catalog


class _BalancedDeck:
    """Har bir element eng kam ishlatilganlar orasidan tanlanadigan to'plam."""

    def __init__(
        self,
        items: Sequence[dict[str, Any]],
        rng: random.Random,
        group_key: str | None = None,
    ) -> None:
        if not items:
            raise ValueError("To'plam bo'sh bo'lishi mumkin emas")
        self._items = list(items)
        self._rng = rng
        self._group_key = group_key
        self._usage: dict[str, int] = defaultdict(int)
        self._group_usage: dict[str, int] = defaultdict(int)

    def draw(self) -> dict[str, Any]:
        pool = self._items
        if self._group_key is not None:
            groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for item in pool:
                groups[item[self._group_key]].append(item)
            min_group_usage = min(self._group_usage[group] for group in groups)
            candidates = [
                group
                for group in groups
                if self._group_usage[group] == min_group_usage
            ]
            chosen_group = self._rng.choice(candidates)
            pool = groups[chosen_group]

        min_usage = min(self._usage[item["id"]] for item in pool)
        candidates = [item for item in pool if self._usage[item["id"]] == min_usage]
        chosen = self._rng.choice(candidates)

        self._usage[chosen["id"]] += 1
        if self._group_key is not None:
            self._group_usage[chosen[self._group_key]] += 1
        return chosen


class CharacterGenerator:
    """Personaj kartalarini tasodifiy, ammo balansli tarzda yaratadi.

    Bitta xona uchun bitta generator ishlatilsa, kartalar o'yinchilar orasida
    teng taqsimlanadi. Bir necha xona uchun alohida generator yaratish tavsiya
    etiladi.
    """

    def __init__(
        self,
        data_path: str | Path | None = None,
        *,
        seed: int | None = None,
        special_card_probability: float = 0.5,
    ) -> None:
        if not 0.0 <= special_card_probability <= 1.0:
            raise ValueError("special_card_probability 0 va 1 oralig'ida bo'lishi kerak")

        self.catalog = load_catalog(data_path)
        self._rng = random.Random(seed)
        self._special_card_probability = special_card_probability
        self._lock = threading.Lock()

        factories: dict[CardType, Callable[[], _BalancedDeck]] = {
            card_type: (
                lambda key=category: _BalancedDeck(
                    self.catalog[key], self._rng, GROUP_KEYS.get(key)
                )
            )
            for card_type, category in CHARACTER_CATEGORIES.items()
        }
        self._decks: dict[CardType, _BalancedDeck] = {
            card_type: factory() for card_type, factory in factories.items()
        }
        self._special_deck = _BalancedDeck(
            self.catalog[SPECIAL_CATEGORY], self._rng
        )
        self._generated = 0

    @property
    def generated_count(self) -> int:
        """Shu generator yaratgan personajlar soni."""
        return self._generated

    def generate_character(self) -> dict[str, PlayerCard]:
        """Bitta personaj uchun kartalar to'plamini qaytaradi.

        Natija kalitlari :class:`CardType` qiymatlari bo'ladi, masalan
        ``cards["profession"]``. Maxsus karta ehtimoli generator sozlamasiga
        bog'liq.
        """
        with self._lock:
            cards: dict[str, PlayerCard] = {}
            for card_type, deck in self._decks.items():
                item = deck.draw()
                cards[card_type.value] = self._build_card(card_type, item)

            if self._rng.random() < self._special_card_probability:
                item = self._special_deck.draw()
                cards[CardType.SPECIAL.value] = self._build_card(
                    CardType.SPECIAL, item
                )

            self._generated += 1
            return cards

    def generate_card(self, card_type: CardType | str) -> PlayerCard:
        """Bitta turdagi yangi kartani yaratadi (reroll uchun)."""
        normalized = card_type if isinstance(card_type, CardType) else CardType(str(card_type).lower())
        if normalized is CardType.CATASTROPHE:
            raise ValueError("Falokat kartasini almashtirish mumkin emas")
        with self._lock:
            if normalized is CardType.SPECIAL:
                item = self._special_deck.draw()
            else:
                category = CHARACTER_CATEGORIES[normalized]
                item = self._decks[normalized].draw()
            return self._build_card(normalized, item)

    @staticmethod
    def _build_card(card_type: CardType, item: dict[str, Any]) -> PlayerCard:
        return PlayerCard(
            type=card_type,
            title=item["title"],
            description=item["description"],
            is_revealed=False,
        )


_default_generator: CharacterGenerator | None = None
_default_generator_lock = threading.Lock()


def get_default_generator() -> CharacterGenerator:
    """Modul darajasidagi umumiy generatorni qaytaradi (kerak bo'lsa yaratadi)."""
    global _default_generator
    if _default_generator is None:
        with _default_generator_lock:
            if _default_generator is None:
                _default_generator = CharacterGenerator()
    return _default_generator


def generate_character(
    generator: CharacterGenerator | None = None,
) -> dict[str, PlayerCard]:
    """Tasodifiy, balansli personaj kartalarini yaratadi.

    Args:
        generator: Ixtiyoriy generator. Berilmasa, modulning umumiy generatori
            ishlatiladi.

    Returns:
        ``CardType`` qiymatlari bo'yicha kalitlangan kartalar lug'ati.
    """
    return (generator or get_default_generator()).generate_character()
