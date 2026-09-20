# TaxiTips pipeline-viz

Ett fristående, read-only fönster in i datapipelinen. Ingen inloggning, inget
auth, körs bara på localhost. Syftet är att kunna se **helheten** på en sida:
vilka datakällor som finns, vad som händer med datan i varje steg, och vad
föraren faktiskt får se i slutändan.

Detta är medvetet **separat** från `taxitips-api` och `taxitips-app` — det är
ett tankeverktyg, inte en del av produkten. Det skriver aldrig något.

## Kör

```bash
cp .env.example .env
# klistra in VIZ_SERVICE_KEY från Coolify -> taxitips-worker -> Environment Variables
node server.js
```

Öppna http://localhost:4000

## Sidorna

Mot Django (`VIZ_BACKEND=http://127.0.0.1:8000 node server.js`) har varje tjänst en egen sida:

| Sida | Innehåll |
|---|---|
| `/` | Översikt: färskhet och vad föraren får, per tjänst |
| `/tag`, `/kollektivtrafik`, `/vag`, `/flyg`, `/vader`, `/evenemang` | `service.html`: källorna, analysstegen, sorter och regler, och vad föraren får med varför. Ett tips öppnar hela kedjan från rådata till notisbeslut. |
| `/farjor` | Färjeankomsterna (tidtabell + AIS), sorterade för taxiföraren |
| `/system` | Den gamla helsidan: lanseringsläge, FCM-test, täckning, ersättningsregler |

Data kommer från `/api/pipeline/services`, `/api/pipeline/service/<tjänst>` och
`/api/pipeline/tip/<id>` i Django (`core/service_view.py`), som alla bara svarar med DEBUG.

## Varför den failar högljutt

Supabase svarar på count-queries med tomt resultat i stället för fel när
nyckeln inte gäller. Utan en explicit probe skulle sidan ha renderat en
självsäker dashboard full av nollor — värre än ett felmeddelande, eftersom det
ser ut som riktig data. `server.js` gör därför en testläsning först och visar
ett tydligt fel om nyckeln inte funkar.
