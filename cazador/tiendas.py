"""Lectores de cada tienda de farmacia y perfumería. Cada uno devuelve una lista de Producto."""
from __future__ import annotations

import html
import json
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
    for intento in range(4):
        espera = 2 + intento * 3
        try:
            r = SES.get(url, timeout=30, **kw)
            if r.status_code == 429:  # demasiados pedidos: esperar lo que pida la tienda y reintentar
                try:
                    espera = min(int(r.headers.get("Retry-After", "")), 60)
                except ValueError:
                    espera = 15 * (intento + 1)
            elif r.status_code < 500:
                return r
        except requests.RequestException:
            if intento == 3:
                raise
        time.sleep(espera)
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


def magento_html(tienda: str, base: str, categorias: Iterable[str], max_paginas: int = 60, hilos: int = 2) -> list[Producto]:
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


# ---------------------------------------------------------------- VTEX clásico (Farmacity)
def vtex(tienda: str, base: str, maximo: int = 2500, fq: str | None = None) -> list[Producto]:
    vistos: dict[str, Producto] = {}
    desde, total = 0, None
    while desde < maximo:
        r = _get(f"{base}/api/catalog_system/pub/products/search", params={"_from": desde, "_to": desde + 49, **({"fq": fq} if fq else {})})
        if r.status_code not in (200, 206):
            nota(f"  [{tienda}] desde {desde}: HTTP {r.status_code}")
            break
        if total is None:
            m = re.search(r"/(\d+)$", r.headers.get("resources", ""))
            total = int(m.group(1)) if m else maximo
        lote = r.json()
        if not lote:
            break
        for pr in lote:
            for it in pr.get("items", [])[:20]:
                of = ((it.get("sellers") or [{}])[0]).get("commertialOffer") or {}
                if not of.get("Price"):
                    continue
                lista = of.get("ListPrice") or of.get("PriceWithoutDiscount")
                p = Producto(
                    tienda=tienda,
                    id=str(it["itemId"]),
                    nombre=it.get("nameComplete") or pr["productName"],
                    precio=float(of["Price"]),
                    moneda="UYU",
                    url=pr.get("link") or f"{base}/{pr['linkText']}/p",
                    precio_lista=float(lista) if lista and lista > of["Price"] else None,
                    disponible=(of.get("AvailableQuantity") or 0) > 0,
                )
                vistos[p.clave] = p
        desde += 50
        if desde >= total:
            break
    nota(f"  [{tienda}] {fq or 'todo'}: {total} declarados")
    return list(vistos.values())


# ---------------------------------------------------------------- Magento 2 con GraphQL abierto (Farma.uy)
_MAG_Q = (
    "{products(search:\"\", %s pageSize:%d, currentPage:%d){total_count items{sku name url_key url_suffix stock_status "
    "price_range{minimum_price{final_price{value currency} regular_price{value}}}}}}"
)


def magento(tienda: str, base: str, categoria: str | None = None, por_pagina: int = 100, max_paginas: int = 60) -> list[Producto]:
    filtro = f'filter:{{category_id:{{eq:"{categoria}"}}}}' if categoria else ""
    vistos: dict[str, Producto] = {}
    total = None
    for pag in range(1, max_paginas + 1):
        r = _get(f"{base}/graphql", params={"query": _MAG_Q % (filtro, por_pagina, pag)})
        try:
            datos = r.json()["data"]["products"]
        except (ValueError, KeyError, TypeError):
            nota(f"  [{tienda}] pág {pag}: HTTP {r.status_code} {r.text[:150]}")
            break
        total = datos["total_count"]
        for it in datos["items"]:
            mp = it["price_range"]["minimum_price"]
            precio, lista = mp["final_price"]["value"], (mp.get("regular_price") or {}).get("value")
            if not precio:
                continue
            p = Producto(
                tienda=tienda,
                id=it["sku"],
                nombre=it["name"].strip(),
                precio=float(precio),
                moneda="USD" if mp["final_price"].get("currency") == "USD" else "UYU",
                url=f"{base}/{it['url_key']}{it.get('url_suffix') or ''}",
                precio_lista=float(lista) if lista and lista > precio else None,
                disponible=it.get("stock_status") == "IN_STOCK",
            )
            vistos[p.clave] = p
        if pag * por_pagina >= total or not datos["items"]:
            break
    nota(f"  [{tienda}] {total} declarados")
    return list(vistos.values())


def juntar(listas: Iterable[list[Producto]]) -> list[Producto]:
    """Une varias lecturas (una por categoría) sin repetir productos."""
    vistos: dict[str, Producto] = {}
    for lista in listas:
        for p in lista:
            vistos.setdefault(p.clave, p)
    return list(vistos.values())


# ---------------------------------------------------------------- VTEX FastStore (Tata / Multiahorro Hogar)
_FS_QUERY = "https://www.tata.com.uy/api/graphql"


def faststore(tienda: str, base: str, categorias: Iterable[str]) -> list[Producto]:
    vistos: dict[str, Producto] = {}
    for cat in categorias:
        after, total = 0, None
        while True:
            variables = {
                "first": 50,
                "after": str(after),
                "sort": "price_asc",
                "term": "",
                "selectedFacets": [{"key": "category-1", "value": cat}],
            }
            r = _get(
                _FS_QUERY,
                params={"operationName": "ProductsQuery", "variables": json.dumps(variables)},
            )
            if r.status_code != 200:
                nota(f"  [{tienda}] {cat}: HTTP {r.status_code}")
                break
            try:
                datos = r.json()["data"]["search"]["products"]
            except (ValueError, KeyError, TypeError):
                nota(f"  [{tienda}] {cat}: respuesta inesperada {r.text[:200]}")
                break
            total = datos["pageInfo"]["totalCount"]
            for e in datos["edges"]:
                n = e["node"]
                for o in (n.get("offers") or {}).get("offers", [])[:1]:
                    p = Producto(
                        tienda=tienda,
                        id=str(n["sku"]),
                        nombre=n["name"],
                        precio=float(o["price"]),
                        moneda="UYU",
                        url=f"{base}/{n['slug']}/p",
                        precio_lista=float(o["listPrice"]) if o.get("listPrice") else None,
                        disponible="InStock" in (o.get("availability") or ""),
                    )
                    vistos[p.clave] = p
            after += 50
            if after >= total or not datos["edges"] or after >= 3000:
                break
        nota(f"  [{tienda}] {cat}: {total} declarados")
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
    "Farmacity": lambda: juntar(
        vtex("Farmacity", "https://www.farmacity.com.uy", fq=f"C:/{cat}/")
        for cat in (
            2228,  # Maquillaje
            2249,  # Perfumes y fragancias
            2254,  # Cuidado de la piel
            2255,  # Cuidado capilar
            2263,  # Electro belleza
            2270,  # Accesorios de belleza
            2273,  # Dermocosmética
            2297,  # Cuidado personal
            2425,  # Nutrición y deportes
        )
    ),
    "Farma.uy": lambda: juntar(
        magento("Farma.uy", "https://www.farma.uy", categoria=cat)
        for cat in (
            8,  # Dermocosmética
            387,  # Maquillaje
            15,  # Cuidado capilar
            45,  # Perfumes y fragancias
            51,  # Cuidado personal
            80,  # Suplementos y fitness
            271,  # Belleza
            1001,  # Oportunidades imperdibles
        )
    ),
    "Tata / Multiahorro": lambda: faststore(
        "Tata / Multiahorro", "https://www.tata.com.uy", ["perfumeria"]  # shampoos, jabones, desodorantes, cuidado personal
    ),
}
