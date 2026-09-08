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

## Vad sidan visar

1. **Flödet** — källa → source_events → scoring → opportunities → app/push
2. **Datakällor** — Trafiklab, Trafikverket, SMHI, GTFS static: vad var och en
   ger, hur ofta den hämtas, och vad den faktiskt används till
3. **Bearbetningen** — de sex stegen från rå payload till poäng, med
   poängtaket per severity_tier
4. **Live-fördelning** — hur de aktiva opportunities just nu fördelar sig
   över severity_tier
5. **Ett spårat exempel** — en verklig störning hela vägen: rå källdata →
   klassificering och poäng → vad föraren ser på kortet
6. **Vad som inte fungerar än** — ärliga luckor (GTFS static-matchning,
   Västtrafik, vägsignaler som nollas ut på avstånd)

Punkt 4 och 5 hämtas live från produktionen; resten är beskrivningar av
pipelinen som uppdateras för hand när koden ändras.

## Varför den failar högljutt

Supabase svarar på count-queries med tomt resultat i stället för fel när
nyckeln inte gäller. Utan en explicit probe skulle sidan ha renderat en
självsäker dashboard full av nollor — värre än ett felmeddelande, eftersom det
ser ut som riktig data. `server.js` gör därför en testläsning först och visar
ett tydligt fel om nyckeln inte funkar.
