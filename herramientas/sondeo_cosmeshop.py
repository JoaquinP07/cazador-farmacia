"""Diagnóstico de una sola vez: ¿por qué Cosmeshop responde 405 desde GitHub?"""
import requests

URL = "https://www.cosmeshop.com.uy/maquillaje"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
COMPLETO = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "es-UY,es;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}
PRUEBAS = {
    "usuario_solo": {"User-Agent": UA},
    "navegador_completo": COMPLETO,
    "navegador_con_referer": {**COMPLETO, "Referer": "https://www.google.com/", "Sec-Fetch-Site": "cross-site"},
    "sin_idioma": {"User-Agent": UA, "Accept": "*/*"},
}
for nombre, h in PRUEBAS.items():
    for url in (URL, "https://www.cosmeshop.com.uy/", URL + "?pagenumber=2"):
        try:
            r = requests.get(url, headers=h, timeout=30)
            print(f"{nombre:24} {r.status_code} {len(r.text):>7} bytes  {url.replace('https://www.cosmeshop.com.uy','') or '/'}"
                  f"  server={r.headers.get('server')} items={r.text.count('product-item with-text')}")
        except Exception as e:  # noqa: BLE001
            print(f"{nombre:24} error {e!r}"[:200])
r = requests.get(URL, headers=COMPLETO, timeout=30)
print("cuerpo:", r.text[:200].replace("\n", " "))
