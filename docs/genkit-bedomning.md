# Linje, hållplats och "Därför" på varje tips — regler först, Genkit för resten

*2026-10-09. Kod: `core/tip_text.py`, `core/places_ai.py`, `core/ingest.py`,
`core/api.py`. Mät: `manage.py measure_places --hours 24 [--replay]`.*

## 1. Problemet, mätt

Produktion, senaste dygnet (2026-10-08), `kind=transit`:

| Källa | Tips | Utan `places` | Utan `factors` |
|---|---:|---:|---:|
| SL | 3 316 | 3 096 | 1 850 |
| Östgötatrafiken | 426 | 338 | — |
| Värmlandstrafik | 641 | 110 | — |
| Skånetrafiken | 458 | 221 | — |

Informationen står nästan alltid i texten: *"Förseningar upp till 10 minuter
för buss linje 725 från Tumba station 16:58 mot Söderby park"*, *"Avgången från
Karolinska sjukhuset norra kl 16:01 till Sollentuna station är cirka 9 minuter
försenad"*. Trafikbolagen skriver efter ett tiotal mallar.

**Varför 1 850 SL-tips saknade "Därför":** `core/ingest.write` satte
`factors = []` för varje tips med `severity_tier=ignore` ("Övrigt": hissar,
flyttade hållplatser, avklarade störningar). De visas ändå längst ner i listan
(`api._shown_tips`), utan en enda rad. Alla icke-övriga fritexttips hade redan
minst en rad från regeln — men en allmän ("Bussen är försenad"), utan siffror.
Historiken (`/api/alerts/history`) tömde dessutom raderna för avslutade tips.

## 2. Arkitekturen

```
källa → ingest.assess ──► tip_text.extract (regler, varje tips, 0,08 ms/text)
                     │      linje · hållplats · mål · avgångens klockslag · försening
                     ├──► places_ai.facts_for(rule_key)  ← sparad modelläsning för samma text
                     ├──► tip_text.registry_coords       ← koordinat BARA ur registret
                     ▼
          ingest.write: line, station, destination, places (om tomt), factors, rule_key
                     │
beat "read-places" (2 min) ─► places_ai.run: tips där reglerna saknar linje
                     eller hållplats, eller confidence=low → EN Genkit-läsning per text
```

1. **Regler först, gratis** (`core/tip_text.py`). Linjen ur SL:s/Västtrafiks
   linjefält eller ur texten ("buss linje 725" → "Buss 725", "Västtågen 3104" →
   "Västtåg 3104", "tunnelbanans gröna linje", "Lidingöbanan 21"). Hållplatser ur
   "från X", "mellan X och Y", "X - Y kl", "vid X", "Linje 2 X, Ort kl", målet ur
   "mot Y" / "från … till Y". Varje namn är en ordagrann delsträng av texten.
   Hänvisningar ("Hänvisning till hållplats Z", "på Tornavägen") räknas inte —
   det är ersättningshållplatsen, inte där störningen är.
2. **Koordinater bara ur registret** (invariant 2). Hållplatsens exakta namn
   (efter normalisering: "Tumba station" → "Tumba") i `stop_area` för tipsets
   eget bolag (SL/Västtrafik) eller i `rail_station`, och bara inom tipsets län.
   Två träffar längre isär än 1,5 km ("Mörby" i Danderyd och Nynäshamn) ger
   ingen koordinat. Modellen ger aldrig en koordinat.
3. **Genkit bara för resten** (`core/places_ai.py`). Samma faktaläsning som
   granskningen (`TipFacts`, nu med `lines` och `stops`). `tip_facts.sanitize`
   kastar varje linje, hållplats, klockslag och försening som inte står i texten.
   **En läsning per text**: nyckeln är `rule_key = sha1(rubrik + beskrivning)`,
   och läsningen sparas i `ai_facts` + `ai_rule_key` på varje rad med texten. SL:s
   tre rader per meddelande kostar ett anrop. Insamlingen hämtar läsningen varje
   pollrunda, så den överlever upserten (designen från migrering 0033).
4. **Reglerna sätter poängen** (invariant 9). Läsningen fyller bara linje,
   hållplats, mål och "Därför"-rader. För `confidence=low` räknas poängen ur
   faktan med `classify_from_facts` — med `AI_RAISE_CAP` och `ai_adjusted_at` som
   förut. Granskningen (`review_uncertain`) återanvänder en läsning av samma text
   i stället för att anropa igen, och tvärtom.
5. **Ordning och tak:** medel/starka tips först, sedan nyaste; högst
   `AI_PLACES_MAX_PER_RUN` (20) texter per körning; `ai_client`:s minut-, dygns-
   och månadstak, felpaus och backoff per text (`retry_allowed("places", …)`).
   `TAXITIPS_AI=off` eller `TAXITIPS_BEAT_DISABLE=read-places` stänger av.

## 3. Enhetlig bedömning: minst en rad "Därför" på varje tips

Raderna (`factors`) byggs deterministiskt, med trafikbolagets egna siffror:

| Läge | Rader (exempel) |
|---|---|
| Försening med minuter | "Avgång 16:58 från Tumba station", "Bussen är upp till 10 min försenad" |
| Inställd avgång | "Avgång 07:12 från Malmö C är inställd", "En enstaka avgång – nästa brukar gå snart" |
| Hela linjen | "Hela linjen står still" (+ omständigheter: tid, väder, ersättning) |
| Känt glapp (SL) | "Nästa avgång går först 40 min senare" |
| Övrigt (`ignore`) | En rad om varför: "Hållplats eller anläggning – inte en körning" |

En rad med minuter ersätter lägets allmänna "Bussen är försenad". Varje siffra i
en rad står i källtexten (`test_every_number_in_a_reason_is_in_the_text`).
Historiken visar nu raderna även för avslutade tips.

