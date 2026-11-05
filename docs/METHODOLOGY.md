# DTS Tracker v6 — Methodology / Metodología

## Español

Este panel tiene tres capas diferentes: **caja fiscal observada**, **contexto de liquidez** y **estimaciones estadísticas de investigación**. Ninguna constituye una orden de negociación. “Más fuerte que el anterior” no significa “por encima del consenso”.

### Lectura en cinco segundos

1. Mira el periodo previsto y la fecha oficial de publicación.
2. Compara anterior y estimación. En paro y solicitudes, una subida significa debilidad laboral; en inflación significa más presión de precios.
3. Mira la banda de error. Si es amplia, la cifra puntual aporta poca precisión.
4. Añade un consenso del mismo periodo y unidad si lo tienes. Sin ese dato no hay comparación válida frente a las expectativas del mercado.
5. Si aparece BLOQUEADO, no uses la cifra histórica como señal vigente.

### Qué se pronostica

| Objetivo | Serie oficial distribuida por FRED | Transformación | Unidad |
|---|---|---|---|
| NFP | BLS PAYEMS | Diferencia mensual del nivel de empleo | Miles de empleos |
| Desempleo | BLS UNRATE | Nivel | Porcentaje |
| Solicitudes iniciales | DOL ICSA | Nivel / 1.000 | Miles de solicitudes |
| Ventas minoristas | Census RSAFS | 100 × (nivel / nivel anterior − 1) | % mensual nominal |
| CPI general | BLS CPIAUCSL | Variación mensual | % mensual |
| CPI subyacente | BLS CPILFESL | Variación mensual | % mensual |
| PCE subyacente | BEA PCEPILFE | Variación mensual | % mensual |
| Producción industrial | Federal Reserve INDPRO | Variación mensual | % mensual real |
| Viviendas iniciadas | Census/HUD HOUST | Nivel anualizado | Miles de viviendas |
| Balanza comercial | BEA/Census BOPGSTB | Nivel / 1.000 | Miles de millones USD, con signo |

Son series ajustadas estacionalmente. Los pronósticos son para el siguiente periodo de observación de cada serie, no necesariamente para una publicación esta semana. El dashboard no inventa una fecha de publicación: la obtiene de la página oficial de la serie en FRED. Una fecha sin hora no se convierte en una hora exacta.

### Modelo y validación

El modelo de referencia usa el último nivel para series de nivel y la media de las tres últimas variaciones para series de cambio. Compite con una autorregresión AR(1) estimada sobre hasta 120 observaciones anteriores, con regularización fija del 10 % sobre la varianza y coeficiente acotado a ±0,95.

Se requieren al menos 120 observaciones válidas y 60 orígenes de pronóstico válidos. Las primeras 30 predicciones de ese tramo seleccionan AR1 solo si su MAE mejora al menos el 5 % frente a la referencia. Las siguientes 30 evalúan la selección sin volver a escoger el ganador. La mejora publicada es `(1 − MAE_modelo / MAE_referencia) × 100`. Si no hay ventaja, se muestra explícitamente.

La banda usa los percentiles 10 y 90 de los errores de esas 30 predicciones reservadas. **No garantiza una cobertura futura del 80 %**. Los errores son dependientes del régimen; los cambios estructurales pueden invalidar el comportamiento histórico.

La historia es la última versión revisada disponible. Estas pruebas **no son una evaluación frente a las primeras publicaciones históricas**, ni demuestran capacidad de anticipar sorpresas de mercado. No se presentan probabilidades numéricas de sorpresa. Los huecos se conservan; no se interpola y se excluyen los orígenes que necesiten datos ausentes. Una variación entre meses no consecutivos nunca se trata como mensual.

Desde v6 se archiva la primera estimación emitida cada día para cada objetivo y periodo en `data/forecast_archive/`. El archivo conserva fecha, método, huella SHA-256 de la fuente y resultados de evaluación. Reejecutar el día no sustituye esa primera emisión. Para demostrar ventaja en tiempo real será necesario asociar esos pronósticos con primeras publicaciones verificadas y consensos capturados antes del anuncio. Esa validación sigue pendiente.

### Qué aporta —y qué no aporta— el DTS

Se conserva la siguiente identidad en millones de USD:

`B = I − R`

`F = (W − R) − (D − I)`

`ΔTGA = B − F`

`Contribución TGA a reservas = −ΔTGA`, manteniendo constantes los demás factores del balance de la Fed.

Aquí `D` y `W` son ingresos y pagos totales; `I` y `R`, emisiones y amortizaciones de deuda en efectivo. `F` es un flujo neto de caja no financiador: **no equivale automáticamente al déficit MTS ni a creación consolidada de activos financieros netos**. La variación real de reservas también depende de activos de la Fed, efectivo, repos inversos y otras partidas.

