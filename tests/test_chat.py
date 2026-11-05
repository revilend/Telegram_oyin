"""Jonli chat (engine/chat.py) qoidalari uchun testlar.

Xabarlar bazaga yozilmaydi: faqat RAMdagi navbat va WebSocket ulanishlari
tekshiriladi.
"""

from __future__ import annotations

import asyncio
import unittest
from typing import Any

from engine.chat import (
    ChatAccess,
    ChatError,
    ChatHub,
    KIND_MAFIA,
    KIND_SYSTEM,
    KIND_USER,
    MAX_MESSAGE_LENGTH,
)


class FakeSocket:
    """Ulanish o'rnini bosuvchi oddiy yozuvchi."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.closed = False

    async def send_json(self, payload: dict[str, Any]) -> None:
        self.sent.append(payload)

    def types(self) -> list[str]:
        return [item.get("type") for item in self.sent]

    def chat_texts(self) -> list[str]:
        return [item["message"]["text"] for item in self.sent if item.get("type") == "chat"]


class ChatHubTest(unittest.TestCase):
    def setUp(self) -> None:
        self.players: dict[int, ChatAccess] = {}
        self.hub = ChatHub(lambda code, user_id: self.players.get(int(user_id)))
        self.loop = asyncio.new_event_loop()

    def tearDown(self) -> None:
        self.loop.close()

    def run_async(self, coro):
        return self.loop.run_until_complete(coro)

    def add_player(
        self,
        user_id: int,
        name: str = "Ali",
        *,
        alive: bool = True,
        mafia: bool = False,
        night: bool = False,
        member: bool = True,
    ) -> None:
        self.players[user_id] = ChatAccess(
            game_type="mafia" if mafia or night else "bunker",
            name=name,
            is_member=member,
            is_alive=alive,
            is_mafia=mafia,
            is_night=night,
        )

    def connect(self, user_id: int) -> FakeSocket:
        socket = FakeSocket()
        self.run_async(self.hub.connect("BNK1", socket, user_id))
        return socket

    # ------------------------------------------------------------------
    # Asosiy oqim
    # ------------------------------------------------------------------
    def test_message_reaches_every_member(self) -> None:
        self.add_player(1, "Ali")
        self.add_player(2, "Vali")
        first = self.connect(1)
        second = self.connect(2)

        entry = self.run_async(self.hub.post("BNK1", 1, "Salom jamoa"))
        self.assertEqual(entry.kind, KIND_USER)
        self.assertEqual(first.chat_texts(), ["Salom jamoa"])
        self.assertEqual(second.chat_texts(), ["Salom jamoa"])
        self.assertEqual(first.sent[0]["type"], "chat-history")

    def test_history_is_sent_to_newcomer(self) -> None:
        self.add_player(1, "Ali")
        self.add_player(2, "Vali")
        self.connect(1)
        self.run_async(self.hub.post("BNK1", 1, "birinchi"))

        late = self.connect(2)
        history = late.sent[0]
        self.assertEqual(history["type"], "chat-history")
        self.assertEqual([item["text"] for item in history["messages"]], ["birinchi"])

    def test_empty_message_rejected(self) -> None:
        self.add_player(1, "Ali")
        with self.assertRaises(ChatError):
            self.run_async(self.hub.post("BNK1", 1, "   "))

    def test_long_message_is_trimmed(self) -> None:
        self.add_player(1, "Ali")
        entry = self.run_async(self.hub.post("BNK1", 1, "x" * (MAX_MESSAGE_LENGTH + 120)))
        self.assertEqual(len(entry.text), MAX_MESSAGE_LENGTH + 1)
        self.assertTrue(entry.text.endswith("…"))

    def test_newlines_are_flattened(self) -> None:
        self.add_player(1, "Ali")
        entry = self.run_async(self.hub.post("BNK1", 1, "bir\nikki\r\nuch"))
        self.assertNotIn("\n", entry.text)

    # ------------------------------------------------------------------
    # Begonalar
    # ------------------------------------------------------------------
    def test_stranger_cannot_write(self) -> None:
        self.add_player(1, "Ali")
        self.add_player(9, "", member=False)
        with self.assertRaises(ChatError):
            self.run_async(self.hub.post("BNK1", 9, "ruxsat bormi?"))

    def test_stranger_does_not_see_history(self) -> None:
        self.add_player(1, "Ali")
        self.add_player(9, "", member=False)
        self.connect(1)
        self.run_async(self.hub.post("BNK1", 1, "maxfiy suhbat"))

        stranger = self.connect(9)
        history = stranger.sent[0]
        self.assertEqual(history["messages"], [])
        self.assertTrue(history["locked"])

    def test_unknown_room_is_not_invented(self) -> None:
        with self.assertRaises(ChatError):
            self.run_async(self.hub.post("YOQ1", 1, "salom"))

    # ------------------------------------------------------------------
    # Arvoh (o'yindan chiqqan) o'yinchi
    # ------------------------------------------------------------------
    def test_ghost_writes_once_then_locked(self) -> None:
        self.add_player(1, "Ali")
        self.add_player(2, "Vali", alive=False)
        self.connect(1)
        self.connect(2)

        entry = self.run_async(self.hub.post("BNK1", 2, "oxirgi so'zim"))
        self.assertTrue(entry.ghost)
        # Bitta so'zdan keyin maydon qulflanadi.
        self.assertTrue(self.hub.locked("BNK1", 2, self.players[2]))

        with self.assertRaises(ChatError) as ctx:
            self.run_async(self.hub.post("BNK1", 2, "yana bir so'z"))
        self.assertIn("arvohsiz", str(ctx.exception))
        self.assertTrue(self.hub.locked("BNK1", 2, self.players[2]))

    def test_dead_player_ghost_message_is_marked(self) -> None:
        self.add_player(1, "Ali")
        self.add_player(2, "Vali", alive=False)
        member = self.connect(1)
        self.connect(2)

        self.run_async(self.hub.post("BNK1", 2, "xayr"))
        payload = [item for item in member.sent if item.get("type") == "chat"][-1]
        self.assertTrue(payload["message"]["ghost"])

    # ------------------------------------------------------------------
    # Mafiya kechasi
    # ------------------------------------------------------------------
    def test_night_message_only_for_living_mafia(self) -> None:
        self.add_player(1, "Don", mafia=True, night=True)
        self.add_player(2, "Tinch", night=True)
        self.add_player(3, "O'lgan mafiya", mafia=True, night=True, alive=False)
        don = self.connect(1)
        civilian = self.connect(2)
        dead_mafia = self.connect(3)

        entry = self.run_async(self.hub.post("BNK1", 1, "kimni o'ldiramiz?"))
        self.assertEqual(entry.kind, KIND_MAFIA)
        self.assertEqual(don.chat_texts(), ["kimni o'ldiramiz?"])
        self.assertEqual(civilian.chat_texts(), [])
        self.assertEqual(dead_mafia.chat_texts(), [])

    def test_civilian_cannot_write_at_night(self) -> None:
        self.add_player(1, "Don", mafia=True, night=True)
        self.add_player(2, "Tinch", night=True)
        with self.assertRaises(ChatError):
            self.run_async(self.hub.post("BNK1", 2, "men ham yozaman"))

    def test_mafia_chat_hidden_from_newcomer_history(self) -> None:
        self.add_player(1, "Don", mafia=True, night=True)
        self.add_player(2, "Tinch", night=True)
        self.connect(1)
        self.run_async(self.hub.post("BNK1", 1, "maxfiy reja"))

        civilian = self.connect(2)
        self.assertEqual(civilian.sent[0]["messages"], [])

    # ------------------------------------------------------------------
    # Tizim xabarlari
    # ------------------------------------------------------------------
    def test_system_message_goes_to_all_members(self) -> None:
        self.add_player(1, "Ali")
        self.add_player(2, "Vali")
        first = self.connect(1)
        second = self.connect(2)

        self.run_async(self.hub.system("BNK1", "Vali xonaga qo'shildi"))
        for socket in (first, second):
            payload = [item for item in socket.sent if item.get("type") == "chat"][-1]
            self.assertEqual(payload["message"]["kind"], KIND_SYSTEM)
            self.assertEqual(payload["message"]["text"], "Vali xonaga qo'shildi")

    def test_system_message_is_not_sent_to_strangers(self) -> None:
        self.add_player(1, "Ali")
        self.add_player(9, "", member=False)
        member = self.connect(1)
        stranger = self.connect(9)

        self.run_async(self.hub.system("BNK1", "O'yin boshlandi"))
        self.assertEqual(member.chat_texts(), ["O'yin boshlandi"])
        self.assertEqual([item for item in stranger.sent if item.get("type") == "chat"], [])

    def test_disconnect_stops_delivery(self) -> None:
        self.add_player(1, "Ali")
        self.add_player(2, "Vali")
        first = self.connect(1)
        second = self.connect(2)
        self.run_async(self.hub.disconnect("BNK1", second))

        self.run_async(self.hub.post("BNK1", 1, "faqat bittasi ko'radi"))
        self.assertEqual(first.chat_texts(), ["faqat bittasi ko'radi"])
        self.assertEqual(second.chat_texts(), [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
