# PRE-REGISTRO — GATE RNG · Previsión del rango (volatilidad) diario G8

**Estado:** CONGELADO 8-nov-2026, antes de ejecutar sobre datos reales. Autor: Claude (por encargo de Sander).
**Ley de la casa:** el técnico describe y no predice la dirección. Este gate NO prueba dirección.
Pregunta si la MAGNITUD del movimiento de mañana y de los próximos 5 días se puede prever mejor
que con lo que la mesa usa hoy.

## 1. Pregunta
¿Un modelo HAR (Corsi 2009) sobre la varianza de rango diaria prevé la varianza de mañana (h=1)
y la media de los próximos 5 días (h=5) mejor que la ventana de 21 días que la mesa usa hoy para
dimensionar (σ21)?

## 2. Datos
- `RSF_gate/RSF_daily_ohlcv.csv` (Dukascopy, los mismos datos que los gates RSF/TSM/BDC/TCE).
- 7 pares USD: AUDUSD, EURUSD, GBPUSD, NZDUSD, USDCAD, USDCHF, USDJPY. Periodo 2016-01 a 2026-06.
- Se descartan las barras con `n_hours < 20` (festivos y velas cortas) y las barras con H<=L.

## 3. Variable objetivo (proxy de varianza)
Varianza de Parkinson diaria: `v_t = (ln(H_t/L_t))^2 / (4 ln 2)`.
- h=1: `v_{t+1}`.
- h=5: media de `v_{t+1..t+5}`.

## 4. Modelos (especificación fija, sin búsqueda)
- **HAR-log (candidato):** `ln v_{t+1} = b0 + b1 ln v_t + b2 ln mean5(v)_t + b3 ln mean22(v)_t + e`.
  - Se estima por MCO con ventana expandible y re-estimación cada día. Solo usa información hasta t.
  - Mínimo de 750 observaciones antes de la primera previsión.
  - Previsión: `exp(ŷ + 0.5·s²)`, donde s² es la varianza de los residuos de entrenamiento.
  - Para h=5 se estima otra regresión con la media de 5 días adelante como objetivo y los mismos regresores.
- **B1 · Referencia de la mesa en la misma escala (principal):** media de `v` en los últimos 21 días.
  Es la misma ventana que σ21, en la misma escala que el objetivo.
- **B2 · Referencia ingenua:** `v_t` (mañana igual que hoy).
- **B3 · RiskMetrics:** EWMA de `v` con λ = 0.94.

## 5. Métrica y prueba
- Pérdida principal: QLIKE = `y/f − ln(y/f) − 1`. Es robusta a un proxy ruidoso (Patton 2011).
- Pérdida secundaria: MSE sobre la varianza.
- Diebold-Mariano unilateral sobre la diferencia de QLIKE (HAR − B1), con error estándar de
  Newey-West (rezagos = h+4), agregando todos los pares y cada par por separado.

## 6. Particiones
- **Desarrollo:** previsiones fechadas desde 2019-01-01 hasta 2022-12-31.
- **Confirmación (reserva):** desde 2023-01-01 hasta 2026-06-30. Se lee una sola vez, después del
  veredicto de desarrollo, sin tocar la especificación.

## 7. Criterios de PASS (congelados, para h=1 y h=5 por separado)
- **G1:** QLIKE agregada del HAR al menos un 5 % menor que la de B1.
- **G2:** DM agregado con p < 0.05.
- **G3:** el HAR mejora a B1 en QLIKE en al menos 6 de los 7 pares.
- **G4:** el HAR no pierde frente a B2 ni frente a B3 en QLIKE agregada.
- **Veredicto:** PASS si G1–G4 se cumplen en desarrollo Y en confirmación. Si solo pasa en
  desarrollo, el veredicto es FAIL.

## 8. Uso si pasa
Rango esperado (1 día y 5 días) por par, en pips y en múltiplos de ATR, como dato del parte diario.
Sirve para tamaño, stops y días de dato. No es señal de entrada ni de dirección.

## 9. Qué NO hace este gate
- No prueba dirección.
- No toca ningún script congelado.
- No abre la reserva del 40 % de EM1, que se archiva como FAIL.
