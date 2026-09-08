# TaxiTips — handoff för en kodagent

Läs den här filen först. Den är verktygsneutral (Cursor, Antigravity, Claude
Code, vad som helst) och beskriver var systemet står, hur det körs, och
vilka regler som inte får brytas. `CLAUDE.md` innehåller uppdragsgivarens
ursprungliga briefing och prioritetsordning; den här filen är dagsläget.

Språk: koden och dokumentationen är på svenska. Behåll det. Fältnamn från
externa API:er skrivs som de heter i API:et (`AdvertisedTimeAtLocation`,
inte "annonserad tid").

---

## 1. Vad produkten svarar på

En taxiförare, mitt i ett pass: *"var finns det folk som behöver taxi nu,
varför tror ni det, och är det värt att köra dit?"*

Affärsmodellen är B2B: taxibolag betalar en Stripe-prenumeration, förare
går med via en bolagskod. Ingen App Store-prenumeration, ingen IAP.

## 2. Var koden ligger

```
taxitips-backend/   Django. Hämtning, klassificering, poängsättning, förar-API. Tyngdpunkten.
taxitips-app/       Flutter. Förarappen (iOS/Android) plus adminläge.
taxitips-api/       Supabase (auth, bolag, enheter, Stripe) + den GAMLA Node-workern.
taxitips-web/       Marknadssajt + admin/bolagsportal.
taxitips-pipeline-viz/  Läsvy över hela pipelinen på localhost:4000. Tänkverktyg, inte produkt.
docs/               Mätningar och research. Se §5.
```

**Node-workern (`taxitips-api/worker`) pensioneras.** All pipelinelogik är
portad till Django. Rör den inte utan skäl; den finns kvar för jämförelse.

## 3. Dataflödet, hela vägen

```
sex källor          → source_events → klassificering → poängsättning → opportunities → /api/alerts → appen
(Trafikverket järnväg,  (rå payload)   taxi_relevance    scoring.py        (tipset)      core/api.py
 Trafikverket väg,                     text_scoring      thresholds.py
 SL, Västtrafik,                       mode.py           compensation.py
 Trafiklab, SMHI)                                        alternatives.py
```

Nyckelmoduler i `taxitips-backend/core/`:

| Fil | Ansvar |
|---|---|
| `sources/*.py` | En adapter per källa. Normaliserar till EN gemensam larmform. |
| `taxi_relevance.py` | Är det här taxirelevant alls? Ger score/level/places. |
| `text_scoring.py` | Färdsättsmedveten allvarlighetsgrad (tier) för textkällor. |
| `scoring.py` | Järnvägens strukturella klassificerare (nästa avgång, sista avgången). |
| `thresholds.py` | **Alla tröskelvärden.** 50, 150 km, 24 h. Ändra här, ingen annanstans. |
| `alternatives.py` | "Vad gör resenären i stället?" — nästa avgång + ersättningstrafik. |
| `compensation.py` | Lagstadgad förseningsersättning per län. |
| `coverage.py` | Vilka län vi hämtar från, och varför inte de andra. |
| `health.py` | Bokför varje hämtning i `SourceStatus`. |
| `api.py` | Förar-API:t. `feed_for()` är urvalslogiken. |
| `repository.py` | Rå SQL-upsert. Läs kommentaren om `notified_at` innan du rör den. |

## 4. Kör lokalt

```bash
colima start
cd taxitips-api && supabase start                       # Postgres på 54322
cd ../taxitips-backend && ./.venv/bin/python manage.py runserver 8000
cd ../taxitips-pipeline-viz && node server.js           # http://localhost:4000
cd ../taxitips-app && flutter run --dart-define=API_BASE_URL=http://127.0.0.1:8000
```

I Chrome: lägg till `-d chrome --web-port 5180` plus
`--dart-define=SUPABASE_URL=http://127.0.0.1:54321` och
`--dart-define=SUPABASE_ANON_KEY=<PUBLISHABLE_KEY ur supabase status>`.
Konton, bolag och prenumerationer fylls av
`manage.py seed_local_demo --service-key <supabase service_role>`: tre bolag
(trial, betalande, uppsagt), fem konton, sex förartokens. Det uppsagda
bolaget finns för att "obetalt" och "pipelinen hittade inget" annars ser
identiska ut på skärmen. Exakta kommandon och inloggningar i `DEV.md`.

