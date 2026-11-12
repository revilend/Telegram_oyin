"""Bunker, Mafiya, Josus, Alias, Bomba endpointlari va WebSocket."""

from __future__ import annotations

from fastapi import APIRouter

from api.deps import *  # noqa: F401,F403 - umumiy yordamchi va sxemalar

router = APIRouter()


@router.post("/api/mafia/{code}/join")
async def join_mafia_lobby(
    code: str,
    payload: JoinRequest,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Global qidiruvdan Mafiya lobby'siga qo'shilish."""
    resolved_id = resolve_room_user_id(user, payload.user_id)
    full_name = (
        (user.full_name if user is not None else "") or payload.full_name or ""
    ).strip()
    username = (
        (user.username if user is not None else "") or payload.username or ""
    ).strip()
    if not full_name:
        raise HTTPException(status_code=400, detail="full_name majburiy")
    economy = get_economy()
    economy.ensure_user(resolved_id, username, full_name)
    try:
        player = mafia_bot.get_default_manager().join(
            code, resolved_id, full_name, username
        )
        game = mafia_bot.get_default_manager().get_game(code)
    except mafia_bot.MafiaGameError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    metrics.user(resolved_id)
    await chat_hub.system(code, f"{full_name} xonaga qo'shildi")
    return {"ok": True, "me": mafia_me_payload(game, player, economy=economy)}


@router.post("/api/mafia/{code}/start")
async def start_mafia_game(
    code: str,
    payload: UserRequest,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Mini App'dan xona egasi Mafiya o'yinini boshlaydi."""
    resolved_id = resolve_room_user_id(user, payload.user_id)
    try:
        mafia_bot.get_default_manager().start_game(code, resolved_id)
    except mafia_bot.MafiaGameError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@router.get("/api/mafia/{code}/me")
async def get_mafia_role(
    code: str,
    user_id: int | None = None,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Guruh Mafiya o'yinidagi o'yinchining roli va karta ma'lumoti."""
    resolved_id = resolve_room_user_id(user, user_id)
    game = _mafia_game_for(code)
    player = game.room.players.get(resolved_id)
    if player is None:
        raise HTTPException(
            status_code=404, detail="Siz bu Mafiya xonasida emassiz"
        )
    return {"me": mafia_me_payload(game, player)}


@router.post("/api/mafia/{code}/booster")
async def buy_mafia_booster(
    code: str,
    payload: MafiaBoosterRequest,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Mafiya boosterini sotib oladi (Kevlar, Reroll yoki 2x ovoz)."""
    resolved_id = resolve_room_user_id(user, payload.user_id)
    game = _mafia_game_for(code)
    player = game.room.players.get(resolved_id)
    if player is None:
        raise HTTPException(
            status_code=404, detail="Siz bu Mafiya xonasida emassiz"
        )

    economy = get_economy()
    try:
        purchase = purchase_booster(
            economy,
            game.room,
            game.code,
            resolved_id,
            payload.booster,
        )
    except MafiaBoosterError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    mafia_bot.get_default_manager().save(game)

    return {
        "ok": True,
        "booster": purchase.booster.key,
        "message": purchase.message,
        "coins": purchase.account.coins,
        "me": mafia_me_payload(game, player, economy=economy),
    }


@router.get("/api/mafia/{code}/state")
async def get_mafia_public_state(
    code: str,
    user_id: int | None = None,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Mafiya Mini App uchun maxfiy rollarsiz umumiy holat."""
    resolved_id = resolve_room_user_id(user, user_id)
    game = _mafia_game_for(code)
    room = game.room
    viewer = room.players.get(resolved_id)
    if viewer is None:
        raise HTTPException(status_code=403, detail="Siz bu Mafiya xonasida emassiz")

    night_options = ()
    if viewer.role is not None:
        night_options = NIGHT_OPTIONS_BY_ROLE.get(
            viewer.role,
            (NIGHT_ACTION_BY_ROLE[viewer.role],)
            if viewer.role in NIGHT_ACTION_BY_ROLE
            else (),
        )
    action_labels = {
        "kill": "Nishonni tanlash",
        "heal": "Davolash",
        "protect": "Himoya qilish",
        "block": "Mehmonga borish (harakatni muzlatish)",
        "snipe": "Nishonga olish",
        "shoot": "O'q uzish (o'ldirish)",
        "investigate": "O'yinchini tekshirish",
        "don_search": "Komissarni qidirish",
        "frame": "Tekshiruvdan yashirish",
        "witch_kill": "O'ldirish",
        "witch_heal": "Tiriltirish",
        "silence": "Ovozini bloklash",
        "copy": "Rolini egallash",
    }
    report = room.last_report
    private_result = None
    if report is not None:
        private_result = report.sheriff_results.get(resolved_id)
        if private_result is None:
            private_result = report.don_results.get(resolved_id)
    return {
        "state": {
            "code": game.code,
            "phase": room.phase.value,
            "round": room.round,
            "is_host": resolved_id == game.host_id,
            "is_alive": viewer.is_alive,
            "players": [
                {
                    "user_id": player.user_id,
                    "name": room.display_name(player),
                    "is_alive": player.is_alive,
                    "is_me": player.user_id == resolved_id,
                }
                for player in room.players.values()
            ],
            "night_actions": [
                {"key": action.value, "label": action_labels.get(action.value, action.value)}
                for action in night_options
            ],
            "has_submitted_night_action": resolved_id in room.night_actions,
            "has_voted": resolved_id in room.votes,
            "my_vote_target": room.votes.get(resolved_id),
            "is_silenced": resolved_id in room.silenced,
            "vote_counts": [
                {"user_id": player.user_id, "count": room.vote_counts().get(player.user_id, 0)}
                for player in room.alive_players
            ],
            "can_begin_voting": (
                resolved_id == game.host_id
                and room.phase is GamePhase.DAY_REPORT
            ),
            "can_tally": (
                resolved_id == game.host_id
                and room.phase is GamePhase.VOTING
            ),
            "private_result": private_result,
            "phase_deadline": game.phase_deadline,
            "phase_seconds_left": game.phase_seconds_left(),
            "winner": room.winner.value if room.winner is not None else None,
        }
    }


@router.post("/api/mafia/{code}/night-action")
async def submit_mafia_night_action(
    code: str,
    payload: MafiaNightActionRequest,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Tungi harakatni dvigatel qoidalari orqali yuboradi."""
    resolved_id = resolve_user_id(user, payload.user_id)
    game = _mafia_game_for(code)
    if resolved_id not in game.room.players:
        raise HTTPException(status_code=403, detail="Siz bu Mafiya xonasida emassiz")
    try:
        game.room.submit_night_action(
            resolved_id, payload.target_id, kind=payload.kind
        )
    except MafiaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    mafia_bot.get_default_manager().save(game)
    return {"ok": True}


@router.post("/api/mafia/{code}/begin-voting")
async def begin_mafia_voting(
    code: str,
    user_id: int | None = None,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Tonggi hisobotdan keyin ovoz berishni xona egasi boshlaydi."""
    resolved_id = resolve_room_user_id(user, user_id)
    game = _mafia_game_for(code)
    if resolved_id != game.host_id:
        raise HTTPException(status_code=403, detail="Ovoz berishni faqat xona egasi boshlaydi")
    try:
        game.room.begin_voting()
    except MafiaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    game.start_phase_timer()
    mafia_bot.get_default_manager().save(game)
    return {"ok": True}


@router.post("/api/mafia/{code}/vote")
async def cast_mafia_vote(
    code: str,
    payload: MafiaVoteRequest,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Kunduzgi ovozni yuboradi; qoidalarni dvigatel tekshiradi."""
    resolved_id = resolve_room_user_id(user, payload.user_id)
    game = _mafia_game_for(code)
    try:
        game.room.cast_vote(resolved_id, payload.target_id)
    except MafiaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    mafia_bot.get_default_manager().save(game)
    return {"ok": True}


@router.post("/api/mafia/{code}/tally")
async def tally_mafia_votes(
    code: str,
    payload: MafiaTallyRequest,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Ovozlarni xona egasi sanaydi va dvigatel keyingi fazani boshlaydi."""
    resolved_id = resolve_room_user_id(user, payload.user_id)
    game = _mafia_game_for(code)
    if resolved_id != game.host_id:
        raise HTTPException(status_code=403, detail="Ovozlarni faqat xona egasi sanaydi")
    try:
        eliminated_id = game.room.tally_votes()
        winner = resolve_day_vote(
            game.room,
            eliminated_id,
            kamikaze_target_id=payload.kamikaze_target_id,
        )
    except MafiaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if game.room.phase is GamePhase.FINISHED:
        game.clear_phase_timer()
        if _runtime_bot is not None:
            await mafia_bot.announce_finish(_runtime_bot, game)
    else:
        game.start_phase_timer()
        if _runtime_bot is not None:
            if eliminated_id is not None:
                await mafia_bot.announce_execution(
                    _runtime_bot, game, game.room.players[eliminated_id]
                )
            await mafia_bot.announce_night(_runtime_bot, game)
    mafia_bot.get_default_manager().save(game)

    return {
        "ok": True,
        "eliminated_id": eliminated_id,
        "winner": winner.value if winner is not None else None,
    }


@router.get("/api/room/{code}")
async def get_room(
    code: str,
    user_id: int = 0,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Xonaning ochiq holati: falokat, raund, ochilgan kartalar."""
    room = manager().get_room(code)
    viewer_id = user.id if user is not None else user_id
    return {"state": public_state(room, viewer_id=viewer_id)}


@router.get("/api/room/{code}/me")
async def get_my_cards(
    code: str,
    user_id: int | None = None,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """O'yinchining shaxsiy yashirin kartalari."""
    resolved_id = resolve_room_user_id(user, user_id)
    room = manager().get_room(code)
    return {"me": private_state(room, resolved_id)}


@router.post("/api/room/{code}/action")
async def room_action(
    code: str,
    payload: ActionRequest,
    user: TelegramUser | None = Depends(telegram_user),
) -> dict[str, Any]:
    """Umumiy o'yin harakatlari: qo'shilish, boshlash, ochish, ovoz, sanash."""
    actor_id = resolve_room_user_id(user, payload.user_id)
    full_name = (
        (user.full_name if user is not None else "")
        or payload.full_name
        or ""
    ).strip()
    username = (
        (user.username if user is not None else "")
        or payload.username
        or ""
    ).strip()

    game_manager = manager()
    result: dict[str, Any] | None = None

    if payload.action == "join":
        if not full_name:
            raise HTTPException(status_code=400, detail="full_name majburiy")
        get_economy().ensure_user(actor_id, username, full_name)
        already_inside = actor_id in game_manager.get_room(code).players
        game_manager.join_room(code, actor_id, full_name, username)
        if not already_inside:
            await chat_hub.system(code, f"{full_name} xonaga qo'shildi")
    elif payload.action == "start":
        room = game_manager.get_room(code)
        if room.host_id != actor_id:
            raise HTTPException(
                status_code=403,
                detail="O'yinni faqat xona egasi boshlashi mumkin",
            )
        game_manager.start_game(code)
        await chat_hub.system(code, "O'yin boshlandi. Omad!")
    elif payload.action == "reveal":
        if not payload.card_type:
            raise HTTPException(status_code=400, detail="card_type majburiy")
        game_manager.reveal_card(code, actor_id, payload.card_type)
    elif payload.action == "vote":
        if payload.target_id is None:
            raise HTTPException(status_code=400, detail="target_id majburiy")
        game_manager.cast_vote(code, actor_id, payload.target_id)
    elif payload.action == "tally":
        room = game_manager.get_room(code)
        if room.host_id != actor_id:
            raise HTTPException(
                status_code=403,
                detail="Ovozlarni faqat xona egasi sanaydi",
            )
        eliminated = game_manager.tally_votes(code)
        current = game_manager.get_room(code)
        if eliminated is not None:
            await chat_hub.system(
                code, f"{eliminated.full_name} o'yindan chiqarildi"
            )
        result = {
            "eliminated": (
                {
                    "user_id": eliminated.user_id,
                    "full_name": eliminated.full_name,
                }
                if eliminated is not None
                else None
            ),
            "tie": eliminated is None and current.pending_shield is None,
            "shield_offer": (
                current.pending_shield.model_dump(mode="json")
                if current.pending_shield is not None
                else None
            ),
        }
        _schedule_shield_offer(current)
    elif payload.action == "booster":
        if not payload.booster:
            raise HTTPException(status_code=400, detail="booster majburiy")
        try:
            purchase = buy_booster(
                game_manager,
                get_economy(),
                code,
                actor_id,
                payload.booster,
                payload.card_type,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        result = {
            "booster": purchase.booster.key,
            "price": purchase.booster.price,
            "coins": purchase.account_coins,
            "eliminated": (
                {
                    "user_id": purchase.eliminated.user_id,
                    "full_name": purchase.eliminated.full_name,
                }
                if purchase.eliminated is not None
                else None
            ),
            "card": _card_payload(purchase.card) if purchase.card is not None else None,
        }
    elif payload.action == "shield_decline":
        room = game_manager.get_room(code)
        offer = room.pending_shield
        if offer is None or offer.user_id != actor_id:
            raise HTTPException(
                status_code=400,
                detail="Sizda faol qalqon taklifi yo'q",
            )
        _, eliminated = decline_shield(game_manager, code, actor_id)
        result = {
            "eliminated": {
                "user_id": eliminated.user_id,
                "full_name": eliminated.full_name,
            }
        }

    room = game_manager.get_room(code)
    _record_finished_room(room)
    state = public_state(room, viewer_id=actor_id)
    await hub.broadcast(code, {"type": "state", "state": state})
    return {
        "ok": True,
        "state": state,
        "me": private_state(room, actor_id),
        "result": result,
        "coins": get_economy().get_user(actor_id).coins,
    }


@router.websocket("/ws/{code}")
async def room_socket(
    websocket: WebSocket,
    code: str,
    user_id: int | None = None,
) -> None:
    """Xona uchun real-vaqt kanali: holat va jonli chat."""
    normalized = (code or "").strip().upper()
    bunker_room = _bunker_room_or_none(normalized)
    if bunker_room is None and _chat_access(normalized, 0) is None:
        await websocket.close(code=4404)
        return

    bunker_connected = bunker_room is not None
    if bunker_connected:
        await hub.connect(normalized, websocket)
    if user_id is not None:
        await chat_hub.connect(normalized, websocket, int(user_id))
    try:
        if bunker_connected:
            await websocket.send_json(
                {"type": "state", "state": public_state(bunker_room)}
            )
        while True:
            message = await websocket.receive_text()
            stripped = message.strip()
            if stripped == "ping":
                await websocket.send_json({"type": "pong"})
            elif stripped == "sync":
                current = _bunker_room_or_none(normalized)
                if current is not None:
                    await websocket.send_json(
                        {"type": "state", "state": public_state(current)}
                    )
            else:
                await _handle_socket_payload(
                    websocket, normalized, user_id, stripped
                )
    except WebSocketDisconnect:
        pass
    finally:
        await hub.disconnect(normalized, websocket)
        await chat_hub.disconnect(normalized, websocket)
