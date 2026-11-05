"""«Alias / Krokodil» o'yin dvigateli.

Bitta guruh uchun xona ochiladi, o'yinchilar qo'shiladi va har raundda bitta
«Tushuntiruvchi» tanlanadi.  Tushuntiruvchiga so'z va uning uchta taqiqlangan
so'zi shaxsiy xabar orqali yuboriladi; qolganlar so'zni 60 soniya ichida
topishga harakat qiladi.

Modul aiogram'ga bog'lanmagan: butun o'yin mantig'i oddiy obyektlarda
hisoblanadi, shuning uchun testlar botni ishga tushirmasdan o'tadi.
"""

from __future__ import annotations

import logging
import random
import re
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable

logger = logging.getLogger(__name__)

MIN_PLAYERS = 2
MAX_PLAYERS = 20
ROUND_SECONDS = 60
GUESS_REWARD = 10
EXPLAINER_REWARD = 5
WINNER_REWARD = 25

# Har bir ishtirokchi necha marta so'z tushuntiradi: o'yin cheksiz aylanmaydi.
ROUNDS_PER_PLAYER = 2

# Ketma-ket shuncha raundda hech kim so'zni topmasa, o'yin avtomatik to'xtaydi.
INACTIVE_ROUNDS_LIMIT = 2

CODE_PREFIX = "ALS"
CODE_DIGITS = 3

# Tashlab ketilgan xonalar uchun muddatlar.
LOBBY_TTL_SECONDS = 15 * 60
ROUND_TTL_SECONDS = 30 * 60

ALIAS_WORDS_TABLE = "alias_words"


class AliasError(Exception):
    """Alias o'yini qoidalari bilan bog'liq xatolik."""


class AliasStatus(str, Enum):
    """Xona holatlari."""

    LOBBY = "LOBBY"
    PLAYING = "PLAYING"
    FINISHED = "FINISHED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class AliasWord:
    """Yashirin so'z va uning taqiqlangan so'zlari."""

    word: str
    forbidden: tuple[str, ...] = ()
    category: str = "umumiy"

    def forbidden_text(self) -> str:
        return ", ".join(self.forbidden)


@dataclass
class AliasPlayer:
    """Xonadagi o'yinchi."""

    user_id: int
    name: str
    username: str = ""
    score: int = 0

    def label(self) -> str:
        """Guruhda ko'rsatiladigan nom (username bo'lsa @ bilan)."""
        handle = (self.username or "").strip().lstrip("@")
        if handle:
            return f"@{handle}"
        return self.name or f"ID {self.user_id}"


@dataclass
class AliasRound:
    """Bitta raund: tushuntiruvchi, so'z va taymer."""

    number: int
    explainer_id: int
    word: AliasWord
    started_at: float
    duration: int = ROUND_SECONDS
    finished: bool = False
    winner_id: int | None = None
    timed_out: bool = False

    @property
    def deadline(self) -> float:
        return self.started_at + self.duration

    def seconds_left(self, now: float | None = None) -> int:
        moment = time.time() if now is None else now
        return max(0, int(round(self.deadline - moment)))

    def is_over(self, now: float | None = None) -> bool:
        moment = time.time() if now is None else now
        return self.finished or moment >= self.deadline


@dataclass
class AliasGuessResult:
    """Bitta taxmin natijasi."""

    correct: bool
    word: str
    winner_id: int | None = None
    explainer_id: int | None = None
    already_finished: bool = False