Fyll databasen (en källa per kommando):

```bash
cd taxitips-backend
./.venv/bin/python manage.py poll_rail
./.venv/bin/python manage.py poll_road
./.venv/bin/python manage.py poll_sl --skip-sites
./.venv/bin/python manage.py poll_vasttrafik --skip-sites
./.venv/bin/python manage.py poll_trafiklab
```

Alla stöder `--dry-run`. Utan `--skip-sites` uppdateras hållplatsregistret
(~18 000 rader, tar en stund). Kör det efter `supabase db reset`.

Tester — båda ska vara gröna innan något deployas:

```bash
cd taxitips-backend && CELERY_TASK_ALWAYS_EAGER=1 ./.venv/bin/python manage.py test   # 217
cd taxitips-app && flutter test && flutter analyze                                     # 23, rent
```

API-nycklar ligger i `taxitips-backend/.env` (ogitad). `.env.example`
listar alla och vad de gör.

## 5. Var sanningen finns

Läs dessa innan du gissar om en datakälla. De är mätta, inte antagna.

| Fil | Innehåll |
|---|---|
| `docs/api-field-inventory.md` | Sex källor, fält för fält, mätt ifyllnadsgrad, 19 förslag (tio genomförda). |
| `docs/transit-compensation-rules.md` | Ersättningsregler per län, ordagranna citat, källänkar, hämtdatum. |
| `docs/data-sources.md` | Endpoints, auth, kvoter, vilka operatörskoder som finns. |
| `taxitips-backend/schema/` | **Genererad** av `manage.py dump_truth`. Redigera aldrig för hand. |
| `TAXITIPS_STATUS.md` | Vad som faktiskt fungerar, med datum. §0 är nyast. |

Kör `manage.py dump_truth` efter varje migration och checka in resultatet.
`schema/functions.sql` finns för att `get_smart_alerts` är omdefinierad sju
gånger i migrationsmappen — filen visar vilken version som gäller.

Båda vyerna finns också på **http://localhost:4000** (avsnitt 6c, 14 och 15),
renderade från samma filer.

## 6. Invarianter — bryt inte dessa

Var och en av dem är skriven efter att ha gått sönder på riktigt.

1. **`notified_at` skrivs BARA av push-steget.** Djangos `save()` skriver
   hela raden och skulle nolla fältet varje pollcykel → varje förare får
   samma notis varje minut. Skriv tips via `repository.upsert_opportunities()`,
   aldrig `.save()`. Vaktas av `test_notified_at_survives_upsert`.
2. **Vi hittar aldrig på ett alternativ eller en koordinat.** En förare som
   kör till en perrong där ersättningsbussen redan står gör en bomresa. Tomt
   fält kostar ingenting. Samma sak för `cap_per_person`: nio huvudmän
   skriver inte ut om taket gäller per resenär, och då säger appen inget.
3. **Vägtipsen är kapade till 15 poäng och ligger i `context`, inte i
   tipslistan.** En kö försenar dem som redan sitter i bil. Mätt: 129
   vägrader mot 5 kollektivtrafiktips i Skåne.
4. **`is_last_departure` sätts aldrig av en textkälla.** SL:s
   departures-endpoint svarar bara för ett fönster framåt; "inga fler
   avgångar" betyder "inga inom två timmar", inte "sista turen idag".
5. **`region` är NULL, aldrig tom sträng, när marknaden är okänd.**
   `feed_for()` gör `coalesce(region,'skane')` för tips utan koordinat — en
   tom sträng hade matchat ingen marknad och tipset försvunnit tyst.
6. **Entitlement har TVÅ vägar**: förartoken och inloggad ägare via
   Supabase-JWT. Att bara ta med den första låser ute varje ägare utan parad
   enhet, och det ser ut precis som "inga störningar just nu". JWT:n kan vara
   **ES256** (moderna Supabase-projekt signerar asymmetriskt med en roterande
   nyckel från JWKS) eller HS256 mot den delade hemligheten -- stödet för
   bara det senare släppte igenom noll inloggade ägare.
7. **Tröskelvärden bor i `thresholds.py`.** Talet 50 fanns i fyra kopior i
   tre språk. `severity_labels.dart` har en kvar, som dokumenterad fallback
   för cachead data utan `level`. Lägg inte till en femte.