## 4. Budget

`ai_call` lokalt (eval mot facit, Flash-Lite): 139 lyckade anrop, i snitt
**655 tokens in, 133 ut ≈ 0,00053 USD ≈ 0,005 kr per anrop**. Produktionens
siffra 9 116 anrop ≈ 0,386 USD (`bearbetning-optimeringar.md` §3) är lägre per
anrop eftersom de flesta misslyckades utan tokens.

Volym: ~825 unika kollektivtrafiktexter per dygn (mätt 2026-10-04). På den lokala
datan (5 562 unika texter) läser reglerna linje och hållplats i alla utom 26 %
av de icke-övriga — och de flesta av dem är `confidence=low`, som granskningen
redan läser i dag. Det nya är ~11 % av texterna.

| Syfte | Anrop/dygn (uppskattat) | kr/dygn |
|---|---:|---:|
| `places` (nya: saknad linje/hållplats, delat med `extract`) | ≤ 215 | ≤ 1,1 |
| `extract` (granskningen) | ≤ 300 | ≤ 1,6 |
| `brief` (bara notiskandidater) | ≤ 300 | ≤ 1,6 |
| `gate` + `report` | ≤ 100 | ≤ 0,5 |
| **Summa** | **≤ ~900** | **≤ ~5 kr ≈ 150 kr/mån** |

Hårda spärrar: `AI_MONTHLY_BUDGET_KR = 450` (under ägarens 500 kr), dagstak
`AI_DAILY_CALL_CAP` (3 000, env), minuttak `AI_MAX_CALLS_PER_MINUTE` (env).
Värsta fall — dagstaket varje dag — är 3 000 × 0,005 kr ≈ 16 kr/dygn; då slår
månadsspärren till vid 450 kr och reglerna gäller ensamma resten av månaden.

## 5. Vad ägaren gör

1. **Slå på fakturering** för Google Cloud-projektet som `GEMINI_API_KEY` hör
   till (AI Studio → API keys → projektet → *Set up billing*). Gratisnivån ger
   15 anrop/min och modell och svarar 429 `RESOURCE_EXHAUSTED` — i dag är
   AI-vägen i praktiken avstängd av kvoten.
2. Sätt en **budgetvarning** på 500 kr i Cloud Billing (dubbel säkring utöver
   `AI_MONTHLY_BUDGET_KR`).
3. Höj minuttaket i Coolify: `AI_MAX_CALLS_PER_MINUTE=60` (env på worker och
   beat), starta om workern. Dagstaket kan ligga kvar (`AI_DAILY_CALL_CAP`).
4. Kör `manage.py measure_places --hours 24` före och ett dygn efter, och
   `manage.py eval_ai --extraction` (modellen mot facit) när kvoten är öppen.

## 6. Mätning

`measure_places --replay` läser varje tips text om med dagens regler, utan att
skriva. Lokal databas (2026-09-20, 10 946 fritexttips; före = som raderna
skrevs, efter = dagens regler på samma texter, utan Genkit):

| Källa | plats före → efter | linje efter | hållplats efter | "Därför" före → efter |
|---|---|---:|---:|---|
| SL (deviations) | 7 % → 96 % | 100 % | 95 % | 84 % → 100 % |
| SL (Trafiklab) | 5 % → 56 % | 46 % | 55 % | 45 % → 100 % |
| Värmlandstrafik | 79 % → 100 % | 100 % | 99 % | 42 % → 100 % |
| Östgötatrafiken | 21 % → 95 % | 99 % | 10 % | 90 % → 100 % |
| Skånetrafiken | 52 % → 63 % | 33 % | 46 % | 60 % → 100 % |
| Västtrafik | 48 % → 97 % | 93 % | 96 % | 45 % → 100 % |
| **Totalt** | **36 % → 77 %** | **69 %** | **68 %** | **63 % → 100 %** |

Hållplats *med koordinat ur registret* (inte länets mittpunkt): SL 95 %, Västtrafik
95 %, UL 93 %, totalt 62 % — övriga län saknar hållplatsregister och får bara
Trafikverkets stationer.

"Före"-raderna för "Därför" skrevs innan `factors` fanns (2026-09-20) — i
produktion var de 1 850 tomma SL-raderna övrigt-tips. Resten upp till 100 % i
plats och hållplats är texter som inte namnger någon plats ("Försenad p.g.a.
tekniskt fel", Östgötatrafikens "bevakad linje"-avisering, hissar). SL via
Trafiklab och Skåne har låga tal för att majoriteten är övrigt-tips.

Facit: `core/fixtures/golden_extraction.jsonl` (32 verkliga texter, alla bolagens
mallar). Reglerna: 32/32 linje, 32/32 hållplats, 21/21 mål, 17/17 avgång,
13/13 försening (`eval_ai --extraction --rules-only`).

## 7. API-kontraktet

`core/api._serialize` (flöde, detalj, historik) har fyra nya fält:

| Fält | Exempel | Tomt när |
|---|---|---|
| `line` | `"Buss 725"`, `"Pågatågen 1612"` | linjen inte står någonstans |
| `station` | `"Tumba station"`, `"Malmö C"` | texten bara nämner målet, eller inget |
| `compensation_url` | huvudmannens sida om förseningsersättning | ingen källbelagd regel för tipsets huvudman |
| `compensation_source` | `"SL"`, `"Skånetrafiken"` | samma |

Länken är `RegionCompensationRule.source_url`, och namnet `source_name` (ny,
migrering 0034, fylld ur `docs/transit-compensation-rules.md` §3). Tågtips
följer produkten på tavlan (`compensation.rule_region_for`: Pågatågen → Skåne,
Öresundståg/Krösatågen → stationens län, SJ → ingen).
