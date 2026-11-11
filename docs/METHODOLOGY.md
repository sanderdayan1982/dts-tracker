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

## v6.1 — Vigencia, ventaja y lectura de mesa

- **Vigencia del radar.** `valid_until_utc` = generación + 26 h, ampliada 24 h por cada fin de semana o festivo federal dentro de la ventana (no hay publicaciones ni refrescos programados esos días). Un fallo en día hábil sigue caducando a las 26 h.
- **Ventaja demostrada.** Si el AR1 elegido en el tramo de selección no mejora a la referencia en el tramo reservado, se publica la referencia (`demoted_on_holdout: true`). El tramo reservado solo puede degradar al modelo simple, nunca promover uno complejo. Cada estimación lleva `edge: DEMONSTRATED | NONE`.
- **ARGOS.** En `argos_summary.json`, `signal` es `null` cuando `edge` es `NONE`; la dirección bruta se conserva en `signal_research`. ARGOS no debe usar `signal_research` como señal.
- **Lectura de mesa.** Franja superior generada automáticamente a partir del contrato de caja y del radar: variación del TGA y su contribución a reservas, Z de calendario, caja neta y financiación, próximo dato con su estado de ventaja y recuento de consensos cargados. Es un resumen descriptivo, no una señal de trading.

## v7 — Puente DTS → datos de impacto

**Objetivo.** Medir, sin información futura, si la caja diaria del Tesoro mejora la estimación de NFP, solicitudes de paro, ventas minoristas y balanza comercial.

| Dato | Canal DTS | Variable | Corte de información |
|---|---|---|---|
| NFP (PAYEMS, Δ mensual) | Retenciones IRPF/FICA (Tabla II; Tabla IV antes del 14-02-2023) | Crecimiento Lag 364 de 20 sesiones menos su media de 12 meses | 2 días hábiles antes del viernes BLS |
| Solicitudes (ICSA) | Prestaciones por desempleo DOL | Cambio semanal del crecimiento Lag 364 de 5 sesiones | Martes posterior a la semana de referencia |
| Ventas (RSAFS, % m/m) | Retenciones + devoluciones individuales (Tabla V) | Sorpresa de retenciones e impulso de devoluciones frente a un año antes | Último día hábil del mes |
| Balanza (BOPGSTB) | Aduanas | Crecimiento Lag 364 de 15 sesiones del mes siguiente menos su media de 12 meses | Día 25 del mes siguiente |

**Diseño fijado de antemano.** Una especificación por dato, sin búsqueda de variables. Regresión con penalización ridge fija (λ = 1 sobre variables estandarizadas), ventana móvil de 96 meses y mínimo de 36. Cada origen se estima solo con periodos cuyo dato ya estaba publicado. Se excluye mar-2020 a dic-2021 del ajuste y de la evaluación.

**Regla de ventaja.** `DEMONSTRATED` exige: mejora del MAE ≥ 5 % frente a la referencia del radar, Diebold-Mariano unilateral p < 0,10 (Newey-West, 3 retardos), mejora positiva en los últimos 24 orígenes **y** mejora ≥ 2 % con p < 0,10 frente al mismo modelo sin las variables DTS (ablación). La ablación se añadió tras la primera ejecución porque la mejora de ventas minoristas procedía de la contracción de la referencia y no del DTS; solo endurece la regla.

**Resultado inicial (2019–2026, sin pandemia).** Ningún canal demuestra valor añadido del DTS: NFP +0,4 % frente a la ablación (p 0,19); ventas +0,4 % (p 0,37); solicitudes −0,6 %; balanza −0,4 %. El puente se muestra en cada tarjeta con su aporte en unidades del dato, pero **no sustituye** la estimación publicada mientras su estado sea `NONE`.

**Límites.** Los objetivos son la última versión revisada de FRED (las primeras publicaciones requieren ALFRED con clave). La estimación es `PRELIMINARY` mientras falten sesiones del DTS hasta el corte previsto. `data/bridge/dts_daily_series.json` guarda las cuatro series diarias desde 2014; el refresco diario añade solo las fechas nuevas. El flujo manual «DTS bridge — full history rebuild» reconstruye todo el historial.

