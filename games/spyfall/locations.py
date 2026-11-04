"""«Josus» (Spyfall) lokatsiyalari va ulardagi rollar katalogi.

Har bir lokatsiya uchun o'zbekcha nom, emoji va 6–8 ta maxsus rol
saqlanadi. O'yin boshida bitta lokatsiya tasodifiy tanlanadi: tinch
ishtirokchilar lokatsiya nomi bilan birga shu joyga xos rolni ko'radi,
josus esa faqat «siz josusiz» ogohlantirishini oladi.
"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class Location:
    """Bitta joylashuv va undagi rollar."""

    key: str
    name: str
    emoji: str
    roles: tuple[str, ...]


LOCATIONS: tuple[Location, ...] = (
    Location(
        key="samolyot",
        name="Samolyot",
        emoji="✈️",
        roles=(
            "Uchuvchi",
            "Styuardessa",
            "Yo'lovchi",
            "Mexanik",
            "Kontrabandachi",
            "Biznes-klass mijozi",
            "Bagaj nazoratchisi",
        ),
    ),
    Location(
        key="shifoxona",
        name="Shifoxona",
        emoji="🏥",
        roles=(
            "Bosh jarroh",
            "Hamshira",
            "Bemor",
            "Stomatolog",
            "Qorovul",
            "Tez yordam haydovchisi",
            "Anesteziolog",
        ),
    ),
    Location(
        key="harbiy_baza",
        name="Harbiy baza",
        emoji="🎖️",
        roles=(
            "General",
            "Snayper",
            "Oshpaz",
            "Radist",
            "Navbatchi askar",
            "Harbiy shifokor",
            "Sapyor",
        ),
    ),
    Location(
        key="bank",
        name="Bank",
        emoji="🏦",
        roles=(
            "Bank direktori",
            "Kassir",
            "Inkassator",
            "Mijoz",
            "Qo'riqchi",
            "Kredit bo'limi xodimi",
            "Kripto-treyder",
        ),
    ),
    Location(
        key="toyxona",
        name="To'yxona",
        emoji="💍",
        roles=(
            "Kuyov",
            "Kelin",
            "Oshpaz",
            "Hofiz",
            "Fotograf",
            "Kuyovjo'ra",
            "Sovchi",
            "To'y boshlovchisi",
        ),
    ),
    Location(
        key="choyxona",
        name="Choyxona",
        emoji="🫖",
        roles=(
            "Choychi",
            "Oshpaz",
            "Mijoz",
            "Sozanda",
            "Hisobchi",
            "Choynak ustasi",
        ),
    ),
    Location(
        key="kosmik_stantsiya",
        name="Kosmik stantsiya",
        emoji="🚀",
        roles=(
            "Komandir",
            "Kosmonavt",
            "Muhandis",
            "Shifokor",
            "Radist",
            "Yer aloqasi operatori",
            "Katta olim",
        ),
    ),
    Location(
        key="kema",
        name="Kema (Titanik)",
        emoji="🚢",
        roles=(
            "Kapitan",
            "Shturman",
            "Matros",
            "Ofitsiant",
            "Passajir",
            "Kok",
            "Radiooperator",
        ),
    ),
    Location(
        key="politsiya",
        name="Politsiya bo'limi",
        emoji="🚓",
        roles=(
            "Komissar",
            "Detektiv",
            "Navbatchi",
            "Patrul",
            "Advokat",
            "Guvoh",
            "Sud-tibbiyot eksperti",
        ),
    ),
    Location(
        key="universitet",
        name="Universitet",
        emoji="🎓",
        roles=(
            "Professor",
            "Talaba",
            "Dekan",
            "Kutubxonachi",
            "Laborant",
            "Rektor",
            "Qabul komissiyasi xodimi",
        ),
    ),
    Location(
        key="qamoqxona",
        name="Qamoqxona",
        emoji="⛓️",
        roles=(
            "Nazoratchi",
            "Mahbus",
            "Advokat",
            "Qamoqxona boshlig'i",
            "Oshpaz",
            "Psixolog",
            "Yangi kelgan mahbus",
        ),
    ),
    Location(
        key="kino_studiyasi",
        name="Kino studiyasi",
        emoji="🎬",
        roles=(
            "Rejissyor",
            "Aktyor",
            "Operator",
            "Grimyor",
            "Ssenariy yozuvchi",
            "Chiroqchi",
            "Prodyuser",
        ),
    ),
    Location(
        key="suv_osti_kemasi",
        name="Suv osti kemasi",
        emoji="🛟",
        roles=(
            "Kapitan",
            "Navigator",
            "Torpedachi",
            "Mexanik",
            "Oshpaz",
            "Sonar operatori",
            "Kemadagi shifokor",
        ),
    ),
    Location(
        key="elchixona",
        name="Elchixona",
        emoji="🛂",
        roles=(
            "Elchi",
            "Konsul",
            "Tarjimon",
            "Qo'riqchi",
            "Viza xodimi",
            "Diplomat",
            "Jurnalist",
        ),
    ),
    Location(
        key="bozor",
        name="Bozor (Chorsu)",
        emoji="🍉",
        roles=(
            "Sotuvchi",
            "Xaridor",
            "Hammol",
            "Tarozibon",
            "Qo'riqchi",
            "Pul maydalovchi",
            "Raqib sotuvchi",
        ),
    ),
    Location(
        key="aeroport",
        name="Aeroport",
        emoji="🛫",
        roles=(
            "Dispetcher",
            "Uchuvchi",
            "Bojxona xodimi",
            "Yo'lovchi",
            "Bagaj ortuvchi",
            "Styuardessa",
            "Chipta kassiri",
        ),
    ),
    Location(
        key="maktab",
        name="Maktab",
        emoji="🏫",
        roles=(
            "O'qituvchi",
            "O'quvchi",
            "Direktor",
            "Farrosh",
            "Oshpaz",
            "Psixolog",
            "Ota-ona",
        ),
    ),
    Location(
        key="restoran",
        name="Restoran",
        emoji="🍽️",
        roles=(
            "Oshpaz",
            "Ofitsiant",
            "Bosh direktor",
            "Mijoz",
            "Barmen",
            "Somelye",
            "Idish yuvuvchi",
        ),
    ),
    Location(
        key="kinoteatr",
        name="Kinoteatr",
        emoji="🍿",
        roles=(
            "Proyeksiyachi",
            "Kassir",
            "Tomoshabin",
            "Popkorn sotuvchisi",
            "Tozalovchi",
            "Menejer",
            "Tanqidchi",
        ),
    ),
    Location(
        key="plyaj",
        name="Plyaj",
        emoji="🏖️",
        roles=(
            "Qutqaruvchi",
            "Sotuvchi",
            "Sayyoh",
            "Suv sporti instruktori",
            "Qo'riqchi",
            "Muzqaymoqchi",
        ),
    ),
    Location(
        key="muzey",
        name="Muzey",
        emoji="🏛️",
        roles=(
            "Kurator",
            "Ekskursovod",
            "Qo'riqchi",
            "Restavrator",
            "Tashrif buyuruvchi",
            "Arxeolog",
            "Rassom",
        ),
    ),
    Location(
        key="mehmonxona",
        name="Mehmonxona",
        emoji="🏨",
        roles=(
            "Resepshn xodimi",
            "Qo'ng'iroqchi",
            "Mehmon",
            "Tozalovchi",
            "Boshqaruvchi",
            "Oshpaz",
            "Xavfsizlik xodimi",
        ),
    ),
    Location(
        key="poyezd",
        name="Poyezd",
        emoji="🚆",
        roles=(
            "Mashinist",
            "Konduktor",
            "Yo'lovchi",
            "Restoran vagon ofitsianti",
            "Chipta tekshiruvchi",
            "Stansiya navbatchisi",
        ),
    ),
    Location(
        key="supermarket",
        name="Supermarket",
        emoji="🛒",
        roles=(
            "Kassir",
            "Ombor mudiri",
            "Xaridor",
            "Qo'riqchi",
            "Savdo menejeri",
            "Tozalovchi",
            "Yetkazib beruvchi",
        ),
    ),
    Location(
        key="stadion",
        name="Stadion",
        emoji="🏟️",
        roles=(
            "Futbolchi",
            "Hakam",
            "Murabbiy",
            "Tomoshabin",
            "Kommentator",
            "Shifokor",
            "Qo'riqchi",
        ),
    ),
    Location(
        key="kutubxona",
        name="Kutubxona",
        emoji="📚",
        roles=(
            "Kutubxonachi",
            "Kitobxon",
            "Arxivchi",
            "Tozalovchi",
            "Qo'riqchi",
            "Tadqiqotchi",
        ),
    ),
    Location(
        key="sirk",
        name="Sirk",
        emoji="🎪",
        roles=(
            "Ekvilibrist",
            "Kloun",
            "Dressirovkachi",
            "Tomoshabin",
            "Direktor",
            "Chipta sotuvchisi",
            "Akrobat",
        ),
    ),
    Location(
        key="hayvonot_bogi",
        name="Hayvonot bog'i",
        emoji="🦁",
        roles=(
            "Qo'riqchi",
            "Veterinar",
            "Tashrif buyuruvchi",
            "Gid",
            "Ozuqa tayyorlovchi",
            "Dressirovkachi",
        ),
    ),
    Location(
        key="teatr",
        name="Teatr",
        emoji="🎭",
        roles=(
            "Aktyor",
            "Rejissyor",
            "Sufler",
            "Grimyor",
            "Tomoshabin",
            "Chipta sotuvchisi",
            "Sahna ishchisi",
        ),
    ),
)

MIN_LOCATIONS = 25
MIN_ROLES = 6
MAX_ROLES = 8

LOCATIONS_BY_KEY: dict[str, Location] = {item.key: item for item in LOCATIONS}

if len(LOCATIONS) < MIN_LOCATIONS:
    raise ValueError(
        f"Josus uchun kamida {MIN_LOCATIONS} ta lokatsiya kerak, "
        f"{len(LOCATIONS)} ta berildi"
    )
if len(LOCATIONS_BY_KEY) != len(LOCATIONS):
    raise ValueError("Lokatsiya kalitlari takrorlanmasligi kerak")
for _location in LOCATIONS:
    if not MIN_ROLES <= len(_location.roles) <= MAX_ROLES:
        raise ValueError(
            f"'{_location.key}' lokatsiyasida {MIN_ROLES}–{MAX_ROLES} ta rol "
            f"bo'lishi kerak, {len(_location.roles)} ta berildi"
        )
    if len(set(_location.roles)) != len(_location.roles):
        raise ValueError(f"'{_location.key}' lokatsiyasida rollar takrorlangan")

del _location


def get_location(key: str) -> Location:
    """Kalit bo'yicha lokatsiyani qaytaradi.

    Raises:
        KeyError: bunday lokatsiya bo'lmasa.
    """
    normalized = str(key or "").strip().lower()
    if normalized not in LOCATIONS_BY_KEY:
        for item in LOCATIONS:
            if item.name.strip().lower() == normalized:
                return item
        raise KeyError(f"Noma'lum lokatsiya: {key!r}")
    return LOCATIONS_BY_KEY[normalized]


def random_location(rng: random.Random | None = None) -> Location:
    """Tasodifiy lokatsiya tanlaydi."""
    return (rng or random).choice(LOCATIONS)


def location_choices() -> list[dict[str, str]]:
    """Mini App uchun lokatsiyalar ro'yxati (rollarsiz — sir saqlanadi)."""
    return [
        {"key": item.key, "name": item.name, "emoji": item.emoji}
        for item in LOCATIONS
    ]
