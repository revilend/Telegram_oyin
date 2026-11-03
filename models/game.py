"""«Bunker» o'yini holat modellari (Pydantic v2)."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class CardType(str, Enum):
    """O'yin kartasi turlari."""

    CATASTROPHE = "catastrophe"
    PROFESSION = "profession"
    BIOLOGY = "biology"
    HEALTH = "health"
    HOBBY = "hobby"
    LUGGAGE = "luggage"
    FACT = "fact"
    SPECIAL = "special"


class RoomStatus(str, Enum):
    """Xona holatlari."""

    LOBBY = "LOBBY"
    PLAYING = "PLAYING"
    VOTING = "VOTING"
    SHIELD_OFFER = "SHIELD_OFFER"
    FINISHED = "FINISHED"


class PlayerCard(BaseModel):
    """Bitta ochiq yoki yashirin karta."""

    type: CardType
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=1000)
    is_revealed: bool = False

    @field_validator("title", "description")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Karta matni bo'sh bo'lishi mumkin emas")
        return value


class Player(BaseModel):
    """Xonadagi bitta o'yinchi va uning personaj kartalari."""

    user_id: int
    username: str = ""
    full_name: str = ""
    is_alive: bool = True
    is_host: bool = False
    cards: dict[str, PlayerCard] = Field(default_factory=dict)
    votes_against: int = Field(default=0, ge=0)
    shield_used: bool = False
    double_vote: bool = False

    @field_validator("cards")
    @classmethod
    def _validate_cards(cls, cards: dict[str, PlayerCard]) -> dict[str, PlayerCard]:
        valid_types = {card_type.value for card_type in CardType}
        for key, card in cards.items():
            if key not in valid_types:
                raise ValueError(f"Noma'lum karta kaliti: {key!r}")
            if key != card.type.value:
                raise ValueError(
                    f"Karta kaliti {key!r} uning turi {card.type.value!r} bilan mos emas"
                )
        return cards

    @field_validator("username", "full_name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        return value.strip()

    def get_card(self, card_type: CardType | str) -> PlayerCard | None:
        """Kalit bo'yicha kartani qaytaradi."""
        key = card_type.value if isinstance(card_type, CardType) else card_type
        return self.cards.get(key)

    def add_card(self, card: PlayerCard) -> None:
        """Kartani qo'shadi yoki shu turdagi kartani almashtiradi."""
        self.cards[card.type.value] = card

    def reveal_card(self, card_type: CardType | str) -> bool:
        """Kartani ochadi. Karta topilmasa ``False`` qaytaradi."""
        card = self.get_card(card_type)
        if card is None:
            return False
        card.is_revealed = True
        return True

    def revealed_cards(self) -> dict[str, PlayerCard]:
        """Faqat ochilgan kartalarni qaytaradi."""
        return {key: card for key, card in self.cards.items() if card.is_revealed}

    def eliminate(self) -> None:
        """O'yinchini o'lik deb belgilaydi."""
        self.is_alive = False


class ShieldOffer(BaseModel):
    """Haydalishdan oldin o'yinchiga beriladigan qalqon taklifi."""

    user_id: int
    counts: dict[int, int] = Field(default_factory=dict)

    @field_validator("counts")
    @classmethod
    def _validate_counts(cls, counts: dict[int, int]) -> dict[int, int]:
        if any(count < 0 for count in counts.values()):
            raise ValueError("Ovozlar soni manfiy bo'lishi mumkin emas")
        return counts


class GameRoom(BaseModel):
    """Bunker xonasining to'liq holati."""

    room_id: str = Field(min_length=1, max_length=64)
    code: str = Field(min_length=3, max_length=12)
    host_id: int
    status: RoomStatus = RoomStatus.LOBBY
    max_players: int = Field(default=12, ge=2, le=20)
    bunker_capacity: int = Field(default=6, ge=1, le=20)
    current_round: int = Field(default=0, ge=0)
    catastrophe: dict[str, Any] = Field(default_factory=dict)
    players: dict[int, Player] = Field(default_factory=dict)
    eliminated_players: list[int] = Field(default_factory=list)
    vote_weights: dict[int, int] = Field(default_factory=dict)
    pending_shield: ShieldOffer | None = None

    @field_validator("code")
    @classmethod
    def _normalize_code(cls, value: str) -> str:
        code = value.strip().upper()
        if not code.isalnum():
            raise ValueError("Xona kodi faqat harf va raqamlardan iborat bo'lishi kerak")
        return code

    @field_validator("status", mode="before")
    @classmethod
    def _normalize_status(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @field_validator("players")
    @classmethod
    def _validate_players(cls, players: dict[int, Player]) -> dict[int, Player]:
        for key, player in players.items():
            if key != player.user_id:
                raise ValueError(
                    f"O'yinchi kaliti {key!r} uning user_id {player.user_id!r} bilan mos emas"
                )
        return players

    @model_validator(mode="after")
    def _validate_room(self) -> "GameRoom":
        if self.bunker_capacity > self.max_players:
            raise ValueError("Bunker sig'imi maksimal o'yinchilar sonidan katta bo'lmasligi kerak")
        unknown = set(self.eliminated_players) - set(self.players)
        if unknown:
            raise ValueError(f"Haydalganlar ro'yxatida noma'lum o'yinchilar bor: {sorted(unknown)}")
        eliminated = set(self.eliminated_players)
        for user_id, player in self.players.items():
            if user_id in eliminated and player.is_alive:
                raise ValueError(
                    f"Haydalgan o'yinchi {user_id} tirik deb belgilangan"
                )
            if user_id not in eliminated and not player.is_alive:
                raise ValueError(
                    f"Tirik bo'lmagan o'yinchi {user_id} haydalganlar ro'yxatida yo'q"
                )
        if self.pending_shield is not None:
            candidate = self.players.get(self.pending_shield.user_id)
            if candidate is None:
                raise ValueError("Qalqon taklifi noma'lum o'yinchiga berilgan")
            if not candidate.is_alive:
                raise ValueError("Haydalgan o'yinchiga qalqon taklif qilinmaydi")
        unknown_voters = set(self.vote_weights) - set(self.players)
        if unknown_voters:
            raise ValueError(
                f"Ovoz og'irligida noma'lum o'yinchilar bor: {sorted(unknown_voters)}"
            )
        return self

    @property
    def alive_players(self) -> list[Player]:
        """Tirik o'yinchilar ro'yxati."""
        return [player for player in self.players.values() if player.is_alive]

    @property
    def free_slots(self) -> int:
        """Xonadagi bo'sh joylar soni."""
        return max(0, self.max_players - len(self.players))

    @property
    def is_full(self) -> bool:
        """Xona to'lganini bildiradi."""
        return len(self.players) >= self.max_players

    def get_player(self, user_id: int) -> Player | None:
        """user_id bo'yicha o'yinchini qaytaradi."""
        return self.players.get(user_id)

    def add_player(self, player: Player) -> None:
        """Yangi o'yinchini qo'shadi."""
        if self.status != RoomStatus.LOBBY:
            raise ValueError("Faqat LOBBY holatidagi xonaga o'yinchi qo'shiladi")
        if self.is_full:
            raise ValueError("Xona to'lgan")
        if player.user_id in self.players:
            raise ValueError(f"O'yinchi {player.user_id} allaqachon xonada")
        self.players[player.user_id] = player

    def eliminate_player(self, user_id: int) -> Player:
        """O'yinchini haydaydi va holatni yangilaydi."""
        player = self.players.get(user_id)
        if player is None:
            raise ValueError(f"O'yinchi {user_id} topilmadi")
        if not player.is_alive:
            raise ValueError(f"O'yinchi {user_id} allaqachon haydalgan")
        player.eliminate()
        if user_id not in self.eliminated_players:
            self.eliminated_players.append(user_id)
        return player
