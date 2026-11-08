# ACTA — GATE RNG · Previsión del rango diario G8 · VEREDICTO: PASS

**Fecha:** 8-nov-2026.
**Pre-registro:** `PRE-REG_GATE_RNG.md`, sha256 `ec32e55e…2b195b`. Se congeló y se copió a esta carpeta antes de ejecutar nada.
**Datos:** `RSF_daily_ohlcv.csv` (Dukascopy), 7 pares USD, barras con al menos 20 horas.
**Script:** `gate_rng.py`. Ventana expandible, re-estimación diaria, sin mirar el futuro.
**Ejecuciones:** una en desarrollo y después una única lectura de la reserva. La especificación no se tocó entre ambas.

## Resultados (QLIKE: más bajo es mejor)

| Partición | Horizonte | HAR | B1 · media 21 d (mesa) | Mejora vs B1 | Mejora vs EWMA | DM p | Pares ganados | G1–G4 |
|---|---|---|---|---|---|---|---|---|
| Desarrollo 2019–2022 | 1 día | 0,3406 | 0,3677 | **7,4 %** | 4,5 % | 0,0001 | 7/7 | PASS |
| Desarrollo 2019–2022 | 5 días | 0,1703 | 0,1920 | **11,3 %** | 4,3 % | 0,005 | 7/7 | PASS |
| Confirmación 2023–2026 | 1 día | 0,3373 | 0,3656 | **7,7 %** | 2,2 % | 0,0006 | 7/7 | PASS |
| Confirmación 2023–2026 | 5 días | 0,1580 | 0,1811 | **12,7 %** | 3,1 % | 0,002 | 7/7 | PASS |

Mejora por par en la confirmación a 1 día:

| Par | Mejora |
|---|---|
| AUDUSD | +9,7 % |
| EURUSD | +7,5 % |
| GBPUSD | +3,1 % |
| NZDUSD | +4,6 % |
| USDCAD | +4,7 % |
| USDCHF | +8,2 % |
| USDJPY | +12,6 % |

A 5 días, GBPUSD queda prácticamente en empate (+0,1 %). Los otros seis pares mejoran.

## Lectura
- **Primer componente predictivo validado de la capa técnica.** Prevé CUÁNTO se moverá un par mañana y en la semana, mejor que la ventana de 21 días que usa la mesa. Pasa los cuatro criterios en desarrollo y en la reserva, sin tocar nada entre ambas.
- **NO prevé la dirección.** La ley «el técnico describe la dirección y no la predice» sigue intacta.
- **La ventaja frente a una EWMA es pequeña (2–3 %).** El salto grande es frente a la ventana plana de 21 días que usa hoy el vol-targeting.
- **Límites:** solo se probaron los 7 pares USD con OHLC propio. Los 21 cruces y el oro necesitan su propia comprobación antes de usar el número.

## Uso autorizado
Rango esperado a 1 día y a 5 días (en pips y en múltiplos de ATR) como dato de tamaño, stops y días de dato. No es señal de entrada.
