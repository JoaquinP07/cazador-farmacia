"""Comandos por Telegram: /buscar, /agregar, /quitar, /reanudar, /lista, /ayuda.

El bot revisa los mensajes nuevos mientras espera entre una vuelta y la siguiente, así contesta en
pocos segundos. Solo hace caso al chat configurado en TELEGRAM_CHAT_ID; cualquier otro se ignora.
Las tiendas agregadas y pausadas se guardan en estado/control.json (junto al historial).
"""
from __future__ import annotations

import html
import json
import os
import pathlib
import re
import statistics
import time
import unicodedata
from urllib.parse import urlparse

import requests

from . import telegram
from .nucleo import Historial, fmt
from . import tiendas as _T
from .tiendas import TIENDAS, _get, fenicio

shopify = getattr(_T, "shopify", None)
woocommerce = getattr(_T, "woocommerce", None)

CONTROL = pathlib.Path("estado/control.json")
TASA_USD = 40.0  # para comparar precios en pesos con precios en dólares
MAX_RESULTADOS = 10
FRESCO = 3 * 3600  # solo productos vistos en las últimas 3 horas (si no, la tienda dejó de leerse)
MODOS = {"barato", "oferta", "historico"}
EXIGE_CATEGORIAS = True  # True en los bots que no deben leer el catálogo entero de una tienda Fenicio
NOTA_AYUDA = "Sin medicamentos. En el grupo, escribí el comando con el nombre del bot (ej: /lista@cazador_farmacia_joaquin_bot)."

AYUDA = (
    "🤖 <b>Comandos</b>\n"
    "<code>/buscar tv 55</code> → las 10 más baratas\n"
    "<code>/buscar tv 55 oferta</code> → las que más bajaron de precio\n"
    "<code>/buscar tv 55 historico</code> → las que están en su precio más bajo registrado\n"
    "<code>/agregar https://tienda.com.uy</code> → suma una tienda (si sé leerla). Con "
    "<code>cats=perfumeria,maquillaje</code> al final, solo esas secciones\n"
    "<code>/quitar nombre</code> → saca una tienda (o la pausa); <code>/reanudar nombre</code> la vuelve a activar\n"
    "<code>/lista</code> → tiendas que se revisan\n\n"
    + NOTA_AYUDA
)


