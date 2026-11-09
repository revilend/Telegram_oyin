"""Test rejimi: xona ochilganda virtual botlar qo'shilib, o'yin avtomatik boshlanadi.

`TEST_BOTS=1` yoqilganda har bir ochilgan xonani kuzatuvchi oqim (watcher)
tekshiradi: xonada faqat bitta haqiqiy o'yinchi bo'lsa, uchta virtual bot
qo'shiladi, ular tayyor holatga o'tadi va o'yin avtomatik boshlanadi. Keyin
botlar o'z navbatida karta ochadi, ovoz beradi va o'yinni oxirigacha o'ynaydi;
yakunda tanga hamda statistika o'zgarishi (delta) logga yoziladi.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from typing import Any

logger = logging.getLogger(__name__)

TEST_MODE_ENV = "TEST_BOTS"
BOT_IDS = (8_000_000_001, 8_000_000_002, 8_000_000_003)
BOT_NAMES = ("🤖 Test bir", "🤖 Test ikki", "🤖 Test uç")
BOT_USERNAMES = ("testbot1", "testbot2", "testbot3")
BUNKER_CARDS = ("profession", "health", "hobby", "phobia", "baggage", "fact")
GAMES = ("bunker", "mafia", "spyfall", "alias", "bomb")
TICK_SECONDS = 2.0
IDLE_TICKS = 3
LOG_LIMIT = 300

_LOG: deque[str] = deque(maxlen=LOG_LIMIT)
_SESSIONS: dict[str, dict[str, Any]] = {}
_LOCK = threading.RLock()
_STOP = threading.Event()
_THREAD: threading.Thread | None = None


# ----------------------------------------------------------------------
# Yordamchi funksiyalar
# ----------------------------------------------------------------------
def log(message: str) -> None:
    """Xabarni jurnalga va ko'rinadigan tarixga yozadi."""
    logger.info("%s", message)
    with _LOCK:
        _LOG.append(f"{time.strftime('%H:%M:%S')} {message}")


def test_mode_enabled() -> bool:
    """Test rejimi env orqali yoqilganmi?"""
    return str(os.environ.get(TEST_MODE_ENV, "")).strip().lower() in {"1", "true", "yes", "on"}


def _key(game: str, code: str) -> str:
    return f"{game}:{(code or '').strip().upper()}"


def _bot_name(index: int) -> str:
    return BOT_NAMES[index % len(BOT_NAMES)]


def _snapshot(ids: list[int]) -> dict[int, dict[str, int]]:
    """Tanga va statistika holatini yozib oladi."""
    from core.economy import get_economy

    economy = get_economy()
    data: dict[int, dict[str, int]] = {}
    for uid in ids:
        try:
            user = economy.get_user(int(uid))
        except Exception:
            user = economy.ensure_user(int(uid))
        data[int(uid)] = {
            "coins": int(getattr(user, "coins", 0) or 0),
            "games_played": int(getattr(user, "games_played", 0) or 0),
            "wins": int(getattr(user, "wins", 0) or 0),
        }
    return data


def _diff(before: dict[int, dict[str, int]], after: dict[int, dict[str, int]]) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for uid, now in after.items():
        was = before.get(uid, {})
        result[str(uid)] = {
            "coins": now["coins"] - int(was.get("coins", 0)),
            "games_played": now["games_played"] - int(was.get("games_played", 0)),
            "wins": now["wins"] - int(was.get("wins", 0)),
        }
    return result


# ----------------------------------------------------------------------
# Menejerlar
# ----------------------------------------------------------------------
def _bunker_manager() -> Any:
    from engine.game_manager import get_default_manager

    return get_default_manager()


def _mafia_lobby() -> Any:
    from bot.handlers import mafia_group

    return mafia_group.get_default_manager()


def _spyfall_manager() -> Any:
    from games.spyfall.manager import get_default_manager

    return get_default_manager()


def _alias_manager() -> Any:
    from games.alias.engine import get_default_manager

    return get_default_manager()


def _bomb_manager() -> Any:
    from games.bomb.manager import get_default_manager

    return get_default_manager()