def normalize_word(text: str) -> str:
    """So'zni solishtirish uchun soddalashtiradi.

    Yangi alifbo harflari (ö, ş, ç, ğ) va apostrof turlari bir xil shaklga
    keltiriladi, shuning uchun «O'zbekiston», «Özbekiston» va «ozbekiston»
    bir xil hisoblanadi.
    """
    value = (text or "").strip().lower()
    value = (
        value.replace("ö", "o")
        .replace("ş", "sh")
        .replace("ç", "ch")
        .replace("ğ", "g")
    )
    value = re.sub(r"['‘’ʻ`´]", "", value)
    value = re.sub(r"[^0-9a-zа-яё ]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


# So'zlar yangi o'zbek alifbosida yozilgan.  Supabase'dagi ``alias_words``
# jadvali bo'sh bo'lsa shu ro'yxat ishlatiladi.
DEFAULT_WORDS: tuple[AliasWord, ...] = (
    AliasWord("Kitob", ("varaq", "o'qish", "muqova"), "buyum"),
    AliasWord("Şahar", ("ko'ça", "uy", "aholi"), "joy"),
    AliasWord("Çoy", ("piyola", "qaynoq", "damlama"), "ichimlik"),
    AliasWord("Ğalaba", ("musobaqa", "sovrin", "birinchi"), "tushuncha"),
    AliasWord("Quyosh", ("osmon", "issiq", "yorug'lik"), "tabiat"),
    AliasWord("Telefon", ("qo'ng'iroq", "ekran", "batareya"), "texnika"),
    AliasWord("Maktab", ("o'qituvchi", "sinf", "dars"), "joy"),
    AliasWord("Do'st", ("yaqin", "ishonch", "suhbat"), "tushuncha"),
    AliasWord("Yomğir", ("bulut", "suv", "soyabon"), "tabiat"),
    AliasWord("Öyin", ("qoida", "g'alaba", "jamoa"), "tushuncha"),
    AliasWord("Şifokor", ("kasalxona", "dori", "bemor"), "kasb"),
    AliasWord("Özbekiston", ("mamlakat", "Toshkent", "bayroq"), "joy"),
    AliasWord("Muzqaymoq", ("sovuq", "şirin", "muz"), "taom"),
    AliasWord("Sayohat", ("çamadon", "poyezd", "yo'l"), "tushuncha"),
    AliasWord("Kompyuter", ("klaviatura", "ekran", "dastur"), "texnika"),
    AliasWord("Bog'", ("daraxt", "meva", "barg"), "tabiat"),
    AliasWord("Non", ("o'choq", "un", "tandir"), "taom"),
    AliasWord("Kino", ("ekran", "aktyor", "süjet"), "san'at"),
    AliasWord("Sport", ("mashq", "g'alaba", "maydon"), "tushuncha"),
    AliasWord("Tong", ("quyosh", "uyqu", "xo'roz"), "vaqt"),
    AliasWord("Sovğa", ("tug'ilgan kun", "quti", "quvonch"), "tushuncha"),
    AliasWord("Sut", ("oq", "sigir", "ichimlik"), "ichimlik"),
    AliasWord("Çoyxona", ("stol", "çoy", "suhbat"), "joy"),
    AliasWord("Bayram", ("sovğa", "mehmon", "dasturxon"), "tushuncha"),
    AliasWord("Tog'", ("baland", "cho'qqi", "qor"), "tabiat"),
    AliasWord("Balıq", ("suv", "qanot", "taroq"), "hayvon"),
    AliasWord("Robot", ("mexanizm", "dastur", "metall"), "texnika"),
    AliasWord("Şam", ("olov", "mum", "qorong'i"), "buyum"),
    AliasWord("Köprik", ("daryo", "yo'l", "ustun"), "joy"),
    AliasWord("Poyezd", ("relis", "vokzal", "çipta"), "transport"),
)


class WordBook:
    """So'zlar ombori: Supabase jadvali yoki ichki ro'yxat."""

    def __init__(self, words: Iterable[AliasWord] | None = None) -> None:
        self._words: list[AliasWord] = list(words or DEFAULT_WORDS)
        self._loaded_from_db = False

    @property
    def words(self) -> list[AliasWord]:
        return list(self._words)

    def __len__(self) -> int:
        return len(self._words)

    def load_from_client(self, client: Any) -> int:
        """``alias_words`` jadvalidan so'zlarni o'qiydi (imkon bo'lsa)."""
        if client is None:
            return 0
        try:
            rows = (
                client.table(ALIAS_WORDS_TABLE)
                .select("word,forbidden,category,is_active")
                .execute()
                .data
                or []
            )
        except Exception:
            logger.exception("alias_words jadvalini o'qib bo'lmadi")
            return 0
        words: list[AliasWord] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if row.get("is_active") is False:
                continue
            word = str(row.get("word") or "").strip()
            if not word:
                continue
            raw_forbidden = row.get("forbidden") or []
            if isinstance(raw_forbidden, str):
                raw_forbidden = [
                    part.strip() for part in raw_forbidden.split(",") if part.strip()
                ]
            forbidden = tuple(
                str(item).strip() for item in raw_forbidden if str(item).strip()
            )[:3]
            words.append(
                AliasWord(
                    word,
                    forbidden,
                    str(row.get("category") or "umumiy"),
                )
            )
        if words:
            self._words = words
            self._loaded_from_db = True
        return len(words)

    def pick(self, rng: random.Random, used: set[str]) -> AliasWord:
        """Takrorlanmagan so'z tanlaydi; hammasi ishlatilgan bo'lsa tozalaydi."""
        if not self._words:
            raise AliasError("So'zlar ro'yxati bo'sh")
        pool = [item for item in self._words if normalize_word(item.word) not in used]
        if not pool:
            used.clear()
            pool = list(self._words)
        return rng.choice(pool)


@dataclass
class AliasRoom:
    """Bitta guruhdagi Alias o'yini."""

    code: str
    chat_id: int
    host_id: int
    players: dict[int, AliasPlayer] = field(default_factory=dict)
    status: AliasStatus = AliasStatus.LOBBY
    rounds_played: int = 0
    current_round: AliasRound | None = None
    used_words: set[str] = field(default_factory=set)
    last_explainer_id: int | None = None
    created_at: float = field(default_factory=time.time)
    lobby_message_id: int | None = None
    # Har bir o'yinchi necha marta tushuntirgani va ketma-ket o'tkazib
    # yuborilgan (hech kim topmagan) raundlar soni.
    explainer_counts: dict[int, int] = field(default_factory=dict)
    consecutive_misses: int = 0
    stop_reason: str = ""

    @property
    def total_rounds(self) -> int:
        """O'yin uchun rejalashtirilgan raundlar soni."""
        return max(1, len(self.players)) * ROUNDS_PER_PLAYER

    @property
    def rounds_left(self) -> int:
        """Qolgan raundlar soni."""
        return max(0, self.total_rounds - self.rounds_played)

    @property
    def is_complete(self) -> bool:
        """Barcha rejalashtirilgan raundlar o'ynaldimi?"""
        return self.rounds_played >= self.total_rounds

    # ------------------------------------------------------------------
    # O'yinchilar
    # ------------------------------------------------------------------
    def add_player(
        self, user_id: int, name: str, username: str = "", *, is_host: bool = False
    ) -> AliasPlayer:
        """O'yinchini xonaga qo'shadi (takroriy qo'shilishga ruxsat)."""
        uid = int(user_id)
        if self.status is not AliasStatus.LOBBY:
            raise AliasError("O'yin boshlangan, qo'shilish mumkin emas")
        existing = self.players.get(uid)
        if existing is not None:
            if name:
                existing.name = name
            if username:
                existing.username = username
            return existing
        if len(self.players) >= MAX_PLAYERS:
            raise AliasError(f"Xona to'lgan (maksimal {MAX_PLAYERS} kishi)")
        player = AliasPlayer(uid, name or f"ID {uid}", username or "")
        self.players[uid] = player
        if is_host:
            self.host_id = uid
        return player

    def player(self, user_id: int) -> AliasPlayer:
        player = self.players.get(int(user_id))
        if player is None:
            raise AliasError("Siz bu Alias xonasida emassiz")
        return player

    # ------------------------------------------------------------------
    # Raundlar
    # ------------------------------------------------------------------
    def choose_explainer(self, rng: random.Random) -> int:
        """Eng kam tushuntirgan o'yinchini tanlaydi.

        Har bir ishtirokchi teng (2 martadan) tushuntirishi uchun avval
        eng kam tushuntirganlar orasidan tanlanadi; iloji bo'lsa oldingi
        tushuntiruvchi ketma-ket takrorlanmaydi.
        """
        counts = {uid: self.explainer_counts.get(uid, 0) for uid in self.players}
        minimum = min(counts.values())
        candidates = [uid for uid, count in counts.items() if count == minimum]
        if len(candidates) > 1 and self.last_explainer_id in candidates:
            candidates = [uid for uid in candidates if uid != self.last_explainer_id]
        explainer = rng.choice(candidates or list(self.players))
        self.last_explainer_id = explainer
        self.explainer_counts[explainer] = counts.get(explainer, 0) + 1
        return explainer

    def start_round(
        self,
        rng: random.Random,
        wordbook: WordBook,
        *,
        now: float | None = None,
        duration: int = ROUND_SECONDS,
    ) -> AliasRound:
        """Yangi raund boshlaydi va tushuntiruvchini belgilaydi."""
        if len(self.players) < MIN_PLAYERS:
            raise AliasError(
                f"O'yin uchun kamida {MIN_PLAYERS} kishi kerak "
                f"(hozir {len(self.players)})"
            )
        if self.status is AliasStatus.FINISHED:
            raise AliasError("Bu xonada o'yin tugagan")
        if self.is_complete:
            raise AliasError("Barcha raundlar o'ynaldi")
        moment = time.time() if now is None else now
        word = wordbook.pick(rng, self.used_words)
        self.used_words.add(normalize_word(word.word))
        explainer = self.choose_explainer(rng)
        self.rounds_played += 1
        self.status = AliasStatus.PLAYING
        self.current_round = AliasRound(
            number=self.rounds_played,
            explainer_id=explainer,
            word=word,
            started_at=moment,
            duration=max(10, int(duration)),
        )
        return self.current_round

    def submit_guess(
        self, user_id: int, text: str, *, now: float | None = None
    ) -> AliasGuessResult | None:
        """Taxminni tekshiradi; to'g'ri bo'lsa raundni yopadi."""
        current = self.current_round
        if current is None:
            return None
        uid = int(user_id)
        if uid not in self.players:
            return None
        if uid == current.explainer_id:
            return None
        moment = time.time() if now is None else now
        if current.finished:
            return AliasGuessResult(
                correct=False,
                word=current.word.word,
                winner_id=current.winner_id,
                explainer_id=current.explainer_id,
                already_finished=True,
            )
        if moment >= current.deadline:
            return AliasGuessResult(
                correct=False,
                word=current.word.word,
                explainer_id=current.explainer_id,
            )
        if normalize_word(text) != normalize_word(current.word.word):
            return None
        current.finished = True
        current.winner_id = uid
        self.consecutive_misses = 0
        self.player(uid).score += 1
        return AliasGuessResult(
            correct=True,
            word=current.word.word,
            winner_id=uid,
            explainer_id=current.explainer_id,
        )

    def expire_round(self, *, now: float | None = None) -> bool:
        """Taymer tugagan bo'lsa raundni yopadi."""
        current = self.current_round
        if current is None or current.finished:
            return False
        moment = time.time() if now is None else now
        if moment < current.deadline:
            return False
        current.finished = True
        current.timed_out = True
        self.consecutive_misses += 1
        return True

    def abort_round(self) -> None:
        """Raundni g'olibsiz yopadi (masalan so'z yuborilmasa)."""
        current = self.current_round
        if current is None or current.finished:
            return
        current.finished = True
        current.timed_out = True
        self.consecutive_misses += 1

    def should_stop_for_inactivity(self) -> bool:
        """Ketma-ket raundlarda faollik bo'lmaganini bildiradi."""
        return self.consecutive_misses >= INACTIVE_ROUNDS_LIMIT

    def finish(self, reason: str = "completed") -> None:
        """O'yinni yakunlaydi."""
        self.status = AliasStatus.FINISHED
        self.stop_reason = reason
        if self.current_round is not None:
            self.current_round.finished = True

    def winners(self) -> list[AliasPlayer]:
        """Eng ko'p ochko to'plagan g'olib(lar); ochko bo'lmasa — bo'sh."""
        if not self.players:
            return []
        best = max(player.score for player in self.players.values())
        if best <= 0:
            return []
        return [
            player for player in self.leaderboard() if player.score == best
        ]

    def leaderboard(self) -> list[AliasPlayer]:
        """Ochkolar bo'yicha saralangan o'yinchilar."""
        return sorted(
            self.players.values(),
            key=lambda player: (-player.score, player.name.lower()),
        )


class AliasManager:
    """Alias xonalari reyestri."""

    def __init__(
        self,
        *,
        seed: int | None = None,
        wordbook: WordBook | None = None,
    ) -> None:
        self._rooms: dict[str, AliasRoom] = {}
        self._times: dict[str, float] = {}
        self._lock = threading.RLock()
        self._rng = random.Random(seed)
        self._wordbook = wordbook or WordBook()
        self._words_loaded = False

    # ------------------------------------------------------------------
    # So'zlar
    # ------------------------------------------------------------------
    def ensure_words_loaded(self) -> None:
        """Supabase'dagi ``alias_words`` jadvalini bir marta o'qiydi."""
        if self._words_loaded:
            return
        self._words_loaded = True
        try:
            from core.db import get_store

            store = get_store()
            if store.enabled:
                count = self._wordbook.load_from_client(store.client)
                if count:
                    logger.info("alias_words: %s ta so'z yuklandi", count)
        except Exception:  # jadval bo'lmasa ichki ro'yxat ishlatiladi
            logger.exception("Alias so'zlarini yuklashda xatolik")

    @property
    def word_count(self) -> int:
        return len(self._wordbook)

    # ------------------------------------------------------------------
    # Xonalar
    # ------------------------------------------------------------------
    def _generate_code(self) -> str:
        for _ in range(1000):
            code = f"{CODE_PREFIX}{self._rng.randint(0, 10 ** CODE_DIGITS - 1):0{CODE_DIGITS}d}"
            if code not in self._rooms:
                return code
        raise AliasError("Bo'sh Alias xona kodi topilmadi, keyinroq urinib ko'ring")

    def create_room(
        self,
        chat_id: int,
        host_id: int,
        host_name: str,
        host_username: str = "",
    ) -> AliasRoom:
        """Yangi xona ochadi va xona egasini qo'shadi."""
        self.ensure_words_loaded()
        with self._lock:
            room = AliasRoom(
                code=self._generate_code(),
                chat_id=int(chat_id),
                host_id=int(host_id),
            )
            room.add_player(host_id, host_name, host_username, is_host=True)
            self._rooms[room.code] = room
            self._times[room.code] = time.time()
            return room

    def get_room(self, code: str) -> AliasRoom:
        """Kod bo'yicha xonani qaytaradi."""
        normalized = (code or "").strip().upper()
        with self._lock:
            room = self._rooms.get(normalized)
            if room is None:
                raise AliasError(f"'{normalized or code}' kodli Alias xonasi topilmadi")
            self._times[normalized] = time.time()
            return room

    def join(
        self,
        code: str,
        user_id: int,
        name: str,
        username: str = "",
    ) -> AliasRoom:
        """O'yinchini xonaga qo'shadi."""
        with self._lock:
            room = self.get_room(code)
            room.add_player(user_id, name, username)
            return room

    def start_game(
        self, code: str, user_id: int, *, now: float | None = None
    ) -> AliasRoom:
        """O'yinni boshlaydi (faqat xona egasi)."""
        with self._lock:
            room = self.get_room(code)
            if int(user_id) != room.host_id:
                raise AliasError("O'yinni faqat xona egasi boshlaydi")
            room.start_round(self._rng, self._wordbook, now=now)
            self._times[room.code] = time.time()
            return room

    def next_round(self, code: str, *, now: float | None = None) -> AliasRoom:
        """Keyingi raundni boshlaydi."""
        with self._lock:
            room = self.get_room(code)
            room.start_round(self._rng, self._wordbook, now=now)
            return room

    def submit_guess(
        self,
        chat_id: int,
        user_id: int,
        text: str,
        *,
        now: float | None = None,
    ) -> tuple[AliasRoom, AliasGuessResult] | None:
        """Guruhdagi xabarni joriy raund bilan solishtiradi."""
        with self._lock:
            room = self.active_room(chat_id)
            if room is None:
                return None
            result = room.submit_guess(user_id, text, now=now)
            if result is None:
                return None
            self._times[room.code] = time.time()
            return room, result

    def active_room(self, chat_id: int) -> AliasRoom | None:
        """Guruhdagi faol (davom etayotgan) Alias xonasi."""
        for room in self._rooms.values():
            if int(room.chat_id) == int(chat_id) and room.status is AliasStatus.PLAYING:
                return room
        return None

    def lobby_for_chat(self, chat_id: int) -> AliasRoom | None:
        """Guruhdagi kutayotgan Alias lobby'si."""
        for room in self._rooms.values():
            if int(room.chat_id) == int(chat_id) and room.status is AliasStatus.LOBBY:
                return room
        return None

    def room_by_chat(self, chat_id: int) -> AliasRoom | None:
        """Guruhdagi eng so'nggi faol xona (lobby yoki o'yin)."""
        for room in list(self._rooms.values()):
            if int(room.chat_id) == int(chat_id) and room.status in (
                AliasStatus.LOBBY,
                AliasStatus.PLAYING,
            ):
                return room
        return None

    def open_rooms(self, limit: int = 50) -> list[AliasRoom]:
        """Global qidiruv uchun ochiq Alias lobby'lari."""
        with self._lock:
            rooms = [
                room for room in self._rooms.values() if room.status is AliasStatus.LOBBY
            ]
            rooms.sort(key=lambda room: self._times.get(room.code, 0), reverse=True)
            return rooms[: max(1, int(limit))]

    def expire_stale(
        self,
        *,
        lobby_idle_seconds: float = LOBBY_TTL_SECONDS,
        game_idle_seconds: float = ROUND_TTL_SECONDS,
    ) -> dict[str, int]:
        """Tashlab ketilgan xonalarni yopadi va xotiradan olib tashlaydi."""
        now = time.time()
        expired = 0
        finished = 0
        with self._lock:
            for code, room in list(self._rooms.items()):
                idle = now - self._times.get(code, now)
                if room.status is AliasStatus.LOBBY and idle > lobby_idle_seconds:
                    room.status = AliasStatus.EXPIRED
                    self._rooms.pop(code, None)
                    self._times.pop(code, None)
                    expired += 1
                elif (
                    room.status is AliasStatus.PLAYING and idle > game_idle_seconds
                ):
                    room.finish()
                    self._rooms.pop(code, None)
                    self._times.pop(code, None)
                    finished += 1
        if expired or finished:
            logger.info(
                "Alias xonalari tozalandi: %s ta muddati o'tgan, %s ta yopilgan",
                expired,
                finished,
            )
        return {"expired": expired, "finished": finished}

    def drop(self, code: str) -> None:
        """Xonani reyestrdan olib tashlaydi (testlar uchun)."""
        with self._lock:
            self._rooms.pop((code or "").strip().upper(), None)
            self._times.pop((code or "").strip().upper(), None)

    def clear(self) -> None:
        """Barcha xonalarni tozalaydi."""
        with self._lock:
            self._rooms.clear()
            self._times.clear()

    @property
    def room_count(self) -> int:
        with self._lock:
            return len(self._rooms)


_default_manager: AliasManager | None = None
_default_lock = threading.Lock()


def get_default_manager() -> AliasManager:
    """Jarayon uchun yagona Alias menejerini qaytaradi."""
    global _default_manager
    with _default_lock:
        if _default_manager is None:
            _default_manager = AliasManager()
    return _default_manager