Retenciones de nómina describen renta nominal y calendario tributario; no separan empleo, horas, salarios y tipos efectivos. Devoluciones y transferencias describen caja de hogares; no determinan el gasto minorista. Aduanas mezclan valor importado, aranceles, exenciones y desfases. No se convierten en previsiones de empleo, PIB o inflación mediante coeficientes arbitrarios. El DTS se muestra como evidencia contextual independiente hasta validar un modelo puente con datos disponibles en cada fecha.

### Calendario, datos ausentes y versiones

La fecha efectiva de un pago se calcula con un calendario independiente de las filas recibidas. Un día ausente es un problema de cobertura, no un festivo. Los pagos adelantados desde el mes siguiente se reconocen también cuando su fecha nominal supera el último DTS disponible. Se distinguen calendarios administrativos federales y bancarios; las convenciones de cada programa requieren mantenimiento frente a cambios oficiales.

El residual `F − E[componente de calendario | información anterior]` se compara con observaciones anteriores, excluyendo el día actual. Se publica el método efectivo y la muestra. Si falta muestra semanal se identifica el fallback de 60 días. El suelo de escala de 2.500 millones y las reglas Z/percentil son **umbrales de monitorización**, no probabilidades calibradas ni una garantía del 5 % de falsas alarmas.

Lag 364 usa coincidencias exactas, sin duplicar ni trasladar arbitrariamente días. Exige al menos un 95 % de parejas y presencia completa en los periodos comparados. La normalización por días hábiles no elimina cambios fiscales, inflación o composición salarial. Las reglas de ruptura de serie y cierres administrativos son avisos para revisión, no ajustes econométricos universales.

### Otras fuentes

- H.4.1: WRESBAL es un promedio semanal de reservas; WALCL es un saldo del miércoles. Se muestran por separado.
- H.8: TOTBKCR es crédito bancario semanal, con unidad original en miles de millones.
- RRPONTSYD: operaciones diarias de repos inversos, en miles de millones.
- DGS2 y DGS10: rendimientos diarios de vencimiento constante, no rentabilidades de una inversión.
- STLFSI4: índice semanal de estrés financiero; cero es su referencia histórica, no “riesgo cero”.

No se suman series con fechas o bases distintas para fabricar una “liquidez neta exacta”. Para PIB y ADP el panel explica qué información falta en lugar de inventar una cifra.

### Consenso y ARGOS

`data/consensus.json` acepta entradas por identificador con `value`, `reference_period`, `unit`, `source`, `captured_at` y `release_at` UTC. Exige mismo periodo/unidad, captura anterior al anuncio y antigüedad máxima de siete días. Una comparación numérica conserva el estado de investigación; no se convierte en probabilidad.

Las entradas hechas en pantalla son locales al navegador, caducan tras 24 horas o al cambiar de periodo y no modifican el archivo compartido. `data/argos_summary.json` resume las previsiones y declara `basis: research_vs_previous_not_consensus`. ARGOS debe rechazar el documento al vencer `expires`, respetar los estados por evento y no interpretar `STRONGER` como una compra de USD. El resumen con diez eventos supera normalmente 150 tokens: se prioriza conservar periodo, estado y significado.

### Actualización y fallos

GitHub Actions ejecuta el refresco los laborables a las 13:45, 15:45, 21:15, 22:15 y 23:15 UTC. El calendario del DTS se evalúa en Nueva York. Los horarios del dashboard se muestran en la zona del dispositivo. Las ejecuciones de Actions pueden retrasarse; no hay garantía de disponibilidad instantánea.

Los JSON incluyen vigencia; el navegador recalcula el bloqueo cada 30 segundos y al recuperar visibilidad. Los fallos conservan la fecha de los datos originales y se publican como fallos, incluso si el script del DTS termina con error. Las fuentes mensuales/semanales tienen controles independientes de antigüedad. Los archivos se escriben atómicamente. El frontend compara la copia desplegada y GitHub Raw para tomar la versión más reciente, incluida una notificación de fallo.

