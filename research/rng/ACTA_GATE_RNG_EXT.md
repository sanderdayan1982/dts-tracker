# ACTA — GATE RNG-EXT · Rango previsto en los 21 cruces G8 y en XAUUSD · VEREDICTO: PASS

**Fecha:** 8-nov-2026.
**Pre-registro:** `research/rng/PRE-REG_GATE_RNG_EXT.md`, congelado antes de descargar ningún dato. Hereda todo el Gate RNG: modelo HAR-log, referencias B1/B2/B3, QLIKE, Diebold-Mariano con Newey-West y los criterios G1–G4.
**Datos:** velas diarias BID de Dukascopy 2016–2026 (113.450 filas, 29 instrumentos). Descarga gratuita en GitHub Actions (`dts-tracker`, ejecuciones 42465873237 → 42469381579 → 42493031735 → 42508349183, reanudadas desde caché). Faltó 1 de 464 archivos (CHFJPY, agosto de 2026, fuera de las ventanas del examen) y se recuperó en la última ejecución.
**Lectura:** desarrollo (2019–2022) y una única lectura de la confirmación (2023–2026-06), sin tocar la especificación entre ambas.

## Resultados (mejora de QLIKE frente a la media de 21 días de la mesa)

| Conjunto | Partición | 1 día | 5 días | Frente a EWMA (1d / 5d) | DM p (1d / 5d) | Instrumentos que ganan (1d / 5d) | Veredicto |
|---|---|---|---|---|---|---|---|
| 21 cruces | Desarrollo | **−8,6 %** | **−16,3 %** | −5,0 % / −8,6 % | 0,0006 / 0,0006 | 20/21 · 21/21 | PASS |
| 21 cruces | Confirmación | **−11,4 %** | **−16,0 %** | −6,8 % / −8,8 % | 3e-6 / 0,0005 | 20/21 · 19/21 | PASS |
| XAUUSD | Desarrollo | **−7,8 %** | **−13,1 %** | −4,5 % / −5,8 % | 4e-5 / 0,0009 | 1/1 | PASS |
| XAUUSD | Confirmación | **−12,1 %** | **−13,0 %** | −7,1 % / −5,8 % | 0,0001 / 0,009 | 1/1 | PASS |
| 7 mayores (réplica, velas 00:00 UTC) | Desarrollo | −6,4 % | −12,7 % | −3,4 % / −4,9 % | 0,004 / 0,003 | 7/7 | PASS |
| 7 mayores (réplica, velas 00:00 UTC) | Confirmación | −7,8 % | −13,4 % | −2,1 % / −2,4 % | 0,001 / 0,002 | 7/7 · 6/7 | PASS |

**Instrumentos donde el modelo no ganó** (se anotan por transparencia; el criterio pre-registrado es por conjunto):

| Partición | Horizonte | Instrumento | Diferencia |
|---|---|---|---|
| Desarrollo | 1 día | AUDJPY | −0,3 % |
| Confirmación | 1 día | GBPCAD | −0,2 % |
| Confirmación | 5 días | EURGBP | −3,8 % |
| Confirmación | 5 días | **GBPCAD** | **−16,7 %** |
| Réplica de mayores, confirmación | 5 días | GBPUSD | −2,5 % |

## Lectura
- **El rango previsto queda validado en los 29 instrumentos:** 28 pares y oro. La réplica de los 7 mayores con otro corte horario (00:00 UTC en lugar de 17:00 NY) también pasa, lo que indica que el resultado no depende del corte de la vela.
- **Vigilancia:** GBPCAD a 5 días quedó peor que la media de 21 días en la confirmación. Sin excluirlo, porque eso sería un cambio a posteriori, CIRO trata con cautela el `rng5` de GBPCAD y usa el más prudente de los dos.
- **Sigue siendo tamaño, no dirección.**

## Efecto
COLLECT v1.1: `rngValidated` incluye los 29 instrumentos, y todos imprimen `rng_val=PASS`.
