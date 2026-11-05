"""Lectores de cada tienda de farmacia y perfumería. Cada uno devuelve una lista de Producto."""
from __future__ import annotations

import html
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable

import requests

from .nucleo import Producto

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
)
DETALLE: list[str] = []  # notas por categoría, para el reporte de prueba


def nota(txt: str) -> None:
    print(txt)
    DETALLE.append(txt)


SES = requests.Session()
SES.headers.update({"User-Agent": UA, "Accept-Language": "es-UY,es;q=0.9"})


def _get(url: str, **kw) -> requests.Response:
    for intento in range(3):
        try:
            r = SES.get(url, timeout=30, **kw)
            if r.status_code < 500:
                return r
        except requests.RequestException:
            if intento == 2:
                raise
        time.sleep(2 + intento * 3)
    return r


def numero(txt: str) -> float:
    """'7.080' -> 7080 ; '439,00' -> 439.0 ; '1.299,50' -> 1299.5"""
    txt = txt.strip().replace("\xa0", "")
    if "," in txt:
        txt = txt.replace(".", "").replace(",", ".")
    else:
        txt = txt.replace(".", "")
    return float(txt or 0)


def moneda(sim: str) -> str:
    return "USD" if re.search(r"USD|U\$S|US\$", sim, re.I) else "UYU"


def _monto(txt: str) -> tuple[str, float] | None:
    """'$ 1.490' / '$U 456,75' / 'US$ 12' -> (símbolo, número)."""
    m = re.search(r"([^\d\s]*[^\d]*?)\s*(\d[\d.,]*)", html.unescape(txt).replace("\xa0", " "))
    if not m:
        return None
    try:
        return m.group(1).strip(), numero(m.group(2))
    except ValueError:
        return None


# ---------------------------------------------------------------- Fenicio (San Roque)
_IT = re.compile(r"<div class='it [^']*' data-disp='(\d)' data-codProd='([^']+)' data-codVar='([^']+)'")


def _fenicio_pagina(texto: str, tienda: str) -> list[Producto]:
    prods = []
    cortes = [m.start() for m in _IT.finditer(texto)] + [len(texto)]
    for i, m in enumerate(_IT.finditer(texto)):
        bloque = texto[m.start(): cortes[i + 1]]
        disp, cod, var = m.groups()
        a = re.search(r'<a class="tit" href="([^"]+)" title="([^"]*)"', bloque)
        venta = re.search(
            r'class="precio venta"><span class="sim">([^<]*)</span>\s*<span class="monto">([^<]*)<',
            bloque,
        )
        if not a or not venta:
            continue
        lista = re.search(
            r'class="precio lista"><span class="sim">[^<]*</span>\s*<span class="monto">([^<]*)<',
            bloque,
        )
        precio = numero(venta.group(2))
        prods.append(
            Producto(
                tienda=tienda,
                id=f"{cod}-{var}",
                nombre=html.unescape(a.group(2)),
                precio=precio,
                moneda=moneda(venta.group(1)),
                url=a.group(1),
                precio_lista=numero(lista.group(1)) if lista else None,
                disponible=disp == "1",
            )
        )
    return prods


def fenicio(tienda: str, base: str, categorias: Iterable[str], max_paginas: int = 130) -> list[Producto]:
    vistos: dict[str, Producto] = {}
    for cat in categorias:
        total = None
        for pag in range(1, max_paginas + 1):
            url = f"{base}/{cat}?js=1&pag={pag}"
            r = _get(url)
            if r.status_code != 200:
                nota(f"  [{tienda}] {cat} pág {pag}: HTTP {r.status_code}")
                break
            if total is None:
                t = re.search(r'data-total="(\d+)"', r.text)
                total = int(t.group(1)) if t else 0
            nuevos = _fenicio_pagina(r.text, tienda)
            if not nuevos:
                break
            for p in nuevos:
                vistos[p.clave] = p
            if pag * 12 >= (total or 0):
                break
        nota(f"  [{tienda}] {cat}: {total} declarados")
    return list(vistos.values())


# ---------------------------------------------------------------- Magento 2 en HTML (Farmashop)
# El GraphQL de Farmashop está cerrado, así que se leen las páginas de categoría (40 productos por página).
_FS_ITEM = re.compile(r'<div class="product-item-info[^"]*" id="product-item-info_(\d+)"')


def _farmashop_pagina(texto: str, tienda: str, base: str) -> list[Producto]:
    prods = []
    cortes = [m.start() for m in _FS_ITEM.finditer(texto)] + [len(texto)]
    for i, m in enumerate(_FS_ITEM.finditer(texto)):
        bloque = texto[m.start(): cortes[i + 1]]
        a = re.search(r'class="product name product-item-link"\s+href="([^"]+)"', bloque)
        nombre = re.search(r'<label class="product-name[^"]*">([^<]*)</label>', bloque)
        actual = re.search(r'class="price regular_price">([^<]*)<', bloque)
        if not (a and nombre and actual):
            continue
        precio = _monto(actual.group(1))
        if not precio or not precio[1]:
            continue
        antes = re.search(r'class="price_label item_list old_price"[^>]*><span>([^<]*)</span>', bloque)
        lista = _monto(antes.group(1)) if antes else None
        prods.append(
            Producto(
                tienda=tienda,
                id=m.group(1),
                nombre=html.unescape(nombre.group(1)).strip(),
                precio=precio[1],
                moneda=moneda(precio[0]),
                url=a.group(1) if a.group(1).startswith("http") else base + a.group(1),
                precio_lista=lista[1] if lista and lista[1] > precio[1] else None,
            )
        )
    return prods