8. **Migrationer följer expand → migrate → contract.** Aldrig destruktivt i
   samma deploy som koden som slutar använda kolumnen. `pg_dump` före
   migration mot produktion, alltid.
9. **AI-granskningen får bara sänka poäng** (`min(regel, modell)`), klämt
   både i `genkit.py` och i `RailAssessment.save()`.
10. **Ett tips ska alltid gå att förklara**: vilka `source_event_ids`,
    vilken regel, vilken konfidens.

## 7. Fällor i datan (de dyraste)

Fullständig lista i `docs/api-field-inventory.md` §9.

- **WGS84 är lon-först** i `TrainStation` och vägens `Situation` — men
  **lat-först** i `OperativeEvent`. Återanvänd inte `parse_point()` blint.
- **Västtrafiks koordinater är SWEREF99TM i meter**, inte grader.
- **Publiceringsfönster ≠ störningens längd.** SL:s `publish` har median 53
  dygn, Trafiklabs `active_period` 45. Visa dem aldrig som "pågår till".
- **SL:s `/departures` svarar med nakna tidsstämplar** medan deviations
  svarar med tidszon. Lokalisera till Europe/Stockholm före jämförelse.
- **Trafikverkets `PublicationTime` är inte starttiden.** Använd
  `Deviation.StartTime` (medianfel annars: 862 timmar).
- **`TrackAtLocation = "x"`** betyder att stationen saknar spårnumrering.
- **En tom källa och en död källa ser likadana ut** i `source_events`.
  Därför finns `SourceStatus` — kolla den innan du felsöker "inga tips".

## 8. Var arbetet står

**Klart:** pipelinen (sex källor, nationellt), förar-API:t, appen läser från
Django, feedback (🚕/👍/👎), källhälsa, täckningsvy, nästa avgång +
ersättningstrafik, ersättningsregler för 16 län, API-inventering.

**Näst på tur** — ur `docs/api-field-inventory.md`, som har mätningen bakom
varje punkt:

| # | Vad | Varför |
|---|---|---|
| 5 | Läs hållplats + klockslag ur SL:s fritext | 21 av 25 agerbara larm; ger koordinater åt Stockholmstips som idag är platslösa |
| 18 | Ta reda på vad `Deviation.Suspended` betyder | `true` på 65% av väghändelserna; om det betyder "vilande" visar vi hundratals pausade vägarbeten som pågående |
| 10 | Trafiklabs `route_id` bär SCB-länskoden | ersätter ortnamnsregex med strukturerad data |
| 11, 12 | Västtrafik: riktning och reservgeokodning | `affectedLines[].directions` finns på 92%, dagens fält på 7% |
| 15, 16 | SMHI: sikt som signal, och väder vid rätt tidpunkt | dimma fångas inte av dagens trösklar |
| 17 | `OperativeEvent` för orsakstext | enda riktiga *varför*-texten i hela flödet |

**P0, orört** (se `TAXITIPS_STATUS.md` §7): workern kör på
`SUPABASE_SERVICE_ROLE_KEY`, inga verifierade backuper, ingen push-pipeline,
dubbla Stripe-webhookhanterare.

**Kända luckor som inte går att koda bort:** Halland, Sörmland, Jämtland,
Västerbotten och Norrbotten saknas i Trafiklabs ServiceAlerts (404, inte
tomt svar). Västtrafik täcks av en egen adapter eftersom `vt` också 404:ar.
Järnväg och väg täcker däremot hela landet.

## 9. Arbetssätt som fungerat här

- **Mät innan du tror.** Nästan varje bugg i den här kodbasen såg ut som
  saknad data och var felläst data. Hämta ett stickprov och räkna.
- **Ett tomt fält är ett svar.** Skriv "inte verifierat" hellre än en siffra
  du inte kan belägga.
- **Skriv skälet, inte regeln.** Kommentarerna här förklarar varför en
  gräns ser ut som den gör, för att nästa läsare inte ska "förenkla" bort
  den. Fortsätt så.
- **Testa det som går sönder tyst.** Feedbacken var trasig i månader för att
  felet fångades av ett `catch` och tabellen stod på noll rader.
