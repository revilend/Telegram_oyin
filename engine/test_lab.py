"""Virtual bot-o'yinchilar bilan o'yinlarni avtomatik sinash laboratoriyasi.

Admin bitta o'zi 4+ kishilik o'yinlarni tekshira olmaydi: bu modul har bir
o'yin uchun yangi menejer yaratadi, xonaga virtual botlarni qo'shadi, o'yinni
to'liq oxirigacha o'ynaydi va g'oliblar hamda iqtisodiyot (tanga/statistika)
natijalarini hisobotga yig'adi.
"""

from __future__ import annotations

import logging
import random
import traceback
from typing import Any, Callable

from core.economy import get_economy
from engine.game_manager import GameError, GameManager
from games.alias.engine import AliasError, AliasManager, AliasStatus
from games.bomb.engine import BombError, BombStatus
from games.bomb.manager import BombManager
from games.mafia.engine import (
    NIGHT_ACTION_BY_ROLE,
    NIGHT_OPTIONS_BY_ROLE,
    GamePhase,
    MafiaError,
    MafiaPlayer,
    MafiaRoom,
    NightActionType,
    check_game_over,
    resolve_day_vote,
    resolve_night,
    winning_player_ids,
)
from games.spyfall.engine import SpyfallError
from games.spyfall.manager import SpyfallManager
from models.game import RoomStatus

logger = logging.getLogger(__name__)

TEST_HOST_ID = 9_000_000_000
BOT_IDS = (9_000_000_001, 9_000_000_002, 9_000_000_003, 9_000_000_004, 9_000_000_005)
BOT_NAMES = ("🤖 Alfa", "🤖 Bravo", "🤖 Charlie", "🤖 Delta", "🤖 Echo")
BUNKER_CARDS = ("profession", "health", "hobby", "phobia", "baggage", "fact")
GAMES = ("bunker", "mafia", "spyfall", "alias", "bomb")


def _snapshot(economy: Any, ids: list[int]) -> dict[int, dict[str, int]]:
    """O'yinchilarning tanga/statistika holatini yozib oladi."""
    data: dict[int, dict[str, int]] = {}
    for uid in ids:
        try:
            user = economy.get_user(int(uid))
        except Exception:  # hisob hali yaratilmagan bo'lishi mumkin
            user = economy.ensure_user(int(uid))
        data[int(uid)] = {
            "coins": int(getattr(user, "coins", 0) or 0),
            "games_played": int(getattr(user, "games_played", 0) or 0),
            "wins": int(getattr(user, "wins", 0) or 0),
        }
    return data


def _diff(before: dict[int, dict[str, int]], after: dict[int, dict[str, int]]) -> dict[int, dict[str, int]]:
    result: dict[int, dict[str, int]] = {}
    for uid, now in after.items():
        was = before.get(uid, {})
        result[uid] = {
            "coins": now["coins"] - int(was.get("coins", 0)),
            "games_played": now["games_played"] - int(was.get("games_played", 0)),
            "wins": now["wins"] - int(was.get("wins", 0)),
        }
    return result


def _name(uid: int) -> str:
    if uid == TEST_HOST_ID:
        return "🧪 Test host"
    if uid in BOT_IDS:
        return BOT_NAMES[BOT_IDS.index(uid)]
    return f"ID {uid}"


def run_bunker(bots: int = 3) -> dict[str, Any]:
    """Bunker: botlar kartalarni ochadi, ovoz beradi va o'yin tugaydi."""
    manager = GameManager(seed=17)
    log: list[str] = []
    ids: list[int] = []
    room = manager.create_room(TEST_HOST_ID, "Test host", "testhost")
    for index in range(bots):
        uid = BOT_IDS[index]
        manager.join_room(room.code, uid, BOT_NAMES[index], f"bot{index + 1}")
        ids.append(uid)
    ids.append(TEST_HOST_ID)
    manager.start_game(room.code)
    log.append(f"Xona {room.code} ochildi, {len(room.players)} o'yinchi, sig'im {room.bunker_capacity}")

    for _ in range(80):
        room = manager.get_room(room.code)
        if room.status is RoomStatus.FINISHED:
            break
        alive = [player for player in room.players.values() if player.is_alive]
        changed = False
        if room.status is RoomStatus.SHIELD_OFFER:
            for player in alive:
                try:
                    manager.decline_shield(room.code, player.user_id)
                    changed = True
                except GameError:
                    continue
        else:
            for player in alive:
                for card in BUNKER_CARDS:
                    try:
                        manager.reveal_card(room.code, player.user_id, card)
                        changed = True
                    except GameError:
                        continue
            for player in alive:
                target = next((item for item in alive if item.user_id != player.user_id), None)
                if target is None:
                    continue
                try:
                    manager.cast_vote(room.code, player.user_id, target.user_id)
                    changed = True
                except GameError:
                    continue
            try:
                manager.tally_votes(room.code)
                changed = True
            except GameError:
                pass
        if not changed:
            break

    room = manager.get_room(room.code)
    winners = [player.user_id for player in room.players.values() if player.is_alive]
    economy = get_economy()
    before = _snapshot(economy, ids)
    economy.record_finished_game(room.code, ids, winners, game="bunker", reward=0)
    after = _snapshot(economy, ids)
    log.append(f"Holat: {room.status.value}, raund {room.current_round}")
    log.append("Omon qolganlar: " + (", ".join(_name(uid) for uid in winners) or "—"))
    return {
        "game": "bunker",
        "ok": room.status is RoomStatus.FINISHED,
        "code": room.code,
        "log": log,
        "winners": winners,
        "deltas": _diff(before, after),
    }


