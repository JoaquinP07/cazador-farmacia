"""Revisión completa: lee las tiendas, compara con el historial y avisa por Telegram.

Uso:
  python -m cazador            # una revisión
  python -m cazador --bucle    # revisa cada 10 minutos durante ~5 h 30 min (así corre en GitHub)
  python -m cazador --prueba   # además guarda una muestra en reporte/ y manda un mensaje de prueba
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

from . import telegram
from .nucleo import Historial, fmt
from .tiendas import DETALLE, TIENDAS

HISTORIAL = pathlib.Path("estado/historial.json")


def revisar(prueba: bool = False) -> None:
    DETALLE.clear()
    hist = Historial(HISTORIAL)
    tiendas_conocidas = {k.split(":", 1)[0] for k in hist.datos}
    resumen, muestras, avisos = {}, {}, 0
    inicio = time.time()

    # Las tiendas se leen en paralelo (cada una a su ritmo); después se evalúan en orden.
    def leer_tienda(item):
        nombre, leer = item
        t0 = time.time()
        try:
            return nombre, leer(), time.time() - t0
        except Exception:  # una tienda caída no frena a las demás
            traceback.print_exc()
            return nombre, None, time.time() - t0

    with ThreadPoolExecutor(max_workers=8) as ex:
        lecturas = list(ex.map(leer_tienda, TIENDAS.items()))

    for nombre, prods, seg in lecturas:
        if prods is None:
            resumen[nombre] = "error"
            print(f"{nombre}: error")
            continue
        resumen[nombre] = f"{len(prods)} productos en {seg:.0f}s"
        muestras[nombre] = [p.__dict__ for p in prods[:15]]
        for p in prods:
            motivo = hist.evaluar(p)
            # Una tienda sin historial todavía (recién agregada) solo aprende, no avisa.
            if motivo and nombre in tiendas_conocidas:
                avisos += 1
                print("AVISO:", p.tienda, p.nombre, fmt(p.precio, p.moneda), motivo)
                telegram.enviar(telegram.aviso(p, motivo))
        print(f"{nombre}: {resumen[nombre]}")

    hist.limpiar()
    hist.guardar()
    duracion = time.time() - inicio
    print(f"Listo en {duracion:.0f}s · {len(hist.datos)} productos en historial · {avisos} avisos")

    if prueba:
        lineas = "\n".join(f"• {k}: {v}" for k, v in resumen.items())
        ok = telegram.enviar(f"✅ <b>Cazador Farmacia: revisión de prueba</b>\n{lineas}")
        rep = pathlib.Path("reporte")
        rep.mkdir(exist_ok=True)
        (rep / "resumen.json").write_text(
            json.dumps({"tiendas": resumen, "duracion_s": round(duracion), "historial": len(hist.datos),
                        "telegram": "enviado" if ok else telegram.ULTIMO_ERROR,
                        "diagnostico": None if ok else telegram.diagnostico(), "detalle": DETALLE},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        (rep / "muestras.json").write_text(json.dumps(muestras, ensure_ascii=False, indent=1), encoding="utf-8")


# GitHub no respeta la programación cada pocos minutos (la demora horas), así que cada corrida
# revisa en bucle durante un rato largo y al terminar el workflow lanza la siguiente.
INTERVALO = int(os.environ.get("INTERVALO_MIN", "10")) * 60
DURACION = int(os.environ.get("DURACION_MIN", "330")) * 60


def main() -> int:
    if "--resumen" in sys.argv:
        from .resumen import correr

        return correr()
    if "--bucle" not in sys.argv:
        revisar(prueba="--prueba" in sys.argv)
        return 0
    inicio, vuelta = time.time(), 0
    while True:
        vuelta += 1
        t0 = time.time()
        print(f"\n===== Vuelta {vuelta} =====", flush=True)
        try:
            revisar()
        except Exception:  # un error en una vuelta no corta el bucle
            traceback.print_exc()
        proxima = t0 + INTERVALO
        if proxima + 60 - inicio > DURACION:
            break
        time.sleep(max(0, proxima - time.time()))
    print(f"Fin de la tanda: {vuelta} vueltas en {(time.time() - inicio) / 60:.0f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
