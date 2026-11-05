"""Envío de avisos por Telegram."""
from __future__ import annotations

import html
import os

import requests

ULTIMO_ERROR = ""

from .nucleo import Producto, fmt


def enviar(texto: str) -> bool:
    global ULTIMO_ERROR
    token = (os.environ.get("TELEGRAM_TOKEN") or "").strip()
    chat = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat:
        ULTIMO_ERROR = "faltan TELEGRAM_TOKEN / TELEGRAM_CHAT_ID"
        print("[telegram] " + ULTIMO_ERROR + "; mensaje no enviado:\n" + texto)
        return False
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat,
            "text": texto,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        },
        timeout=20,
    )
    if not r.ok:
        ULTIMO_ERROR = f"{r.status_code} {r.text[:300]}"
        print("[telegram] error", ULTIMO_ERROR)
    return r.ok


def aviso(p: Producto, motivo: str) -> str:
    return (
        f"🚨 <b>Posible error de precio</b> — {html.escape(p.tienda)}\n"
        f"{html.escape(p.nombre)}\n"
        f"<b>{fmt(p.precio, p.moneda)}</b> · {html.escape(motivo)}\n"
        f'<a href="{html.escape(p.url, quote=True)}">Ver producto</a>'
    )


def diagnostico() -> dict:
    """Pistas sobre por qué falla el envío, sin exponer los valores de los secretos."""
    token = (os.environ.get("TELEGRAM_TOKEN") or "").strip()
    crudo = os.environ.get("TELEGRAM_CHAT_ID") or ""
    chat = crudo.strip()
    info = {
        "chat_id_tiene_espacios": crudo != chat,
        "chat_id_es_numero": chat.lstrip("-").isdigit(),
        "chat_id_largo": len(chat),
    }
    try:
        yo = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=20).json()
        info["bot"] = (yo.get("result") or {}).get("username")
        up = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=20).json()
        chats = {str((u.get("message") or {}).get("chat", {}).get("id")) for u in up.get("result", [])}
        chats.discard("None")
        info["personas_que_le_escribieron_al_bot"] = len(chats)
        info["tu_chat_id_esta_entre_ellas"] = chat in chats
        info["el_numero_es_el_del_bot"] = bool(token) and chat == token.split(":")[0]
    except Exception as e:  # noqa: BLE001
        info["error"] = repr(e)
    return info