# ------------------------------------------------------------------ estado de control
def cargar_control() -> dict:
    try:
        c = json.loads(CONTROL.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        c = {}
    c.setdefault("extra", [])
    c.setdefault("pausadas", [])
    c.setdefault("offset", 0)
    return c


def guardar_control(c: dict) -> None:
    CONTROL.parent.mkdir(parents=True, exist_ok=True)
    CONTROL.write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")


def _lector(extra: dict):
    nombre, base, tipo = extra["nombre"], extra["base"], extra["tipo"]
    if tipo == "fenicio":
        cats = extra.get("cats") or ["catalogo"]
        return lambda: fenicio(nombre, base, cats, max_paginas=400)
    if tipo == "shopify" and shopify:
        return lambda: shopify(nombre, base)
    if tipo == "woocommerce" and woocommerce:
        return lambda: woocommerce(nombre, base, max_paginas=60)
    raise ValueError(tipo)


def tiendas_activas() -> dict:
    """Las tiendas fijas del código, más las agregadas por Telegram, menos las pausadas."""
    c = cargar_control()
    pausadas = {x.casefold() for x in c["pausadas"]}
    todas = dict(TIENDAS)
    for e in c["extra"]:
        try:
            todas[e["nombre"]] = _lector(e)
        except (KeyError, ValueError):
            continue
    return {k: v for k, v in todas.items() if k.casefold() not in pausadas}


# ------------------------------------------------------------------ texto
def norm(txt: str) -> str:
    txt = unicodedata.normalize("NFKD", txt.lower())
    return "".join(ch for ch in txt if not unicodedata.combining(ch))


SINONIMOS = {
    "tv": ["tv", "televisor", "television", "smart tv"],
    "televisor": ["tv", "televisor", "television"],
    "celular": ["celular", "smartphone", "telefono", "iphone", "galaxy", "redmi", "poco"],
    "notebook": ["notebook", "laptop", "macbook", "portatil"],
    "heladera": ["heladera", "refrigerador", "freezer"],
    "lavarropas": ["lavarropas", "lavadora", "lavasecarropas"],
    "aire": ["aire acondicionado", "split", "inverter"],
}
ACCESORIOS: list[str] = []  # en este bot no se descartan accesorios


def _coincide(token: str, nombre: str) -> bool:
    if token.isdigit():
        return re.search(rf"(?<!\d){token}(?!\d)", nombre) is not None
    for alias in SINONIMOS.get(token, [token]):
        patron = rf"\b{re.escape(alias)}" + (r"\b" if len(alias) <= 3 else "")
        if re.search(patron, nombre):
            return True
    return False


def interpretar(texto: str) -> tuple[list[str], str]:
    palabras = [norm(w) for w in re.findall(r"[\w\"'.+-]+", texto)]
    palabras = [w.strip("\"'.") for w in palabras]
    palabras = [w for w in palabras if w]
    modo = "barato"
    if palabras and palabras[-1] in MODOS:
        modo = palabras.pop()
    return palabras, modo


def a_usd(precio: float, moneda: str) -> float:
    return precio if moneda == "USD" else precio / TASA_USD


# ------------------------------------------------------------------ búsqueda
def buscar(datos: dict, texto: str, ahora: float | None = None) -> str:
    tokens, modo = interpretar(texto)
    if not tokens:
        return "Escribí qué buscás, por ejemplo: <code>/buscar tv 55</code>"
    ahora = ahora or time.time()
    consulta = " ".join(tokens)
    candidatos = []
    for clave, reg in datos.items():
        precio, nombre = reg.get("p"), reg.get("n")
        if not precio or not nombre or not reg.get("d", True) or ahora - reg.get("t", 0) > FRESCO:
            continue
        n = norm(nombre)
        if not all(_coincide(t, n) for t in tokens):
            continue
        if any(re.search(rf"\b{re.escape(a.strip())}", n) and a.strip() not in consulta for a in ACCESORIOS):
            continue
        h = reg.get("h") or []
        previos = h[:-1] if h and h[-1] == precio else h
        previos = [x for x in previos if x > 0]
        med = statistics.median(previos) if len(previos) >= 2 else None
        lista = reg.get("l")
        extra = ""
        clave_orden = a_usd(precio, reg.get("m", "UYU"))
        if modo == "oferta":
            bajas = []
            if med and precio < med:
                bajas.append((1 - precio / med, f"bajó {1 - precio / med:.0%} (habitual {fmt(med, reg['m'])})"))
            if lista and lista > precio:
                bajas.append((1 - precio / lista, f"{1 - precio / lista:.0%} menos que el precio de lista"))
            if not bajas or max(bajas)[0] < 0.05:
                continue
            mejor = max(bajas)
            clave_orden, extra = -mejor[0], mejor[1]
        elif modo == "historico":
            if len(previos) < 2 or precio > min(previos) or precio >= med * 0.98:
                continue
            clave_orden = precio / med
            extra = f"mínimo registrado (antes {fmt(min(previos), reg['m'])})"
        candidatos.append((clave_orden, clave, reg, extra))
    candidatos.sort(key=lambda x: x[0])
    titulo = {"barato": "más baratas", "oferta": "con mayor baja", "historico": "en su precio más bajo registrado"}[modo]
    if not candidatos:
        return f"No encontré nada para <b>{html.escape(consulta)}</b> ({modo}). Probá con otras palabras."
    lineas = [f"🔎 <b>{html.escape(consulta)}</b> — las {min(MAX_RESULTADOS, len(candidatos))} {titulo} "
              f"(de {len(candidatos)} encontradas)\n"]
    vistos, n = set(), 0
    for _, clave, reg, extra in candidatos:
        k = (clave.split(":", 1)[0], norm(reg["n"]))
        if k in vistos:
            continue
        vistos.add(k)
        n += 1
        tienda = html.escape(clave.split(":", 1)[0])
        nombre = html.escape(reg["n"][:90])
        precio = fmt(reg["p"], reg.get("m", "UYU"))
        enlace = reg.get("u")
        titulo_item = f'<a href="{html.escape(enlace, quote=True)}">{nombre}</a>' if enlace else nombre
        lineas.append(f"{n}. <b>{precio}</b> · {tienda}\n{titulo_item}" + (f"\n<i>{html.escape(extra)}</i>" if extra else ""))
        if n >= MAX_RESULTADOS:
            break
    lineas.append("\nOjo: se ordena solo por precio; revisá marca, modelo y garantía.")
    return "\n".join(lineas)


# ------------------------------------------------------------------ agregar / quitar
def detectar(url: str) -> tuple[str, str] | None:
    """Devuelve (tipo, base) si reconoce la plataforma de la tienda."""
    if not re.match(r"^https?://", url):
        url = "https://" + url
    u = urlparse(url)
    if not u.netloc or "." not in u.netloc:
        return None
    base = f"{u.scheme}://{u.netloc}"
    try:
        r = _get(f"{base}/catalogo", params={"js": 1, "pag": 1})
        if r.status_code == 200 and "data-codProd" in r.text and 'data-total="' in r.text:
            return "fenicio", base
    except requests.RequestException:
        pass
    if shopify:
        try:
            r = _get(f"{base}/products.json", params={"limit": 1})
            if r.status_code == 200 and isinstance(r.json().get("products"), list):
                return "shopify", base
        except (requests.RequestException, ValueError):
            pass
    if woocommerce:
        try:
            r = _get(f"{base}/wp-json/wc/store/v1/products", params={"per_page": 1})
            if r.status_code == 200 and isinstance(r.json(), list):
                return "woocommerce", base
        except (requests.RequestException, ValueError):
            pass
    return None


def _nombre_de(base: str) -> str:
    host = urlparse(base).netloc.lower().removeprefix("www.")
    return host.split(".")[0].capitalize()


def agregar(arg: str) -> str:
    partes = [x for x in arg.split() if not x.lower().startswith("cats=")]
    cats = [x.strip("/ ") for a in arg.split() if a.lower().startswith("cats=") for x in a[5:].split(",") if x.strip("/ ")]
    if not partes:
        return "Escribí la dirección, por ejemplo: <code>/agregar https://nstore.com.uy</code>"
    c = cargar_control()
    hallada = detectar(partes[0])
    if not hallada:
        return ("No pude leer esa tienda automáticamente: no reconozco su plataforma "
                "(sé leer Fenicio" + (", Shopify" if shopify else "") + (" y WooCommerce" if woocommerce else "") + "). "
                "Mandásela a Claude y la armamos a mano.")
    tipo, base = hallada
    if tipo == "fenicio" and EXIGE_CATEGORIAS and not cats:
        return ("Es una tienda Fenicio. En este bot hay que elegir las secciones para no traer todo el catálogo: "
                f"<code>/agregar {html.escape(base)} cats=seccion1,seccion2</code>. "
                "Los nombres están en la dirección de cada sección (por ejemplo tienda.com.uy/<b>perfumeria</b>).")
    if any(e["base"] == base for e in c["extra"]):
        return f"Esa tienda ya está agregada ({html.escape(base)})."
    nombre = " ".join(partes[1:]) or _nombre_de(base)
    if nombre.casefold() in {k.casefold() for k in tiendas_activas()}:
        return f"Ya hay una tienda llamada <b>{html.escape(nombre)}</b>. Probá con otro nombre: <code>/agregar {html.escape(base)} OtroNombre</code>"
    extra = {"nombre": nombre, "base": base, "tipo": tipo}
    if cats and tipo == "fenicio":
        extra["cats"] = cats
    try:
        prods = _lector(extra)()
    except Exception as e:  # noqa: BLE001
        return f"Reconocí la plataforma ({tipo}) pero falló la lectura: {html.escape(repr(e)[:150])}"
    if not prods:
        return f"Reconocí la plataforma ({tipo}) pero no encontré productos con precio."
    c["extra"].append(extra)
    guardar_control(c)
    monedas = sorted({p.moneda for p in prods})
    return (f"✅ <b>{html.escape(nombre)}</b> agregada ({tipo}): {len(prods)} productos en {'/'.join(monedas)}.\n"
            "La primera vuelta solo aprende los precios; los avisos empiezan en la siguiente.")


def _buscar_tienda(nombre: str, nombres: list[str]) -> str | None:
    q = nombre.casefold().strip()
    exactas = [n for n in nombres if n.casefold() == q]
    if exactas:
        return exactas[0]
    parciales = [n for n in nombres if q and q in n.casefold()]
    return parciales[0] if len(parciales) == 1 else None


def quitar(arg: str) -> str:
    if not arg.strip():
        return "Escribí el nombre de la tienda, por ejemplo: <code>/quitar Nstore</code>"
    c = cargar_control()
    extras = [e["nombre"] for e in c["extra"]]
    n = _buscar_tienda(arg, extras)
    if n:
        c["extra"] = [e for e in c["extra"] if e["nombre"] != n]
        guardar_control(c)
        return f"🗑️ <b>{html.escape(n)}</b> quitada."
    n = _buscar_tienda(arg, list(TIENDAS))
    if n:
        if n not in c["pausadas"]:
            c["pausadas"].append(n)
            guardar_control(c)
        return f"⏸️ <b>{html.escape(n)}</b> pausada (es una tienda fija). Para volver: <code>/reanudar {html.escape(n)}</code>"
    return "No encontré esa tienda. Mirá los nombres con /lista."


def reanudar(arg: str) -> str:
    c = cargar_control()
    n = _buscar_tienda(arg, c["pausadas"])
    if not n:
        return "No hay ninguna tienda pausada con ese nombre."
    c["pausadas"].remove(n)
    guardar_control(c)
    return f"▶️ <b>{html.escape(n)}</b> reactivada."


def lista(datos: dict) -> str:
    c = cargar_control()
    cuentas: dict[str, int] = {}
    for clave in datos:
        t = clave.split(":", 1)[0]
        cuentas[t] = cuentas.get(t, 0) + 1
    extras = {e["nombre"] for e in c["extra"]}
    lineas = ["📋 <b>Tiendas que se revisan</b>"]
    for nombre in sorted(set(TIENDAS) | extras, key=str.casefold):
        marca = "⏸️ " if nombre in c["pausadas"] else "• "
        suma = " (agregada por Telegram)" if nombre in extras else ""
        lineas.append(f"{marca}{html.escape(nombre)}: {cuentas.get(nombre, 0):,}".replace(",", ".") + suma)
    return "\n".join(lineas)


# ------------------------------------------------------------------ Telegram
def _cargar_historial(ruta: pathlib.Path, cache: dict) -> dict:
    try:
        m = ruta.stat().st_mtime
    except OSError:
        return {}
    if cache.get("m") != m:
        cache["m"], cache["d"] = m, Historial(ruta).datos
    return cache["d"]


def responder(texto: str, ruta_historial: pathlib.Path, cache: dict) -> str | None:
    texto = (texto or "").strip()
    if not texto.startswith("/"):
        return None
    cmd, _, arg = texto.partition(" ")
    cmd = cmd.split("@", 1)[0].lower()
    try:
        if cmd in ("/ayuda", "/start", "/help"):
            return AYUDA
        if cmd == "/buscar":
            return buscar(_cargar_historial(ruta_historial, cache), arg)
        if cmd == "/agregar":
            return agregar(arg)
        if cmd == "/quitar":
            return quitar(arg)
        if cmd == "/reanudar":
            return reanudar(arg)
        if cmd == "/lista":
            return lista(_cargar_historial(ruta_historial, cache))
    except Exception as e:  # noqa: BLE001 - un comando roto no debe cortar el cazador
        return f"⚠️ Falló el comando: {html.escape(repr(e)[:200])}"
    return None


def atender(ruta_historial: pathlib.Path, espera: int = 0, cache: dict | None = None) -> int:
    """Lee los mensajes nuevos y contesta los comandos. Devuelve cuántos atendió."""
    token = (os.environ.get("TELEGRAM_TOKEN") or "").strip()
    chat = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat:
        return 0
    cache = cache if cache is not None else {}
    c = cargar_control()
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{token}/getUpdates",
            params={"offset": c["offset"], "timeout": espera, "allowed_updates": '["message"]'},
            timeout=espera + 15,
        )
        novedades = r.json().get("result", []) if r.ok else []
    except (requests.RequestException, ValueError):
        return 0
    n = 0
    for u in novedades:
        c = cargar_control()  # se relee en cada mensaje: un comando anterior pudo cambiar la lista
        c["offset"] = max(c["offset"], u["update_id"] + 1)
        guardar_control(c)  # el offset queda guardado antes de ejecutar (evita repetir comandos)
        msg = u.get("message") or {}
        if str((msg.get("chat") or {}).get("id")) != chat:
            continue  # solo se obedece al chat configurado
        resp = responder(msg.get("text", ""), ruta_historial, cache)
        if resp:
            telegram.enviar(resp, vista_previa=False)
            n += 1
    return n


def atender_mientras(hasta: float, ruta_historial: pathlib.Path) -> None:
    """Espera hasta la próxima vuelta contestando comandos (reemplaza al sleep)."""
    cache: dict = {}
    while True:
        resto = hasta - time.time()
        if resto <= 0:
            return
        t0 = time.time()
        try:
            atender(ruta_historial, espera=int(min(25, resto)), cache=cache)
        except Exception:  # noqa: BLE001
            pass
        if time.time() - t0 < 2:  # sin token, sin red o con error: no girar en vacío
            time.sleep(min(5, max(0, hasta - time.time())))
