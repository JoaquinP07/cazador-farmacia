"""Resumen de ofertas del momento: los productos con más descuento publicado ahora mismo.

Es distinto a los avisos normales. Los avisos ("Posible error de precio") saltan cuando el precio de un
producto BAJA DE GOLPE respecto a lo que venía costando. Este resumen, en cambio, mira el descuento que la
tienda ya muestra hoy (precio actual contra precio de lista), aunque lleve días así.

Uso:  python -m cazador --resumen
"""
from __future__ import annotations

import html
import traceback
from concurrent.futures import ThreadPoolExecutor

from . import telegram
from .nucleo import Producto, fmt
from .tiendas import TIENDAS

TOP = 25  # cuántos productos mostrar
DESCUENTO_MINIMO = 0.30  # no se muestra nada con menos descuento que esto
MAX_POR_TIENDA = 5  # para que una sola tienda no ocupe todo el resumen
PRECIO_MINIMO = {"UYU": 300.0, "USD": 8.0}  # descartar productos baratos con descuentos poco útiles
LIMITE_MENSAJE = 3800  # Telegram corta a los 4096 caracteres

INTRO = (
    "🏷️ <b>OFERTAS DEL MOMENTO</b> — <i>no son errores de precio</i>\n"
    "Son los productos con <b>más descuento publicado ahora mismo</b> (precio actual contra el precio de "
    "lista que muestra cada tienda). <b>No son errores de precio</b>: son rebajas que la tienda ya tiene "
    "puestas, algunas desde hace días.\n\n"
    "🚨 Los avisos de <b>«Posible error de precio»</b> son otra cosa: saltan solo cuando el precio de un "
    "producto <b>baja de golpe</b> respecto a lo que venía costando.\n\n"
    "Ojo: el descuento depende del precio de lista que declara la tienda, conviene mirar el precio real."
)


def descuento(p: Producto) -> float:
    return 1 - p.precio / p.precio_lista if p.precio_lista else 0.0


def elegir(productos: list[Producto], top: int = TOP) -> list[Producto]:
    """Los de mayor descuento, sin repetidos y con tope por tienda."""
    candidatos = [
        p
        for p in productos
        if p.disponible
        and p.precio > 0
        and p.precio_lista
        and p.precio_lista > p.precio
        and p.precio >= PRECIO_MINIMO.get(p.moneda, 0)
        and descuento(p) >= DESCUENTO_MINIMO
    ]
    candidatos.sort(key=descuento, reverse=True)
    elegidos, vistos, por_tienda = [], set(), {}
    for p in candidatos:
        clave = (p.tienda, " ".join(p.nombre.lower().split()))
        if clave in vistos or por_tienda.get(p.tienda, 0) >= MAX_POR_TIENDA:
            continue
        vistos.add(clave)
        por_tienda[p.tienda] = por_tienda.get(p.tienda, 0) + 1
        elegidos.append(p)
        if len(elegidos) >= top:
            break
    return elegidos


def linea(n: int, p: Producto) -> str:
    return (
        f"🏷️ {n}. <b>{html.escape(p.tienda)}</b> — {html.escape(p.nombre[:90])}\n"
        f"   <b>{fmt(p.precio, p.moneda)}</b> · {descuento(p):.0%} menos que su precio de lista "
        f"({fmt(p.precio_lista, p.moneda)})\n"
        f'   <a href="{html.escape(p.url, quote=True)}">Ver producto</a>'
    )


def mensajes(elegidos: list[Producto]) -> list[str]:
    """Arma el texto y lo parte en mensajes que entren en Telegram."""
    if not elegidos:
        return [INTRO + "\n\nAhora mismo no hay productos con 30% de descuento o más."]
    bloques, actual = [], INTRO
    for n, p in enumerate(elegidos, 1):
        texto = linea(n, p)
        if len(actual) + len(texto) + 2 > LIMITE_MENSAJE:
            bloques.append(actual)
            actual = ""
        actual = f"{actual}\n\n{texto}" if actual else texto
    bloques.append(actual)
    return bloques


def correr() -> int:
    def leer(item):
        nombre, leer_tienda = item
        try:
            return nombre, leer_tienda()
        except Exception:  # una tienda caída no frena a las demás
            traceback.print_exc()
            return nombre, None

    with ThreadPoolExecutor(max_workers=8) as ex:
        lecturas = list(ex.map(leer, TIENDAS.items()))

    todos: list[Producto] = []
    for nombre, prods in lecturas:
        print(f"{nombre}: {'error' if prods is None else str(len(prods)) + ' productos'}")
        todos += prods or []

    elegidos = elegir(todos)
    for p in elegidos:
        print(f"{descuento(p):.0%}", p.tienda, p.nombre, fmt(p.precio, p.moneda))
    ok = all([telegram.enviar(m) for m in mensajes(elegidos)])
    print("Resumen enviado" if ok else f"No se pudo enviar: {telegram.ULTIMO_ERROR}")
    return 0 if ok else 1