# ----------------------------------------------------------------------
# Xonani botlar bilan to'ldirish
# ----------------------------------------------------------------------
def _join_bots_bunker(code: str) -> Any:
    manager = _bunker_manager()
    for index, uid in enumerate(BOT_IDS):
        manager.join_room(code, uid, _bot_name(index), BOT_USERNAMES[index])
    room = manager.get_room(code)
    manager.start_game(code)
    return room


def _join_bots_mafia(code: str) -> Any:
    lobby = _mafia_lobby()
    game = lobby.get_game(code)
    for index, uid in enumerate(BOT_IDS):
        lobby.join(code, uid, _bot_name(index), BOT_USERNAMES[index])
    lobby.start_game(code, game.host_id)
    return game


def _join_bots_spyfall(code: str) -> Any:
    manager = _spyfall_manager()
    room = manager.get_room(code)
    for index, uid in enumerate(BOT_IDS):
        manager.join(code, uid, _bot_name(index))
    manager.start(code, room.host_id)
    return manager.get_room(code)


def _join_bots_alias(code: str) -> Any:
    manager = _alias_manager()
    room = manager.get_room(code)
    for index, uid in enumerate(BOT_IDS):
        manager.join(code, uid, _bot_name(index), BOT_USERNAMES[index])
    manager.start_game(code, room.host_id)
    return manager.get_room(code)


def _join_bots_bomb(code: str) -> Any:
    manager = _bomb_manager()
    room = manager.get_room(code)
    for index, uid in enumerate(BOT_IDS):
        manager.join(code, uid, _bot_name(index))
    manager.start(code, room.host_id)
    return manager.get_room(code)


JOINERS = {
    "bunker": _join_bots_bunker,
    "mafia": _join_bots_mafia,
    "spyfall": _join_bots_spyfall,
    "alias": _join_bots_alias,
    "bomb": _join_bots_bomb,
}


def fill_room(game: str, code: str) -> dict[str, Any]:
    """Xonaga 3 ta bot qo'shib, o'yinni avtomatik boshlaydi."""
    kind = (game or "").strip().lower()
    joiner = JOINERS.get(kind)
    if joiner is None:
        return {"ok": False, "error": f"Noma'lum o'yin: {game}. Mavjud: {', '.join(GAMES)}"}
    key = _key(kind, code)
    try:
        room = joiner(code)
    except Exception as error:  # hech qachon serverni yiqitmaydi
        logger.exception("Botlarni xonaga qo'shib bo'lmadi: %s %s", kind, code)
        log(f"❌ {kind} {code}: botlar qo'shilmadi — {error}")
        return {"ok": False, "error": str(error)}
    with _LOCK:
        _SESSIONS[key] = {
            "game": kind,
            "code": str(code).upper(),
            "ids": [int(uid) for uid in BOT_IDS],
            "before": _snapshot(list(BOT_IDS)),
            "started": time.time(),
            "reported": False,
        }
    log(f"🤖 {kind} {code}: 3 ta bot qo'shildi, o'yin boshlandi")
    return {"ok": True, "game": kind, "code": str(code).upper(), "bots": len(BOT_IDS)}


# ----------------------------------------------------------------------
# O'yin holati va bot harakatlari
# ----------------------------------------------------------------------
def _finished(game: str, code: str) -> bool:
    try:
        if game == "bunker":
            from models.game import RoomStatus

            return _bunker_manager().get_room(code).status is RoomStatus.FINISHED
        if game == "mafia":
            from games.mafia.engine import GamePhase

            return _mafia_lobby().get_game(code).room.phase is GamePhase.FINISHED
        if game == "spyfall":
            from games.spyfall.engine import Phase

            room = _spyfall_manager().get_room(code)
            return room.winner is not None or room.phase is Phase.FINISHED
        if game == "alias":
            from games.alias.engine import AliasStatus

            room = _alias_manager().get_room(code)
            return room.is_complete or room.status is AliasStatus.FINISHED
        if game == "bomb":
            from games.bomb.engine import BombStatus

            return _bomb_manager().get_room(code).status is BombStatus.FINISHED
    except Exception:
        return False
    return False


