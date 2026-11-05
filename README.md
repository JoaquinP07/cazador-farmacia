# Cazador de farmacia y perfumería

Revisa cada 10 minutos las secciones de perfumería, maquillaje, cuidado personal y vitaminas de varias tiendas uruguayas y avisa por Telegram (a un grupo) cuando un producto baja de golpe (posible error de precio u oferta fuerte).

Es el tercer cazador de la familia: el de electrónica (`cazador-ofertas`) y el de ferretería y hogar (`cazador-hogar`) son repositorios aparte.

## Tiendas

| Tienda | Cobertura |
|---|---|
| San Roque | Perfumería, maquillaje, cuidado de la piel, cuidado personal, vitaminas y nutrición (~5.000). Sin medicamentos. |
| Farmashop | Perfumes, maquillaje, manos, cuidado personal y suplementos (~5.200). Sin medicamentos. |
| Farmacity | Maquillaje, perfumes, cuidado de la piel y capilar, dermocosmética, cuidado personal y nutrición (~3.700). Sin medicamentos. |
| Farma.uy | Dermocosmética, maquillaje, cuidado capilar y personal, perfumes, suplementos y belleza (~1.500). Sin medicamentos. |
| Tata / Multiahorro | Sección de perfumería: cuidado personal, higiene, cabello y perfumes (~1.470) |
| Cosmeshop | ❌ pide verificación «soy humano» y bloquea las conexiones desde GitHub |

Pendientes de revisar: La Farmacia Online (no se encontró la dirección web) y Perfumería Todo.

## Cuándo avisa

- Un producto cuesta **30% menos o más** que su precio habitual (la mediana de los últimos precios vistos).
- Un producto nuevo aparece con **60% o más** de descuento sobre su precio de lista.
- No repite el aviso del mismo producto durante 12 horas.

Los porcentajes se cambian en `cazador/nucleo.py`.

## Configuración

En **Settings → Secrets and variables → Actions** del repositorio:

- `TELEGRAM_TOKEN`: el token del bot (el que da @BotFather).
- `TELEGRAM_CHAT_ID`: el número del grupo de Telegram (empieza con `-`). Para averiguarlo: agregá el bot al grupo, escribí un mensaje ahí y corré el flujo **Averiguar el número del grupo** desde la pestaña Actions.

## Flujos de GitHub Actions

- **Cazador Farmacia**: la revisión continua. Se lanza a mano la primera vez (y con «prueba» activada manda un mensaje de prueba y guarda un reporte); después se encadena sola.
- **Resumen de ofertas**: manda un solo mensaje con los productos de mayor descuento publicado ahora mismo. A diferencia de los avisos, no son errores de precio: son rebajas que la tienda ya tiene puestas.
- **Averiguar el número del grupo**: se usa una vez para el `TELEGRAM_CHAT_ID`.
