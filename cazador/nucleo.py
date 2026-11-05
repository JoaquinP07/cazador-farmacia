"""Historial de precios y detección de posibles errores de precio."""
from __future__ import annotations

import json
import pathlib
import statistics
import time
from dataclasses import dataclass, field

# Una baja mayor a esto respecto al precio habitual del producto dispara un aviso.
CAIDA_MINIMA = 0.30
# Para productos nuevos (sin historial): descuento contra el precio de lista que dispara aviso.
DESCUENTO_LISTA_MINIMO = 0.60
# Cuántos precios recordamos por producto.
MAX_HISTORIAL = 30
# No repetir el aviso del mismo producto antes de este tiempo (segundos).
SILENCIO_AVISO = 12 * 3600


@dataclass
class Producto:
    tienda: str
    id: str
    nombre: str
    precio: float
    moneda: str  # "UYU" o "USD"
    url: str
    precio_lista: float | None = None
    disponible: bool = True
    extra: dict = field(default_factory=dict)

    @property
    def clave(self) -> str:
        return f"{self.tienda}:{self.id}"


class Historial:
    def __init__(self, ruta: pathlib.Path):
        self.ruta = ruta
        self.datos: dict = {}
        if ruta.exists():
            try:
                self.datos = json.loads(ruta.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self.datos = {}

    def guardar(self) -> None:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self.ruta.write_text(json.dumps(self.datos, ensure_ascii=False), encoding="utf-8")

    def evaluar(self, p: Producto) -> str | None:
        """Registra el precio y devuelve un motivo de aviso si parece un error."""
        ahora = int(time.time())
        reg = self.datos.setdefault(
            p.clave, {"n": p.nombre, "m": p.moneda, "h": [], "aviso": 0}
        )
        previos = [x for x in reg["h"] if x > 0]
        motivo = None

        if p.disponible and p.precio > 0:
            if len(previos) >= 2:
                habitual = statistics.median(previos)
                if reg.get("m") == p.moneda and p.precio <= habitual * (1 - CAIDA_MINIMA):
                    motivo = (
                        f"bajó {1 - p.precio / habitual:.0%} respecto a su precio habitual "
                        f"({fmt(habitual, p.moneda)})"
                    )
            elif p.precio_lista and p.precio <= p.precio_lista * (1 - DESCUENTO_LISTA_MINIMO):
                motivo = (
                    f"{1 - p.precio / p.precio_lista:.0%} menos que su precio de lista "
                    f"({fmt(p.precio_lista, p.moneda)})"
                )

        if motivo and ahora - reg.get("aviso", 0) < SILENCIO_AVISO:
            motivo = None
        if motivo:
            reg["aviso"] = ahora
        else:
            # Los precios sospechosos no entran al historial, así no "contaminan" el habitual.
            if p.precio > 0:
                reg["h"] = (reg["h"] + [p.precio])[-MAX_HISTORIAL:]
        reg["n"], reg["m"], reg["t"] = p.nombre, p.moneda, ahora
        return motivo

    def limpiar(self, dias: int = 30) -> None:
        limite = time.time() - dias * 86400
        self.datos = {k: v for k, v in self.datos.items() if v.get("t", 0) >= limite}


def fmt(valor: float, moneda: str) -> str:
    simbolo = "US$" if moneda == "USD" else "$"
    return f"{simbolo} {valor:,.0f}".replace(",", ".")