def _tick_bunker(code: str) -> None:
    from engine.game_manager import GameError
    from models.game import RoomStatus

    manager = _bunker_manager()
    room = manager.get_room(code)
    if room.status is RoomStatus.FINISHED:
        return
    alive = [player for player in room.players.values() if player.is_alive]
    if room.status is RoomStatus.SHIELD_OFFER:
        for player in alive:
            if player.user_id not in BOT_IDS:
                continue
            try:
                manager.decline_shield(code, player.user_id)
            except GameError:
                continue
        return
    for player in alive:
        if player.user_id not in BOT_IDS:
            continue
        for card in BUNKER_CARDS:
            try:
                manager.reveal_card(code, player.user_id, card)
            except GameError:
                continue
        target = next((item for item in alive if item.user_id != player.user_id), None)
        if target is None:
            continue
        try:
            manager.cast_vote(code, player.user_id, target.user_id)
        except GameError:
            continue
    try:
        manager.tally_votes(code)
    except GameError:
        pass


def _tick_mafia(code: str) -> None:
    from games.mafia.engine import (
        NIGHT_ACTION_BY_ROLE,
        NIGHT_OPTIONS_BY_ROLE,
        GamePhase,
        MafiaError,
        NightActionType,
        check_game_over,
        resolve_day_vote,
        resolve_night,
        winning_player_ids,
    )

    lobby = _mafia_lobby()
    game = lobby.get_game(code)
    room = game.room
    if room.phase is GamePhase.FINISHED:
        return
    if room.phase is GamePhase.NIGHT:
        for player in room.alive_players:
            if player.user_id not in BOT_IDS:
                continue
            options = NIGHT_OPTIONS_BY_ROLE.get(player.role)
            kind = options[0] if options else NIGHT_ACTION_BY_ROLE.get(player.role)
            if kind is None:
                continue
            if kind in (NightActionType.WITCH_HEAL, NightActionType.COPY):
                candidates = [item for item in room.players.values() if not item.is_alive]
            else:
                candidates = [item for item in room.alive_players if item.user_id != player.user_id]
            if not candidates:
                continue
            try:
                room.submit_night_action(player.user_id, candidates[0].user_id, kind=kind)
            except MafiaError:
                continue
        resolve_night(room)
        winner = check_game_over(room)
        if winner is not None:
            room.finish(winner)
            _record_mafia(room, winning_player_ids(room))
            return
        room.begin_voting()
        return
    if room.phase is GamePhase.VOTING:
        alive = room.alive_players
        for player in alive:
            if player.user_id not in BOT_IDS:
                continue
            target = next((item for item in alive if item.user_id != player.user_id), None)
            if target is None:
                continue
            try:
                room.cast_vote(player.user_id, target.user_id)
            except MafiaError:
                continue
        eliminated = room.tally_votes()
        resolve_day_vote(room, eliminated)
        if room.phase is GamePhase.FINISHED:
            _record_mafia(room, winning_player_ids(room))
        elif room.phase is not GamePhase.NIGHT:
            room.begin_night()


def _record_mafia(room: Any, winners: list[int]) -> None:
    """Mafiya yakunida statistika faqat bir marta yoziladi."""
    try:
        from core.economy import get_economy

        get_economy().record_mafia_game(room.room_id, list(room.players.keys()), winners)
    except Exception:
        logger.exception("Mafiya statistikasini yozib bo'lmadi")


def _tick_spyfall(code: str) -> None:
    from games.spyfall.engine import Phase, SpyfallError
    from games.spyfall.manager import SpyfallRoomError
    from core.economy import get_economy

    manager = _spyfall_manager()
    room = manager.get_room(code)
    if room.phase is Phase.LOBBY or room.winner is not None or room.phase is Phase.FINISHED:
        return
    economy = get_economy()
    players = list(room.players.values())
    humans = [player for player in players if player.user_id not in BOT_IDS]
    target = humans[0] if humans else next((p for p in players if p.user_id not in BOT_IDS), None)
    if target is None:
        return
    for player in players:
        if player.user_id not in BOT_IDS:
            continue
        try:
            manager.vote(code, player.user_id, target.user_id, economy=economy)
        except (SpyfallError, SpyfallRoomError):
            continue
    try:
        manager.tally(code, room.host_id, economy=economy)
    except (SpyfallError, SpyfallRoomError):
        pass


