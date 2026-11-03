"""Booster sotib olish va qalqon qarorlari uchun yagona servis qatlami."""

from __future__ import annotations

from dataclasses import dataclass

from core.economy import EconomyStore, InsufficientCoinsError, get_economy
from engine.boosters import (
    DOUBLE_VOTE,
    REROLL,
    SHIELD,
    Booster,
    BoosterError,
    get_booster,
)
from engine.game_manager import CardNotFoundError, GameManager, InvalidGameStateError
from models.game import GameRoom, Player, PlayerCard, RoomStatus


@dataclass(frozen=True)
class BoosterResult:
    """Booster ishlatilgandan keyingi natija."""

    booster: Booster
    room: GameRoom
    account_coins: int
    eliminated: Player | None = None
    card: PlayerCard | None = None


def _validate_booster(
    manager: GameManager,
    economy: EconomyStore,
    room: GameRoom,
    user_id: int,
    booster: Booster,
    card_type: str | None,
) -> Player:
    player = room.get_player(user_id)
    if player is None:
        raise InvalidGameStateError("Siz bu xonada o'ynayotgan o'yinchi emassiz")
    if not player.is_alive:
        raise InvalidGameStateError("Haydalgan o'yinchi booster ishlata olmaydi")

    if booster.key == SHIELD.key:
        offer = room.pending_shield
        if room.status is not RoomStatus.SHIELD_OFFER or offer is None:
            raise InvalidGameStateError("Hozir qalqon taklifi faol emas")
        if offer.user_id != user_id:
            raise InvalidGameStateError("Bu qalqon taklifi sizga tegishli emas")
        if player.shield_used or economy.has_booster(room.code, user_id, SHIELD.key):
            raise InvalidGameStateError("Qalqondan bu xonada allaqachon foydalanilgan")
        return player

    if room.status not in (RoomStatus.PLAYING, RoomStatus.VOTING):
        raise InvalidGameStateError("Boosterni faqat o'yin davomida ishlatish mumkin")

    if booster.key == DOUBLE_VOTE.key:
        if player.double_vote:
            raise InvalidGameStateError("2 karra ovoz allaqachon faol")
        return player

    if booster.key == REROLL.key:
        if not card_type:
            raise ValueError("Almashtiriladigan karta turi ko'rsatilmagan")
        normalized = card_type.strip().lower()
        card = player.get_card(normalized)
        if card is None:
            raise CardNotFoundError(f"'{normalized}' kartasi mavjud emas")
        if card.is_revealed:
            raise InvalidGameStateError("Ochilgan kartani almashtirish mumkin emas")
        return player

    raise BoosterError(f"Noma'lum booster: {booster.key}")


def buy_booster(
    manager: GameManager,
    economy: EconomyStore,
    code: str,
    user_id: int,
    booster_key: str,
    card_type: str | None = None,
) -> BoosterResult:
    """Tanga yechib, boosterni o'yinda qo'llaydi.

    Tanga yechilgandan keyin o'yin amali xato bersa, pul avtomatik qaytariladi.
    """
    booster = get_booster(booster_key)
    room = manager.get_room(code)
    _validate_booster(manager, economy, room, int(user_id), booster, card_type)

    account = economy.ensure_user(int(user_id))
    if account.coins < booster.price:
        raise InsufficientCoinsError(
            f"Balansda yetarli tanga yo'q: {account.coins} ta bor, "
            f"{booster.price} ta kerak"
        )

    economy.spend_coins(int(user_id), booster.price)
    eliminated: Player | None = None
    card: PlayerCard | None = None
    try:
        if booster.key == SHIELD.key:
            eliminated = manager.activate_shield(code, int(user_id))
        elif booster.key == DOUBLE_VOTE.key:
            manager.use_double_vote(code, int(user_id))
        else:
            card = manager.reroll_card(code, int(user_id), str(card_type))
    except Exception:
        economy.add_coins(int(user_id), booster.price)
        raise

    economy.record_booster(room.code, int(user_id), booster.key)
    if room.status is RoomStatus.FINISHED:
        economy.record_finished_game(
            room.code,
            room.players.keys(),
            [player.user_id for player in room.alive_players],
        )
    return BoosterResult(
        booster=booster,
        room=room,
        account_coins=economy.get_user(int(user_id)).coins,
        eliminated=eliminated,
        card=card,
    )


def decline_shield(
    manager: GameManager,
    code: str,
    user_id: int,
) -> tuple[GameRoom, Player]:
    """Qalqon taklifini rad etib, o'yinchini haydaydi."""
    player = manager.decline_shield(code, int(user_id))
    room = manager.get_room(code)
    if room.status is RoomStatus.FINISHED:
        get_economy().record_finished_game(
            room.code,
            room.players.keys(),
            [item.user_id for item in room.alive_players],
        )
    return room, player
