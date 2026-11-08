"""Barcha o'yin xonalari va inventarning JSONB persistensiyasi testlari."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from games.alias.engine import AliasManager, AliasWord, WordBook
from games.bomb.manager import BombManager
from games.mafia.engine import GamePhase, MafiaPlayer, MafiaRoom
from bot.handlers.mafia_group import MafiaGame, MafiaLobbyManager
from core import room_store
from core.economy import EconomyStore
from core.shop import ShopStore
from engine.game_manager import GameManager


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    """room_store va ShopStore ishlatadigan minimal PostgREST klienti."""

    def __init__(self, client: "FakeClient", table: str) -> None:
        self.client = client
        self.table = table
        self.mode = "select"
        self.payload = None
        self.filters: dict[str, object] = {}
        self.limit_value: int | None = None

    def select(self, *_columns):
        self.mode = "select"
        return self

    def upsert(self, payload, **_kwargs):
        self.payload = payload
        self.mode = "upsert"
        return self

    def insert(self, payload, **_kwargs):
        self.payload = payload
        self.mode = "insert"
        return self

    def delete(self):
        self.mode = "delete"
        return self

    def eq(self, column, value):
        self.filters[column] = value
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def execute(self):
        if self.mode == "upsert":
            if self.table == "user_inventory":
                self.client.upsert(self.table, self.payload)
                return FakeResponse([])
            code = str(self.payload["code"])
            self.client.rooms.setdefault(self.table, {})[code] = self.payload["state"]
            return FakeResponse([])
        if self.mode == "insert":
            self.client.inserted.append((self.table, dict(self.payload)))
            return FakeResponse([])
        if self.mode == "delete":
            code = str(self.filters.get("code") or "").upper()
            self.client.rooms.setdefault(self.table, {}).pop(code, None)
            return FakeResponse([])

        # Select: inventar qatorlari yoki xona holatlari.
        if self.table in room_store.ROOM_TABLES:
            states = self.client.rooms.get(self.table, {})
            if "code" in self.filters:
                state = states.get(str(self.filters["code"]).upper())
                rows = [{"state": state}] if state is not None else []
            else:
                rows = [{"state": state} for state in states.values()]
            if self.limit_value is not None:
                rows = rows[: self.limit_value]
            return FakeResponse(rows)

        rows = [
            dict(row)
            for row in self.client.inventory
            if all(row.get(key) == value for key, value in self.filters.items())
        ]
        return FakeResponse(rows[: self.limit_value] if self.limit_value is not None else rows)


class FakeClient:
    def __init__(self) -> None:
        self.rooms: dict[str, dict[str, dict]] = {}
        self.inventory: list[dict] = []
        self.inserted: list[tuple[str, dict]] = []
        self._inventory_primary: dict[tuple[int, str], dict] = {}

    def table(self, name: str) -> FakeQuery:
        return FakeQuery(self, name)

    def upsert(self, table: str, payload: dict, **_kwargs) -> None:
        if table == "user_inventory":
            key = (int(payload["user_id"]), str(payload["item_slug"]))
            self._inventory_primary[key] = dict(payload)
            self.inventory = list(self._inventory_primary.values())
            return
        self.rooms.setdefault(table, {})[str(payload["code"])] = payload["state"]


class RoomPersistenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FakeClient()
        self.store = SimpleNamespace(enabled=True, client=self.client)
        self.patcher = patch("core.room_store.get_store", return_value=self.store)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def _bind_room_store(self, manager) -> None:
        table = {
            GameManager: room_store.BUNKER_ROOMS_TABLE,
            MafiaLobbyManager: room_store.MAFIA_ROOMS_TABLE,
            BombManager: room_store.BOMB_ROOMS_TABLE,
            AliasManager: room_store.ALIAS_ROOMS_TABLE,
        }[type(manager)]
        manager.set_change_handler(
            lambda room: room_store.save_state(table, room.code, room.to_state())
            if hasattr(room, "to_state")
            else room_store.save_bunker(room, {})
        )

    def test_bunker_room_survives_manager_restart(self) -> None:
        manager = GameManager(seed=3)
        manager.set_change_handler(room_store.save_bunker)
        room = manager.create_room(101, "Ali", "ali", bunker_capacity=2)
        manager.join_room(room.code, 102, "Vali", "vali")
        manager.join_room(room.code, 103, "Zilola", "zilola")
        manager.join_room(room.code, 104, "Sardor", "sardor")
        manager.start_game(room.code)

        restored_manager = GameManager(seed=4)
        restored_manager.set_room_loader(room_store.load_bunker)
        restored = restored_manager.get_room(room.code.lower())
        self.assertEqual(restored.code, room.code)
        self.assertEqual(set(restored.players), {101, 102, 103, 104})
        self.assertEqual(restored.status.value, "PLAYING")

    def test_mafia_room_survives_manager_restart(self) -> None:
        manager = MafiaLobbyManager(seed=5)
        self._bind_room_store(manager)
        game = manager.create_game(0, 201, "Ali", "ali")
        manager.join(game.code, 202, "Vali", "vali")

        restored_manager = MafiaLobbyManager(seed=6)
        restored_manager.set_room_loader(
            lambda code: MafiaGame.from_state(
                room_store.load_state(room_store.MAFIA_ROOMS_TABLE, code)
            )
            if room_store.load_state(room_store.MAFIA_ROOMS_TABLE, code)
            else None
        )
        restored = restored_manager.get_game(game.code.lower())
        self.assertEqual(restored.code, game.code)
        self.assertEqual(restored.chat_id, 0)
        self.assertEqual(set(restored.room.players), {201, 202})
        self.assertEqual(restored.room.phase, GamePhase.LOBBY)
        self.assertEqual(restored.usernames[201], "ali")

    def test_bomb_room_survives_manager_restart(self) -> None:
        manager = BombManager(seed=7)
        self._bind_room_store(manager)
        room = manager.create_room(301, "Ali")
        manager.join(room.code, 302, "Vali")

        restored_manager = BombManager(seed=8)
        restored_manager.set_room_loader(
            lambda code: __import__(
                "games.bomb.engine", fromlist=["BombRoom"]
            ).BombRoom.from_state(
                room_store.load_state(room_store.BOMB_ROOMS_TABLE, code)
            )
            if room_store.load_state(room_store.BOMB_ROOMS_TABLE, code)
            else None
        )
        restored = restored_manager.get_room(room.code.lower())
        self.assertEqual(restored.code, room.code)
        self.assertEqual(set(restored.players), {301, 302})
        self.assertEqual(restored.status.value, "LOBBY")

    def test_alias_room_round_survives_manager_restart(self) -> None:
        manager = AliasManager(
            seed=9,
            wordbook=WordBook([AliasWord("Kitob", ("varaq",))]),
        )
        self._bind_room_store(manager)
        room = manager.create_room(-100, 401, "Ali", "ali")
        manager.join(room.code, 402, "Vali", "vali")
        manager.start_game(room.code, 401)
        self.assertIsNotNone(room.current_round)

        from games.alias.engine import AliasRoom

        restored_manager = AliasManager(
            seed=10,
            wordbook=WordBook([AliasWord("Kitob", ("varaq",))]),
        )
        restored_manager.set_room_loader(
            lambda code: AliasRoom.from_state(
                room_store.load_state(room_store.ALIAS_ROOMS_TABLE, code)
            )
            if room_store.load_state(room_store.ALIAS_ROOMS_TABLE, code)
            else None
        )
        restored = restored_manager.get_room(room.code.lower())
        self.assertEqual(restored.code, room.code)
        self.assertEqual(set(restored.players), {401, 402})
        self.assertIsNotNone(restored.current_round)
        self.assertTrue(restored.current_round.word.word)

    def test_inventory_is_read_from_supabase_after_new_store(self) -> None:
        economy = EconomyStore(url="", key="", client=None)
        economy.ensure_user(501)
        economy.add_coins(501, 500)
        store = ShopStore(economy=economy, client=self.client)
        store.buy(501, "frame_gold")
        self.assertEqual(store.entry(501, "frame_gold").quantity, 1)
        self.assertIn(
            ("shop_transactions", self.client.inserted[-1][1]),
            self.client.inserted,
        )

        # Yangi jarayon: xotira bo'sh, lekin inventar Supabase'dan o'qiladi.
        restarted = ShopStore(economy=economy, client=self.client)
        self.assertEqual(restarted.entry(501, "frame_gold").quantity, 1)


if __name__ == "__main__":
    unittest.main()