def _tick_alias(code: str) -> None:
    from games.alias.engine import AliasError, AliasStatus

    manager = _alias_manager()
    room = manager.get_room(code)
    if room.is_complete or room.status is AliasStatus.FINISHED:
        return
    current = room.current_round
    if current is None or current.is_over():
        try:
            manager.next_round(code)
        except AliasError:
            pass
        return
    guesser = next((uid for uid in BOT_IDS if uid != current.explainer_id), None)
    if guesser is None:
        return
    try:
        room.submit_guess(guesser, current.word.word)
    except AliasError:
        pass
    if not room.is_complete:
        try:
            manager.next_round(code)
        except AliasError:
            pass


def _tick_bomb(code: str) -> None:
    from games.bomb.engine import BombError, BombStatus

    room = _bomb_manager().get_room(code)
    if room.status is not BombStatus.PLAYING:
        return
    current = room.current_player_id
    if current is None:
        return
    actor = int(current)
    if actor not in BOT_IDS:
        # Test rejimida haqiqiy o'yinchi navbatni cheksiz ushlab turmasin:
        # IDLE_TICKS bosqichdan keyin bot uning kartasini o'zi tashlaydi.
        key = _key("bomb", code)
        with _LOCK:
            session = _SESSIONS.get(key)
            if session is None:
                return
            if session.get("turn_id") != actor:
                session["turn_id"] = actor
                session["turn_ticks"] = 0
                return
            session["turn_ticks"] = int(session.get("turn_ticks") or 0) + 1
            ticks = session["turn_ticks"]
        if ticks < IDLE_TICKS:
            return
    if room.pending_defuse is not None:
        try:
            room.defuse_bomb(room.pending_defuse, "middle")
        except BombError:
            pass
        return
    try:
        room.draw_card(actor)
    except BombError:
        pass


TICKERS = {
    "bunker": _tick_bunker,
    "mafia": _tick_mafia,
    "spyfall": _tick_spyfall,
    "alias": _tick_alias,
    "bomb": _tick_bomb,
}


# ----------------------------------------------------------------------
# Yakuniy hisobot
# ----------------------------------------------------------------------
def _finalize(key: str) -> None:
    with _LOCK:
        session = _SESSIONS.get(key)
        if session is None or session.get("reported"):
            return
        session["reported"] = True
        before = session["before"]
        game = session["game"]
        code = session["code"]
        ids = list(session["ids"])
        del _SESSIONS[key]
    if game == "bunker":
        _record_bunker(code)
    elif game == "alias":
        _record_alias(code)
    after = _snapshot(ids)
    deltas = _diff(before, after)
    winners = [uid for uid, delta in deltas.items() if delta["wins"] > 0]
    coins = sum(delta["coins"] for delta in deltas.values())
    played = sum(delta["games_played"] for delta in deltas.values())
    log(
        f"✅ {game} {code}: tugadi — g'olib {', '.join(winners) or '—'}, "
        f"tanga {coins:+d}, o'yin {played:+d}, statistika yozildi"
    )

def _record_alias(code: str) -> None:
    """Alias yakunida statistika faqat bir marta yoziladi."""
    try:
        from core.economy import get_economy

        room = _alias_manager().get_room(code)
        ids = list(room.players.keys())
        winners = [player.user_id for player in room.winners()] if hasattr(room, "winners") else []
        get_economy().record_finished_game(room.code, ids, winners or ids, game="alias", reward=0)
    except Exception:
        logger.exception("Alias statistikasini yozib bo'lmadi")


def _record_bunker(code: str) -> None:
    """Bunker yakunida statistika faqat bir marta yoziladi."""
    try:
        from core.economy import get_economy

        room = _bunker_manager().get_room(code)
        winners = [player.user_id for player in room.players.values() if player.is_alive]
        ids = list(room.players.keys())
        get_economy().record_finished_game(room.code, ids, winners, game="bunker", reward=0)
    except Exception:
        logger.exception("Bunker statistikasini yozib bo'lmadi")


