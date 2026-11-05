"""Xona ichidagi jonli chat (RAM-only, WebSocket orqali).

Xabarlar hech qayerda saqlanmaydi: faqat WebSocket ulanishlari orqali
xotirada tarqatiladi. Qoidalar:

* faqat xona a'zolari yozadi (begonalar rad etiladi);
* o'yindan chiqqan/o'ldirilgan o'yinchi faqat bitta so'nggi so'z yozadi,
  keyin uning maydoni qulflanadi;
* Mafiyada tun bosqichida faqat tirik mafiyalar yozadi va ularning
  xabarlari faqat tirik mafiyalarga ko'rinadi;
* tizim xabarlari (qo'shildi, chiqdi, tun boshlandi) hammaga ko'rinadi.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 300
HISTORY_LIMIT = 200
GHOST_LIMIT = 1

KIND_USER = "user"
KIND_SYSTEM = "system"
KIND_MAFIA = "mafia"


class ChatError(Exception):
    """Chat qoidasi buzilganda ko'tariladi (foydalanuvchiga ko'rsatiladi)."""


@dataclass(frozen=True)
class ChatAccess:
    """Foydalanuvchining xonadagi holati (chat qoidalari uchun)."""

    game_type: str
    name: str
    is_member: bool
    is_alive: bool = True
    is_mafia: bool = False
    is_night: bool = False
    is_host: bool = False


@dataclass
class ChatEntry:
    """Bitta chat xabari."""

    id: int
    user_id: int
    name: str
    text: str
    kind: str
    ts: float
    ghost: bool = False

    def payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class _Client:
    websocket: Any
    user_id: int


class ChatHub:
    """Xonalar bo'yicha chat xabarlari va ulanishlarini boshqaradi."""

    def __init__(
        self,
        resolver: Callable[[str, int], ChatAccess | None],
        *,
        history_limit: int = HISTORY_LIMIT,
    ) -> None:
        self._resolver = resolver
        self._limit = max(20, int(history_limit))
        self._history: dict[str, deque[ChatEntry]] = {}
        self._ghosts: dict[str, set[int]] = {}
        self._clients: dict[str, list[_Client]] = {}
        self._counter = 0
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Ulanish
    # ------------------------------------------------------------------
    async def connect(self, code: str, websocket: Any, user_id: int) -> ChatAccess | None:
        """Ulanishni ro'yxatga oladi va tarixni yuboradi."""
        access = self._resolver(code, int(user_id))
        if access is None:
            return None
        async with self._lock:
            self._clients.setdefault(code, []).append(
                _Client(websocket=websocket, user_id=int(user_id))
            )
            history = [
                entry.payload()
                for entry in self._history.get(code, ())
                if self._visible(entry, access)
            ]
        await self._safe_send(
            websocket,
            {
                "type": "chat-history",
                "messages": history,
                "locked": self.locked(code, int(user_id), access),
            },
        )
        return access

    async def disconnect(self, code: str, websocket: Any) -> None:
        async with self._lock:
            clients = self._clients.get(code) or []
            self._clients[code] = [
                client for client in clients if client.websocket is not websocket
            ]
            if not self._clients[code]:
                self._clients.pop(code, None)

    # ------------------------------------------------------------------
    # Xabarlar
    # ------------------------------------------------------------------
    def locked(self, code: str, user_id: int, access: ChatAccess) -> bool:
        """Foydalanuvchi uchun yozish maydoni qulflanganmi."""
        if not access.is_member:
            return True
        if access.is_alive:
            return False
        return int(user_id) in self._ghosts.get(code, set())

    async def post(self, code: str, user_id: int, text: str) -> ChatEntry:
        """Xabarni tekshirib, ko'rinadigan ulanishlarga tarqatadi."""
        clean = "".join(
            char for char in str(text or "").replace("\r", " ").replace("\n", " ")
            if char.isprintable() or char == " "
        ).strip()
        if not clean:
            raise ChatError("Xabar bo'sh bo'lishi mumkin emas")
        if len(clean) > MAX_MESSAGE_LENGTH:
            clean = clean[:MAX_MESSAGE_LENGTH].rstrip() + "…"

        access = self._resolver(code, int(user_id))
        if access is None:
            raise ChatError("Xona topilmadi")
        if not access.is_member:
            raise ChatError("Siz bu xonada qatnashmayapsiz")

        async with self._lock:
            ghost = False
            if not access.is_alive:
                spoken = self._ghosts.setdefault(code, set())
                if int(user_id) in spoken:
                    raise ChatError("Siz o'yindan chiqqansiz (arvohsiz)")
                spoken.add(int(user_id))
                ghost = True
            kind = KIND_USER
            if access.game_type == "mafia" and access.is_night and not ghost:
                if not access.is_mafia:
                    raise ChatError("Tunda faqat mafiyalar yozadi")
                kind = KIND_MAFIA

            self._counter += 1
            entry = ChatEntry(
                id=self._counter,
                user_id=int(user_id),
                name=access.name,
                text=clean,
                kind=kind,
                ts=time.time(),
                ghost=ghost,
            )
            self._history.setdefault(code, deque(maxlen=self._limit)).append(entry)

        await self._broadcast(code, entry)
        return entry

    async def system(self, code: str, text: str) -> None:
        """Tizim xabarini hammaga tarqatadi (tarixga ham yoziladi)."""
        async with self._lock:
            self._counter += 1
            entry = ChatEntry(
                id=self._counter,
                user_id=0,
                name="",
                text=str(text or "").strip(),
                kind=KIND_SYSTEM,
                ts=time.time(),
            )
            if not entry.text:
                return
            self._history.setdefault(code, deque(maxlen=self._limit)).append(entry)
        await self._broadcast(code, entry)

    async def history(self, code: str, user_id: int) -> list[dict[str, Any]]:
        """Foydalanuvchiga ko'rinadigan xabarlar tarixi."""
        access = self._resolver(code, int(user_id))
        if access is None:
            return []
        async with self._lock:
            return [
                entry.payload()
                for entry in self._history.get(code, ())
                if self._visible(entry, access)
            ]

    def reset(self, code: str | None = None) -> None:
        codes = [code] if code else list(self._history)
        for key in codes:
            self._history.pop(key, None)
            self._ghosts.pop(key, None)
            self._clients.pop(key, None)

    # ------------------------------------------------------------------
    # Yordamchilar
    # ------------------------------------------------------------------
    @staticmethod
    def _visible(entry: ChatEntry, access: ChatAccess) -> bool:
        # Begona (a'zo bo'lmagan) o'yinchi xonadagi yozishmalarni ko'rmaydi.
        if not access.is_member:
            return False
        if entry.kind == KIND_MAFIA:
            return bool(access.is_mafia and access.is_alive)
        return True

    async def _broadcast(self, code: str, entry: ChatEntry) -> None:
        async with self._lock:
            clients = list(self._clients.get(code) or [])
        payload = {"type": "chat", "message": entry.payload()}
        stale: list[_Client] = []
        for client in clients:
            access = self._resolver(code, client.user_id)
            if access is None or not self._visible(entry, access):
                continue
            try:
                await client.websocket.send_json(payload)
            except Exception:
                stale.append(client)
        if stale:
            async with self._lock:
                current = self._clients.get(code) or []
                self._clients[code] = [
                    client for client in current if client not in stale
                ]

    async def _safe_send(self, websocket: Any, payload: dict[str, Any]) -> None:
        try:
            await websocket.send_json(payload)
        except Exception:
            logger.debug("Chat tarixini yuborib bo'lmadi", exc_info=True)
