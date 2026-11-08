# PRE-REGISTRO — GATE RNG-EXT · Extensión a los 28 pares G8 y al oro

**Estado:** CONGELADO 8-nov-2026, antes de descargar ningún dato. Hereda TODO de `PRE-REG_GATE_RNG.md`
(sha256 `ec32e55e…2b195b`): modelo, referencias, métrica, particiones y criterios G1–G4. Solo cambian los datos y el
número de instrumentos.

## Datos
- Velas diarias BID de Dukascopy, archivos anuales `BID_candles_day_1.bi5`, cierre a las 00:00 UTC.
- Periodo 2016–2026. Se descargan en GitHub Actions (coste cero).
- Se descartan sábados y domingos (`n_hours = 0`) y las barras con H<=L.
- Las velas cierran a las 00:00 UTC y no a las 17:00 de Nueva York. El modelo es el mismo y la comparación es interna a cada serie.

## Tres veredictos independientes
1. **CROSSES:** los 21 cruces sin USD. G3 = al menos el 86 % de los pares (la proporción de 6 de 7), es decir 18 de 21.
2. **XAUUSD:** el oro solo. G3 es trivial (1 de 1); G1, G2 y G4 se aplican igual.
3. **MAJORS-DK:** los 7 pares USD con velas a 00:00 UTC. Es una réplica de robustez frente a otro corte horario.
   No reemplaza al PASS original.

Cada conjunto necesita PASS en desarrollo (2019–2022) y en confirmación (2023–2026-06). La especificación no se toca entre corridas.
Un conjunto en FAIL no usa el número en producción. Su chip mostrará el rango como «no validado».