# ----------------------------------------------------------------------
# Kuzatuvchi oqim
# ----------------------------------------------------------------------
def _candidates() -> list[tuple[str, str, int]]:
    """Bot qo'shish mumkin bo'lgan ochiq xonalar ro'yxati."""
    found: list[tuple[str, str, int]] = []
    try:
        for room in _bunker_manager().open_rooms(50):
            found.append(("bunker", room.code, len(room.players)))
    except Exception:
        logger.debug("Bunker xonalarini o'qib bo'lmadi", exc_info=True)
    try:
        for game in _mafia_lobby().open_games(50):
            found.append(("mafia", game.code, len(game.room.players)))
    except Exception:
        logger.debug("Mafiya xonalarini o'qib bo'lmadi", exc_info=True)
    try:
        for room in _spyfall_manager().open_rooms(50):
            found.append(("spyfall", room.code, len(room.players)))
    except Exception:
        logger.debug("Josus xonalarini o'qib bo'lmadi", exc_info=True)
    try:
        for room in _alias_manager().open_rooms(50):
            found.append(("alias", room.code, len(room.players)))
    except Exception:
        logger.debug("Alias xonalarini o'qib bo'lmadi", exc_info=True)
    try:
        for room in list(getattr(_bomb_manager(), "_rooms", {}).values()):
            found.append(("bomb", room.code, len(room.players)))
    except Exception:
        logger.debug("Bomba xonalarini o'qib bo'lmadi", exc_info=True)
    return found


def step() -> None:
    """Bitta kuzatuv bosqichi: yangi xonani to'ldirish va botlarni o'ynatish."""
    if not test_mode_enabled():
        return
    # 1) Yolg'iz o'yinchi kutayotgan yangi xonalarga botlarni qo'shamiz.
    for game, code, players in _candidates():
        key = _key(game, code)
        with _LOCK:
            known = key in _SESSIONS
        if known or players != 1:
            continue
        try:
            fill_room(game, code)
        except Exception:
            logger.exception("Test botlarni qo'shib bo'lmadi: %s %s", game, code)
    # 2) Boshlangan o'yinlarda botlarni navbatma-navbat o'ynatamiz.
    with _LOCK:
        active = list(_SESSIONS.keys())
    for key in active:
        game, _, code = key.partition(":")
        try:
            if _finished(game, code):
                _finalize(key)
                continue
            ticker = TICKERS.get(game)
            if ticker is not None:
                ticker(code)
        except Exception:
            logger.exception("Test bot qadami yiqildi: %s %s", game, code)


def _loop() -> None:
    log("🟢 Test bot rejimi yoqildi")
    while not _STOP.is_set():
        try:
            step()
        except Exception:
            logger.exception("Test bot kuzatuvchisi yiqildi")
        _STOP.wait(TICK_SECONDS)


def start_watcher() -> None:
    """Kuzatuvchi oqimni ishga tushiradi (test rejimi yoqilgan bo'lsa)."""
    global _THREAD
    if not test_mode_enabled():
        logger.info("%s yoqilmagan — test botlar kuzatilmaydi", TEST_MODE_ENV)
        return
    with _LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return
        _STOP.clear()
        _THREAD = threading.Thread(target=_loop, name="test-bots", daemon=True)
        _THREAD.start()


def stop_watcher() -> None:
    """Kuzatuvchi oqimni to'xtatadi."""
    global _THREAD
    _STOP.set()
    with _LOCK:
        thread, _THREAD = _THREAD, None
    if thread is not None:
        thread.join(timeout=2.0)


def status() -> dict[str, Any]:
    """Test rejimi holati va oxirgi loglar."""
    with _LOCK:
        sessions = [
            {"game": value["game"], "code": value["code"], "started": value["started"]}
            for value in _SESSIONS.values()
        ]
        return {
            "enabled": test_mode_enabled(),
            "running": bool(_THREAD is not None and _THREAD.is_alive()),
            "bots": [{"id": uid, "name": BOT_NAMES[index]} for index, uid in enumerate(BOT_IDS)],
            "rooms": sessions,
            "log": list(_LOG)[-40:],
        }


__all__ = [
    "BOT_IDS",
    "BOT_NAMES",
    "GAMES",
    "TEST_MODE_ENV",
    "fill_room",
    "log",
    "start_watcher",
    "status",
    "step",
    "stop_watcher",
    "test_mode_enabled",
]
