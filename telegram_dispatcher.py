import asyncio
from send_telegram import send_pending_photos_once
from telegram_cache import reset_inflight


async def telegram_dispatcher_loop(stop_event=None) -> None:
    print("[DISPATCHER] Iniciando loop principal")

    # 🔥 proteção caso stop_event venha None
    if stop_event is None:
        class Dummy:
            def is_set(self):
                return False
        stop_event = Dummy()

    # Reseta itens in_flight de runs anteriores
    try:
        reset_inflight()
    except Exception:
        pass

    while not stop_event.is_set():
        try:
            sent, _ = send_pending_photos_once(max_items=5)

            # Se nada foi enviado, aguarda um pouco
            if sent == 0:
                await asyncio.sleep(5)

        except Exception as e:
            print(f"[DISPATCHER] Erro no loop: {e}")
            await asyncio.sleep(5)