Fuentes: [Treasury DTS](https://fiscaldata.treasury.gov/datasets/daily-treasury-statement/), [FRED](https://fred.stlouisfed.org/), [BLS](https://www.bls.gov/schedule/), [BEA](https://www.bea.gov/news/schedule), [Fed H.4.1](https://www.federalreserve.gov/releases/h41/), [Fed H.8](https://www.federalreserve.gov/releases/h8/).

## English

The dashboard separates observed Treasury cash, central-bank liquidity context and numerical research estimates. Every estimate names its reference period, source, units, previous observation, held-out error band and research status. “Stronger than previous” is not “above consensus”, and neither automatically implies a stronger dollar.

Ten official monthly/weekly series are mapped in the table above. A persistence/recent-average baseline competes with a fixed-specification rolling AR1. Thirty chronological origins select the method; thirty later origins evaluate it without re-selection. At least 120 valid observations are required. Historical gaps remain missing; invalid prediction origins are skipped, and a multi-month change is never represented as one month. The empirical error band does not guarantee future 80% coverage.

All backtests use the latest revised vintage. Real-time first-release and market-surprise performance remain unverified. No surprise probability is published. First daily forecasts are archived immutably by target and reference period for future evaluation against verified first releases.

Treasury net cash is `(withdrawals − cash debt redemptions) − (deposits − cash debt issues)`. It is not automatically the MTS deficit or consolidated net-financial-asset creation. The TGA reserve contribution is `−ΔTGA`, holding other balance-sheet factors unchanged. Calendar residuals and robust Z scores are monitoring diagnostics, not macro probabilities. Withholding, refunds and customs are contextual fiscal evidence until a validated point-in-time bridge model exists.

Data quality and expiry fail closed in both the JSON contract and UI. SLGS supports OPEN, CLOSED and UNKNOWN. Every Fed series keeps its own observation date and measurement basis. No asynchronous balance-sheet series are summed into a fictitious exact liquidity measure. GDP and ADP limitations are explained explicitly.

Browser consensus entries are local and expire; shared ARGOS consensus requires the documented dated configuration. ARGOS must enforce `expires`, preserve per-event status and interpret all directions as comparisons with previous observations, not market expectations or trading instructions. See the Spanish sections for complete operational details and formulas.

## Monitor de caja restaurado y lectura para trading

La primera sección conserva TGA, depósitos y retiradas. `treasury_book.json` exporta los importes oficiales de la Tabla I en sus tres columnas: diario, mes acumulado y año fiscal acumulado. Los acumulados no se reconstruyen sumando una ventana truncada. El TGA siempre es el saldo al cierre; nunca se suman saldos. La fecha de corte y el año fiscal permiten revisar observaciones históricas. La identidad saldo inicial + depósitos − retiradas = saldo final se comprueba para cada columna, con tolerancia de redondeo de 5 millones USD. Datos ausentes permanecen nulos; las reversiones conservan el signo.

Los umbrales visuales originales se recuperaron del commit `dbab8541068e5ae1b35607b138822488f6b684c9`: flujo neto diario, media móvil de 30 sesiones, desviación típica poblacional incluyendo la sesión observada, bandas ±1σ y ±2σ; zonas Z con cortes −2, −1, +1 y +2. Se mantiene exactamente esta convención descriptiva. No existía en esa versión un umbral numérico independiente para el saldo TGA. Estas bandas no se aplican a acumulados o saldos ni sustituyen las puertas de calidad y el modelo de calendario del motor.

Las visualizaciones adicionales incluyen la cascada de caja, emisión/amortización frente a otros cobros/pagos, persistencia de 5/20/60 observaciones y contribución diaria del TGA a reservas. Para las últimas se mantienen constantes los demás factores del balance de la Fed. La comparación fiscal usa acumulados publicados tras igual número de sesiones de cada año: sigue siendo nominal y sensible a composición y calendario. Se suspende si la ventana no contiene el inicio de ambos años. Las 18 partidas originales se conservan como una selección, no como desglose exhaustivo del total. El margen legal frente al límite de deuda no mide la capacidad efectiva de las medidas extraordinarias ni predice una fecha de impago.

## Pulso DTS en el contrato de ARGOS y en el radar

El bloque `dts` de `argos_summary.json` incluye saldo inicial/final, variación del TGA, financiación neta en efectivo, Z de calendario, margen legal, estado SLGS y sumas NTF de 5/20/60 sesiones. Los importes son millones USD; el Z no tiene unidad. Si el DTS caduca o queda bloqueado, estos valores y los drivers fiscales pasan a `null`; SLGS pasa a `UNKNOWN`. Los acumulados requieren ventanas completas y observaciones conciliadas.

`fiscal_pulse_lag364` publica retenciones y prestaciones DOL a 20 sesiones (Lag 364), variaciones FYTD de retenciones, prestaciones DOL y devoluciones individuales EFT + cheques, devoluciones empresariales del día y aduanas. El campo `basis` distingue el Lag 364 de las ventanas móviles de la comparación de acumulados fiscales con su ancla de calendario. Las variaciones FYTD son de totales nominales, no tasas por sesión. Se conservan los signos de las reversiones y se diferencia ausencia de cero. La variación bruta de aduanas se publica como descriptiva con `customs_20d_comparable` y flags de ruptura/aranceles; no reactiva la señal predictiva suspendida. Las devoluciones FYTD pueden describirse fuera de temporada sin activar un pronóstico de ventas.

Los eventos `nfp`, `claims`, `retail` y `trade` incorporan `dts_driver`, calculado una sola vez para ARGOS y `macro_radar.json`; este último contiene también su texto español, fecha y caducidad. La tarjeta lo presenta junto al baseline de FRED, sin modificar su fórmula, estimación, bandas ni señal. El driver de claims utiliza el FYTD DOL, mientras el contrato conserva también el dato de 20 sesiones solicitado. Es contexto fiscal, no una estimación directa del número de solicitudes.