def run_spyfall(bots: int = 3) -> dict[str, Any]:
    """Josus: botlar ovoz beradi, natija va tangalar yoziladi."""
    manager = SpyfallManager(seed=23)
    economy = get_economy()
    log: list[str] = []
    room = manager.create_room(TEST_HOST_ID, "Test host")
    ids = [TEST_HOST_ID]
    for index in range(bots):
        uid = BOT_IDS[index]
        manager.join(room.code, uid, BOT_NAMES[index])
        ids.append(uid)
    manager.start(room.code, TEST_HOST_ID)
    room = manager.get_room(room.code)
    players = list(room.players.values())
    spy = next((player for player in players if player.is_spy), None)
    target = next((player for player in players if not player.is_spy), None)
    log.append(f"Xona {room.code}, {len(players)} o'yinchi, josus: {_name(spy.user_id) if spy else '—'}")
    before = _snapshot(economy, ids)
    if target is not None:
        for player in players:
            try:
                manager.vote(room.code, player.user_id, target.user_id, economy=economy)
            except SpyfallError:
                continue
        try:
            manager.tally(room.code, TEST_HOST_ID, economy=economy)
        except SpyfallError:
            pass
    room = manager.get_room(room.code)
    after = _snapshot(economy, ids)
    log.append(f"Holat: {getattr(room.phase, 'value', room.phase)}, g'olib: {getattr(room.winner, 'value', room.winner)}")
    return {
        "game": "spyfall",
        "ok": room.winner is not None,
        "code": room.code,
        "log": log,
        "winners": [],
        "deltas": _diff(before, after),
    }


def run_bomb(bots: int = 3) -> dict[str, Any]:
    """Portlovchi Bomba: botlar navbat bilan karta tortadi."""
    manager = BombManager(seed=29)
    economy = get_economy()
    log: list[str] = []
    room = manager.create_room(TEST_HOST_ID, "Test host")
    ids = [TEST_HOST_ID]
    for index in range(bots):
        uid = BOT_IDS[index]
        manager.join(room.code, uid, BOT_NAMES[index])
        ids.append(uid)
    manager.start(room.code, TEST_HOST_ID)
    before = _snapshot(economy, ids)
    for _ in range(200):
        if room.status is BombStatus.FINISHED:
            break
        current = room.current_player_id
        if current is None:
            break
        try:
            room.draw_card(current)
        except BombError:
            break
    after = _snapshot(economy, ids)
    log.append(f"Xona {room.code}, {len(ids)} o'yinchi")
    log.append(f"Holat: {room.status.value}, g'olib: {_name(room.winner_id) if room.winner_id else '—'}")
    return {
        "game": "bomb",
        "ok": room.status is BombStatus.FINISHED,
        "code": room.code,
        "log": log,
        "winners": [room.winner_id] if room.winner_id else [],
        "deltas": _diff(before, after),
    }


def run_mafia(bots: int = 5) -> dict[str, Any]:
    """Mafiya: tun harakatlari, kunduzgi ovoz va g'alaba sharti."""
    economy = get_economy()
    log: list[str] = []
    players = [MafiaPlayer(TEST_HOST_ID, "Test host")]
    players += [MafiaPlayer(BOT_IDS[index], BOT_NAMES[index]) for index in range(bots)]
    ids = [player.user_id for player in players]
    room = MafiaRoom(players, room_id="MAFTEST")
    room.start(rng=random.Random(31))
    log.append(f"Rollar tarqatildi: {len(players)} o'yinchi, tun {room.round}")
    before = _snapshot(economy, ids)

    for _ in range(40):
        if room.phase is GamePhase.FINISHED:
            break
        if room.phase is GamePhase.NIGHT:
            for player in room.alive_players:
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
                break
            room.begin_voting()
        elif room.phase is GamePhase.VOTING:
            alive = room.alive_players
            for player in alive:
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
                break
            if room.phase is GamePhase.NIGHT:
                continue
            room.begin_night()
        else:
            break

    winners = winning_player_ids(room)
    economy.record_mafia_game(room.room_id, ids, winners)
    after = _snapshot(economy, ids)
    log.append(f"Holat: {room.phase.value}, raund {room.round}, g'olib: {room.winner.value if room.winner else '—'}")
    log.append("G'oliblar: " + (", ".join(_name(uid) for uid in winners) or "—"))
    return {
        "game": "mafia",
        "ok": room.phase is GamePhase.FINISHED,
        "code": room.room_id,
        "log": log,
        "winners": winners,
        "deltas": _diff(before, after),
    }


