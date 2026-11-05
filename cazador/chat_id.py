"""Muestra los grupos y chats donde el bot recibió mensajes, para saber el número (TELEGRAM_CHAT_ID).

Uso:  python -m cazador.chat_id
Antes hay que agregar el bot al grupo y escribir un mensaje ahí (Telegram guarda los mensajes ~24 h).
Solo imprime el nombre y el número de cada chat; nunca el token.
"""
from __future__ import annotations

import os
import sys

import requests


def main() -> int:
    token = (os.environ.get("TELEGRAM_TOKEN") or "").strip()
    if not token:
        print("Falta el secreto TELEGRAM_TOKEN en el repositorio.")
        return 1
    yo = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=20).json()
    if not yo.get("ok"):
        print("Telegram no aceptó el token (revisá que esté bien copiado).")
        return 1
    print("Bot:", (yo.get("result") or {}).get("username"))
    wh = requests.get(f"https://api.telegram.org/bot{token}/getWebhookInfo", timeout=20).json().get("result") or {}
    print("Webhook configurado:", bool(wh.get("url")))
    up = requests.get(
        f"https://api.telegram.org/bot{token}/getUpdates",
        params={"allowed_updates": '["message","my_chat_member","channel_post","edited_message"]'},
        timeout=20,
    ).json()
    print("Mensajes pendientes que ve el bot:", len(up.get("result", [])))
    chats: dict[int, str] = {}
    for u in up.get("result", []):
        for clave in ("message", "my_chat_member", "channel_post", "edited_message"):
            c = (u.get(clave) or {}).get("chat")
            if c:
                chats[c["id"]] = f'{c.get("type")}: {c.get("title") or c.get("username") or c.get("first_name")}'
    if not chats:
        print("El bot todavía no vio ningún chat. Agregalo al grupo, escribí un mensaje ahí y corré esto de nuevo.")
        return 1
    for cid, desc in chats.items():
        print(f"CHAT_ID {cid}  ({desc})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