def magento_html(tienda: str, base: str, categorias: Iterable[str], max_paginas: int = 60, hilos: int = 3) -> list[Producto]:
    def leer_categoria(cat: str) -> list[Producto]:
        encontrados: dict[str, Producto] = {}
        for pag in range(1, max_paginas + 1):
            r = _get(f"{base}/{cat}.html", params={"p": pag})
            if r.status_code != 200:
                nota(f"  [{tienda}] {cat} pág {pag}: HTTP {r.status_code}")
                break
            nuevos = [p for p in _farmashop_pagina(r.text, tienda, base) if p.clave not in encontrados]
            if not nuevos:
                break
            for p in nuevos:
                encontrados[p.clave] = p
        nota(f"  [{tienda}] {cat}: {len(encontrados)} leídos")
        return list(encontrados.values())

    vistos: dict[str, Producto] = {}
    with ThreadPoolExecutor(max_workers=hilos) as ex:  # pocas categorías a la vez, para no saturar la tienda
        for lote in ex.map(leer_categoria, list(categorias)):
            for p in lote:
                vistos.setdefault(p.clave, p)
    return list(vistos.values())


# ---------------------------------------------------------------- nopCommerce (Cosmeshop)
_NOP_ITEM = re.compile(r'<div class="product-item[^"]*" data-productid="(\d+)"')


def _nop_pagina(texto: str, tienda: str, base: str) -> list[Producto]:
    prods = []
    cortes = [m.start() for m in _NOP_ITEM.finditer(texto)] + [len(texto)]
    for i, m in enumerate(_NOP_ITEM.finditer(texto)):
        bloque = texto[m.start(): cortes[i + 1]]
        a = re.search(r'<h2 class="product-title"><a href="([^"]+)">([^<]*)</a>', bloque)
        actual = re.search(r'class="price actual-price">([^<]*)<', bloque)
        if not (a and actual):
            continue
        precio = _monto(actual.group(1))
        if not precio or not precio[1]:
            continue
        antes = re.search(r'class="price old-price">([^<]*)<', bloque)
        lista = _monto(antes.group(1)) if antes else None
        prods.append(
            Producto(
                tienda=tienda,
                id=m.group(1),
                nombre=html.unescape(a.group(2)).strip(),
                precio=precio[1],
                moneda=moneda(precio[0]),
                url=base + a.group(1) if a.group(1).startswith("/") else a.group(1),
                precio_lista=lista[1] if lista and lista[1] > precio[1] else None,
                disponible="product-box-add-to-cart-button" in bloque,
            )
        )
    return prods


def nopcommerce(tienda: str, base: str, categorias: Iterable[str], max_paginas: int = 80) -> list[Producto]:
    vistos: dict[str, Producto] = {}
    for cat in categorias:
        n = 0
        for pag in range(1, max_paginas + 1):
            r = _get(f"{base}/{cat}", params={"pagenumber": pag})
            if r.status_code != 200:
                nota(f"  [{tienda}] {cat} pág {pag}: HTTP {r.status_code}")
                break
            nuevos = [p for p in _nop_pagina(r.text, tienda, base) if p.clave not in vistos]
            if not nuevos:
                break
            for p in nuevos:
                vistos[p.clave] = p
            n += len(nuevos)
            ultima = max((int(x) for x in re.findall(r"pagenumber=(\d+)", r.text)), default=1)
            if pag >= ultima:
                break
        nota(f"  [{tienda}] {cat}: {n} leídos")
    return list(vistos.values())


# ---------------------------------------------------------------- Configuración
TIENDAS: dict[str, Callable[[], list[Producto]]] = {
    "San Roque": lambda: fenicio(
        "San Roque",
        "https://www.sanroque.com.uy",
        [
            "perfumeria",
            "maquillaje",
            "cuidado-de-la-piel",
            "cuidado-personal",
            "salud/vitaminas",
            "salud/nutricion",
        ],
    ),
    "Farmashop": lambda: magento_html(
        "Farmashop",
        "https://tienda.farmashop.com.uy",
        [
            "perfumes/perfumes-de-mujer",
            "perfumes/perfumes-de-hombre",
            "perfumes/perfumes-unisex",
            "perfumes/perfumes-arabes-importados",
            "perfumes/perfumes-infantiles",
            "perfumes/perfumes-10ml",
            "perfumes/body-splash",
            "maquillaje/bases",
            "maquillaje/bronzers-y-contornos",
            "maquillaje/correctores",
            "maquillaje/cejas",
            "maquillaje/delineador-de-labios",
            "maquillaje/desmaquillantes",
            "maquillaje/iluminadores",
            "maquillaje/labiales",
            "maquillaje/ojos",
            "maquillaje/pesta-as",
            "maquillaje/polvo-compacto",
            "maquillaje/rubores",
            "maquillaje/accesorios-de-maquillaje",
            "manos/cremas",
            "manos/esmalte",
            "manos/manicura",
            "manos/pedicure",
            "manos/quitaesmalte",
            "manos/tratamiento",
            "cuidado-personal/cuidado-de-la-piel",
            "cuidado-personal/cuidado-capilar",
            "cuidado-personal/proteccion-femenina",
            "cuidado-personal/cuidado-masculino",
            "cuidado-personal/cuidado-oral",
            "cuidado-personal/higiene-corporal",
            "cuidado-personal/repelentes",
            "salud/vitaminas",
            "salud/minerales",
            "salud/suplementacion",
            "salud/complementos-nutricionales",
        ],
    ),
    "Cosmeshop": lambda: nopcommerce(
        "Cosmeshop",
        "https://www.cosmeshop.com.uy",
        ["maquillaje", "unas-2", "cosmetica", "perfumeria", "promociones"],
    ),
}