## v7.1 — Consenso automático desde G8 RadarNews

El consenso ya no es manual. Cada ejecución lee `public/data/radar_news_full.json` del repositorio `g8-radar-news` (calendario de ForexFactory, refrescado cada 5 minutos por la Mesa Macro) y lo asocia a cada tarjeta solo si coinciden:

- el título del evento USD (`Non-Farm Employment Change`, `Unemployment Rate`, `Unemployment Claims`, `Retail Sales m/m`, `CPI m/m`, `Core CPI m/m`, `Core PCE Price Index m/m`, `Industrial Production m/m`, `Housing Starts`, `Trade Balance`);
- la fecha de publicación en Nueva York con la fecha verificada de FRED de la tarjeta.

La unidad se convierte de forma explícita (K, M y B a las unidades del radar; un sufijo incompatible se rechaza). `captured_at` es la hora de generación del feed. El contrato existente se mantiene: mismo periodo y unidad, captura anterior al anuncio y antigüedad máxima de 7 días. Después del anuncio, el consenso deja de mostrarse. `data/consensus.json` conserva prioridad si contiene una entrada. El archivo diario de previsiones guarda la tarjeta con su consenso, así que el registro para medir el sistema frente al mercado se acumula solo.

## v8 — Pulso fiscal → economía

Panel principal del dashboard: responde a «¿la economía va mejor o peor que hace un año?» con la caja del Tesoro.

**Método.** Para cada partida se toma el importe oficial acumulado del año fiscal (FYTD) y del mes (MTD) del DTS y se compara con el **mismo número de sesiones** del año anterior (no con sumas de calendario). Las partidas de renta (retenciones, sociedades, autónomos, salarios federales) se muestran también **descontando la inflación** (IPC interanual de FRED). Un cambio de menos de ±3 % (o de ±25 mil millones en emisión neta) se considera «sin cambio». El MTD no se muestra hasta tener 10 sesiones, porque al inicio del mes dominan los desplazamientos de fechas de pago. Las barras comparan cada mes natural completo con el mismo mes del año anterior; un mes con alguna sesión sin dato no se calcula.

| Bloque | Partidas DTS | Alimenta |
|---|---|---|
| Empleo y desempleo | Retenciones IRPF/FICA, prestaciones DOL, SNAP, salarios federales | NFP, tasa de paro, solicitudes |
| Consumo y ahorro | Devoluciones a hogares, TSP aportaciones y retiradas | Ventas minoristas, tasa de ahorro |
| Crecimiento y beneficios | Impuesto de sociedades, renta no retenida/SECA (electrónica + otros) | PIB |
| Sector exterior | Aduanas | Importaciones, balanza comercial |
| Deuda y tipos | Emisión neta (IIIB), intereses de títulos del Tesoro | Rendimientos 2 y 10 años |
| Gasto público | Medicare A/B/D, Medicaid, HHS varios | Déficit, activos financieros netos |

**Semántica.** Verde = mejor que hace un año para la economía (por ejemplo, menos prestaciones o menos SNAP); rojo = peor; ámbar = más presión fiscal o sobre tipos (sin juicio de bueno/malo: en lectura MMT, más intereses y más gasto también son más ingreso del sector privado); gris = sin cambio. El veredicto de cada bloque cuenta las partidas a favor y en contra.

**Límites.** Es una lectura de tendencia, no la cifra del próximo dato (el puente v7 mide eso y hoy no muestra valor añadido). Cada partida lleva su cautela: estacionalidad de devoluciones, pagos trimestrales de sociedades y autónomos, aplazamientos del IRS por desastres, aranceles en aduanas desde 2025, fechas de cupón en intereses, nóminas quincenales en salarios federales. `data/fiscal_pulse.json` caduca con el libro de caja; `argos_summary.json` incluye `fiscal_pulse` con `basis: dts_vs_same_session_last_year_not_forecast`.

## v8.1: events retirado de argos_summary; las tarjetas viven solo en macro_radar.json, consumidor IRIS

El productor de `data/argos_summary.json` publica `v` 2 (una unidad por encima del contrato anterior). Las claves son `v`, `at`, `expires`, `dts`, `basis`, `probabilities` y `fiscal_pulse`.
