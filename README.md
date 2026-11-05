# DTS Tracker — Fiscal Intelligence v6

[Dashboard](https://dts-tracker2026.netlify.app/) · [Methodology / Metodología](docs/METHODOLOGY.md) · [ARGOS feed](https://raw.githubusercontent.com/sanderdayan1982/dts-tracker/main/data/argos_summary.json)

## Español

Panel bilingüe inglés/español con diez estimaciones macro de investigación, caja diaria del Tesoro y siete indicadores oficiales de liquidez y tipos. El selector EN/ES cambia toda la interfaz y conserva la preferencia.

- **Radar:** anterior, estimación, periodo, banda de error, calendario, fuente y consenso opcional.
- **Caja del Tesoro:** identidades contables, TGA, financiación, residual de calendario y 400 días de historia.
- **Fed y liquidez:** reservas, activos, crédito bancario, RRP, tipos a 2/10 años y estrés financiero.
- **Cómo interpretarlo:** instrucciones, unidades, límites y salud de las fuentes.

Las estimaciones no son probabilidades de sorpresa. El consenso no se inventa. Los históricos revisados no demuestran ventaja frente a primeras publicaciones. Las nuevas previsiones se archivan para poder evaluar esa ventaja prospectivamente.

## English

A bilingual fiscal and macro research desk. Ten official-series research estimates, Treasury cash accounting and seven Fed liquidity/rates indicators. Research estimates compare with previous observations, not with an invented market consensus. Latest-vintage historical tests do not establish first-release trading performance.

## Run / Ejecutar

Python 3.11+; no third-party Python packages. Node 20+ for UI tests. No API key is required for the public sources used.

```sh
python3 -m unittest discover -s tests -v
node --test tests/test_ui.mjs
python3 scripts/build_dts_nowcast.py
python3 scripts/build_macro_radar.py
python3 -m http.server 8080
```

GitHub Actions refreshes public data and preserves failure states. The browser uses GitHub Raw plus the deployed data copy and enforces expiry independently. Direct scheduled data commits include `[skip netlify]`; code changes still deploy normally when Netlify is connected to `main`.

## Data contracts

- `data/dts_nowcast.json`: reconciled cash snapshot, endpoint dates and expiry.
- `data/dts_history_400d.json`: recent daily accounting history.
- `data/macro_radar.json`: full forecast cards, evidence and Fed context.
- `data/argos_summary.json`: compact agent contract; enforce global `expires` AND `dts.expires`.
- `data/sources/`: official retrieved observations, source hashes and timestamps.
- `data/forecast_archive/`: first daily forecasts by target and period; not rewritten.
- `data/consensus.json`: optional dated shared consensus configuration. See methodology for required fields.

Browser-entered consensus is local and does not alter ARGOS's shared inputs. A forecast point is never permission to trade.

## Treasury cash monitor / Monitor de caja

The first section retains daily, month-to-date and fiscal-year-to-date Treasury deposits and withdrawals, a stock-only closing TGA balance, and the original daily NTF mean/±1σ/±2σ overlays. Choose a fiscal year and as-of date; daily bars and cumulative official amounts remain distinct.

La primera sección conserva las entradas, salidas y el saldo del TGA. Incluye 18 partidas originales, conciliación exacta, cascada de caja, separación de financiación, persistencia de flujos, mapa de reservas y comparación fiscal. El radar macro permanece disponible mediante «Ir al radar macro».

`data/treasury_book.json` publishes 800 calendar days of retrieved Table-I history with official cumulative fields, Table-II selected categories and II/IIIB cash debt totals. Charts retain signed reversals and do not sum balances. The oldest fiscal year can be partial; the visible window is explicitly labeled.