def run_alias(bots: int = 3) -> dict[str, Any]:
    """Alias: botlar tushuntiruvchini topadi va barcha raundlar o'ynaladi."""
    economy = get_economy()
    log: list[str] = []
    try:
        manager = AliasManager(seed=37)  # type: ignore[call-arg]
    except TypeError:
        manager = AliasManager()
    room = manager.create_room(0, TEST_HOST_ID, "Test host", "testhost")
    ids = [TEST_HOST_ID]
    for index in range(bots):
        uid = BOT_IDS[index]
        manager.join(room.code, uid, BOT_NAMES[index], f"bot{index + 1}")
        ids.append(uid)
    before = _snapshot(economy, ids)
    manager.start_game(room.code, TEST_HOST_ID)
    for _ in range(30):
        room = manager.get_room(room.code)
        if room.is_complete or room.status is AliasStatus.FINISHED:
            break
        current = room.current_round
        if current is None:
            break
        word = current.word.word
        guesser = next(
            (player for player in room.players.values() if player.user_id != current.explainer_id),
            None,
        )
        if guesser is None:
            break
        room.submit_guess(guesser.user_id, word)
        if room.is_complete:
            break
        try:
            manager.next_round(room.code)
        except AliasError:
            break
    room = manager.get_room(room.code)
    winners = [player.user_id for player in room.winners()] if hasattr(room, "winners") else []
    economy.record_finished_game(room.code, ids, winners or ids, game="alias", reward=0)
    after = _snapshot(economy, ids)
    log.append(f"Xona {room.code}, {len(ids)} o'yinchi, {room.rounds_played}/{room.total_rounds} raund")
    log.append(f"Holat: {getattr(room.status, 'value', room.status)}")
    return {
        "game": "alias",
        "ok": room.is_complete or room.status is AliasStatus.FINISHED,
        "code": room.code,
        "log": log,
        "winners": winners,
        "deltas": _diff(before, after),
    }


RUNNERS: dict[str, Callable[..., dict[str, Any]]] = {
    "bunker": run_bunker,
    "mafia": run_mafia,
    "spyfall": run_spyfall,
    "alias": run_alias,
    "bomb": run_bomb,
}


def run_game(name: str = "all") -> dict[str, Any]:
    """Bitta yoki barcha o'yinlarni virtual botlar bilan sinaydi."""
    key = (name or "all").strip().lower()
    targets = list(GAMES) if key in ("all", "", "hammasi") else [key]
    reports: list[dict[str, Any]] = []
    for game in targets:
        runner = RUNNERS.get(game)
        if runner is None:
            return {
                "ok": False,
                "error": f"Noma'lum o'yin: {game}. Mavjud: {', '.join(GAMES)}",
                "reports": reports,
            }
        try:
            reports.append(runner())
        except Exception as error:  # simulyator hech qachon botni yiqitmasin
            logger.exception("Virtual bot testi yiqildi: %s", game)
            reports.append(
                {
                    "game": game,
                    "ok": False,
                    "log": [f"Xato: {error}"],
                    "error": "".join(traceback.format_exception_only(type(error), error)).strip(),
                    "winners": [],
                    "deltas": {},
                }
            )
    return {"ok": all(report.get("ok") for report in reports), "reports": reports}


def format_report(result: dict[str, Any]) -> str:
    """Hisobotni Telegram HTML matniga aylantiradi."""
    from html import escape

    lines: list[str] = ["🧪 <b>Virtual bot testi</b>"]
    if result.get("error"):
        lines.append(f"❌ {escape(str(result['error']))}")
    for report in result.get("reports", []):
        mark = "✅" if report.get("ok") else "⚠️"
        lines.append("")
        lines.append(f"{mark} <b>{escape(str(report.get('game', '?')).upper())}</b> · <code>{escape(str(report.get('code') or '—'))}</code>")
        for entry in report.get("log", [])[:6]:
            lines.append("• " + escape(str(entry)))
        deltas = report.get("deltas") or {}
        changed = [
            f"{escape(_name(uid))}: {value.get('coins', 0):+d} 🪙, o'yin {value.get('games_played', 0):+d}, g'alaba {value.get('wins', 0):+d}"
            for uid, value in deltas.items()
            if any(value.get(key, 0) for key in ("coins", "games_played", "wins"))
        ]
        if changed:
            lines.append("📊 " + "; ".join(changed[:4]))
    return "\n".join(lines)
