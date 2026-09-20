# TaxiTips inför lansering — P0-läget 2026-09-13

Allt nedan är gjort och provat **lokalt** (utvecklingsdatabasen i Docker, samma
Supabase-version som produktionen). **Inget är driftsatt, inget är committat.**
Produktionen har bara lästs, aldrig ändrats. Staging finns inte ännu.

Underlaget `TaxiTips-underlag-infor-lansering.md` hittades inte; bedömningarna bygger
på kod, Coolify, läsande databasfrågor och källvillkoren (se `docs/data-sources.md`).

---

## Kvarvarande lanseringsblockerare, i ordning

| # | Blockerare | Belägg | Åtgärd (kräver ditt beslut) |
|---|---|---|---|
| 1 | **Elva tabeller i produktionen är öppna för anon och authenticated**: RLS av och full rättighet (läsa, skriva, radera). Bland dem `push_delivery` (förartokens, som ger åtkomst till flödet), `scoring_rule`, `source_status`, `opportunity_favorite` och säkerhetskopiorna `_backup_opportunities_20260910` och `_backup_source_events_20260910`. | Läsande SQL mot produktionen: `pg_class.relrowsecurity`, `has_table_privilege`, `pg_default_acl` (Supabases standardrättigheter ger varje tabell `postgres` skapar full rättighet). Inte provat via PostgREST. | `pg_dump`, sedan migrationen `20260913000003_lock_down_django_tables.sql` (återkallar anon/authenticated, tar inte bort data; provad lokalt). Överväg att byta förartokens och se över PostgREST-loggarna. |
| 2 | **Stripe-webhooken tillämpar ingen händelse.** `constructEvent` kastar i Deno för varje anrop, även korrekt signerade. Dessutom: ett misslyckat försök togs aldrig om, ordningen kontrollerades inte, obetald checkout aktiverade bolaget, databasfel markerades "ok". | Lokalt i edge-runtime v1.74.3: HTTP 400 "SubtleCryptoProvider cannot be used in a synchronous context" på korrekt signatur. Produktionen kör v1.71.2 — inte provat där. | Migration `20260913000002_subscription_event_order.sql`, sedan driftsätt `functions/stripe-webhook`. Kontrollera med en testhändelse från Stripe. |
| 3 | **Databasens port 5432 är publik** (`is_public: true`). | Coolify `get_service supabase-taxitips`. Brandvägg framför ej kontrollerad. | Stäng porten eller begränsa med brandvägg. |
| 4 | **Ingen backup i produktionen.** | Inga schemalagda uppgifter, inga pg_cron-jobb; Coolifys backup-API når inte service-databasen. | Extern lagring + `ops/backup/backup.sh` som schemalagd uppgift, och ett återställningsprov på servern. |
| 5 | **Notiser kan inte skickas**: workern saknar `FIREBASE_SERVICE_ACCOUNT_JSON`; 0 enheter har push-token. | Coolify-miljövariabler, SQL. | Nyckel (och APNs i Firebase) i den miljö som ska skicka. Prova med en testtelefon. |
| 6 | **Ingen staging.** Allt P0 är provat lokalt. | Coolify har bara miljön `production`. | Skapa staging med egen databas innan produktionen rörs. |
| 7 | **Butiksgranskning**: integritetspolicy saknas (`/privacy` är platshållare), demokod till granskaren saknas, integritetsmanifestet är ett utkast. | `store/LISTING.md`, `ios/Runner/PrivacyInfo.xcprivacy`. | Skriv policyn, skapa demobolag, stäm av manifestet mot Firebase. |
| 8 | **Driftsättningsordning** för det som gjorts här (se nedan). | — | Följ ordningen; `backfill_areas` direkt efter migreringen. |
| 9 | Ticketmaster-avtal innan evenemang visas i den betalda appen (appen visar dem inte i dag). Rotera API-nycklarna som klistrades in i chatten, nu även ResRobot-nyckeln och de två nya Trafiklab-nycklarna. | Villkoren; konversationen. | Avtal; nya nycklar. |
| 10 | ~~Flödets kapacitet~~ **Löst lokalt (P1):** delad flödescache i 20 s per filter och avrundad position, ETag före uträkning. 100 anrop/s utan fel, p50 15 ms, p95 23–255 ms. | Lasttest nedan. | Mät om på servern; flera repliker sätter `CACHE_REDIS_URL`. |

**Driftsättningsordning** när det blir dags: (1) `pg_dump` av produktionen,
(2) Supabase-migrationerna `20260913000002` och `20260913000003`, (3) backend med
Django-migrationerna `0017`–`0019` och sedan `manage.py backfill_areas`,
(4) webhook-funktionen, (5) worker och beat (beat börjar köra `purge-old` varje timme:
gällande sjudygnsregel, i batchar), (6) ny appversion.

---

## Evidensmatris med utfall

| # | Område | Nuläge före | Ändring | Utfall (lokalt) |
|---|---|---|---|---|
| 1 | Färskhet lokalt | Ingen worker; `.env` har `CELERY_TASK_ALWAYS_EAGER=1`, så även `docker compose` kör beat i eager-läge | Körbok i AGENTS.md med eager av | Provat: worker körde 10 tasks, beat 0 |
| 2 | Hälsa | `/health` bara `select 1` | Beat-hjärtslag; `/health/pipeline`; `check_pipeline` | Stoppad beat → 503 efter **140 s** (`heartbeat_stale`); hjärtslaget skrivet av workern |
| 3 | Försök vs lyckad | Bara `checked_at` | `last_success_at`, `consecutive_failures`, gräns per källa | Tester; kärnkällor avgör, tillägg aldrig |
| 4 | Celery | Inga tidsgränser, inga lås | Mjuk/hård gräns per task, Redis-lås, utgångstid i kön | Lås: 2 överlappande `poll_road` hoppade över. **Fynd:** mjuka gränsen fångades av breda except (`otraf: SoftTimeLimitExceeded()`) — rättat i fem slingor |
| 5 | Vägpoll | Kapad vid 2 000 av ~3 500 | `skip`-sidor, stabil ordning, komplett-flagga | Live: **3 489 situationer på 4 sidor → 6 326 avvikelser** (förut 3 422) |
| 6 | Idempotens | Varje rad skrevs om varje runda | Oförändrade rader skrivs inte (kolumnjämförelse i stället för hash-kolumn); inget markeras borta efter kapad Ticketmaster-hämtning | Tester: oförändrad omkörning = 0 skrivningar |
| 7 | Gallring | `purge_old` fanns, kördes aldrig | Batchad, timvis i beat | Tester; inte kört mot någon riktig databas |
| 8 | Backup | Ingen | `ops/backup/` + körbok | Återställning i tom container: **61/61 tabeller, 59 076 rader lika**. Fynd: kräver `supabase_admin` och rollfil |
| 9 | DB-port | Publik | — | Blockerare 3 |
| 10 | Område utan GPS | Bara operatörsmarknader valbara; utan GPS och område kom hela landet | 21 län (Natural Earth, public domain), `county_code`/`area_codes` på tips med 25 km grannbuffert; flödet svarar `needsArea` | Tester inkl. kuststäder, färjelägen, Arlanda→Uppsala, Kiruna |
| 11 | Position i loggar | lat/lon i URL; ingen loggtvätt; Celery tar över loggningen | Header `X-TT-Position`, avrundad till 2 decimaler; `RedactFilter` på alla loggar inkl. worker | Tester (koordinater, tokens, nycklar, traceback) |
| 12 | iOS-behörighet | Text och manifest saknades | `NSLocationWhenInUseUsageDescription`, `PrivacyInfo.xcprivacy` i projektet | `plutil -lint` OK. Inte byggt på telefon |
| 13 | Notisbeslut | Utspridda grindar; inga områden = alla notiser | `decide()` med orsakskoder (`no_area`, `outside_area`, `unplaced_tip` …) | Tester per kod |
| 14 | Utkorg | Skick före bokföring, ingen retry/TTL | `pending → sending → sent/failed/expired`, lån, backoff, TTL 30 min, collapse key | Tester: krasch, lån, retry, utgång |
| 15 | Token | Nollades vid alla 400/404 | Bara `UNREGISTERED`, `SENDER_ID_MISMATCH`, ogiltig registreringstoken; felkoden läses ur hela svaret | Tester |
| 16 | Push i drift | Nyckel saknas | — | Blockerare 5 |
| 17 | Feed | Python-slinga över alla tips, ingen ETag, hämtning var 30 s; svaren 0,4–1,3 MB | SQL-förfilter, svag ETag/304, väghändelser i svaret kapade till 50; appen skickar If-None-Match, 60 s ± 10 s, pausar i bakgrunden | Svar 808 kB → 71 kB, 51–60 % 304 utan kropp. Kapacitet oförändrad ~45 svar/s, se lastresultat |
| 18 | Lasttest | — | `ops/loadtest/feed_load.py` (fast takt) | 50 och 100 anrop/s körda; se lastresultat |
| 19 | Platser | *Rättelse:* appen kan redan ta bort en telefon (radera raden); RLS i produktionen begränsar det till aktiva medlemmar | Ingen ändring behövdes | Läst i produktionen: `devices_delete_member` |
| 20 | Stripe-webhook | Se blockerare 2 | Asynkron verifiering, omförsök, ordning, betalstatus, felkontroll | **9/9 scenarier** mot lokal edge runtime |
| 21 | Butiksväg | Mobilappen öppnade Stripe Checkout | Registrering bara på webben; granskningsanteckning | `flutter analyze` rent, 30 tester gröna |
| 22 | Evenemang | — | Villkorstexter förtydligade (Ticketmasters 24 h = borttagning på begäran; PredictHQ undantar inte lokal testlagring) | — |

**Avvikelser från planen:** innehållshash blev en kolumnjämförelse i SQL (samma effekt,
ingen ny kolumn). En `revoked_at`-migration för platser skrevs och togs bort när
radera-vägen och RLS-policyn i produktionen visade sig räcka. P1 och P2 gjordes efteråt,
se *P1-läget* och *P2-läget* nedan.

---

## Verifiering

| Kontroll | Resultat |
|---|---|
| Backendtester | 644 gröna |
| Lasttest 50 och 100 anrop/s | Körda; kapacitet ~45 svar/s på två workers |
| Flutter | `flutter analyze` inga fel, `flutter test` 34 gröna |
| Integration Redis + worker + beat (inte eager) | Hälsa 503→200, lås, hjärtslag från worker, 503 efter stoppad beat |
| Vägpoll live | 4 sidor, inga dubbletter |
| Återställning | 61/61 tabeller, radantal lika |
| Stripe-webhook | 9/9 scenarier |
| Låsning av tabeller (lokalt) | anon/authenticated utan rättighet på `push_delivery` och `scoring_rule`; `devices` orörd; Django läser |
| iOS-filer | `plutil -lint` OK |

**Inte kontrollerat:** proxyloggar i Coolify, brandvägg framför 5432, iOS-bygge på
riktig telefon, APNs, riktiga Stripe-händelser i produktionen, feed-latens mot
produktionsdatabasen, om PostgREST i produktionen faktiskt serverar de öppna tabellerna.

---

## Lastresultat

Lokalt på en bärbar dator: gunicorn med två sync-workers (som i Dockerfile), `DEBUG=0`,
lastgeneratorn på samma maskin, 6 977 tips senaste dygnet (fler än produktionens ~4 080,
eftersom vägpollen nu hämtar alla situationer). Fast takt, 30 s per körning.

**Före** kapningen av väghändelser i svaret:

| Profil | Takt | p50 | p95 | Fel | Storlek |
|---|---|---|---|---|---|
| GPS | 50/s | 4,9 s | 8,5 s | 23 % | 808 kB |
| GPS | 100/s | 7,8 s | 9,0 s | 56 % | 459 kB |

**Efter** (`context` kapad till 50, `backfill_areas` körd):

| Profil | Takt | p50 | p95 | p99 | Fel | 304-andel | Storlek | CPU (två workers) |
|---|---|---|---|---|---|---|---|---|
| GPS | 50/s | 3,5 s | 7,8 s | 9,2 s | 11 % | — | 71 kB | 120 % |
| GPS | 100/s | 7,3 s | 7,8 s | 9,2 s | 46 % | — | 44 kB | 122 % |
| Län | 100/s | 3,8 s | 7,8 s | 8,8 s | 40 % | — | 50 kB | 111 % |
| GPS + ETag | 100/s | 7,6 s | 7,8 s | 9,4 s | 46 % | 51 % | 2 kB | 124 % |
| Län + ETag | 100/s | 3,9 s | 7,8 s | 8,7 s | 40 % | 60 % | 0 kB | 115 % |

**Tolkning**

- **Kapaciteten är ungefär 45 svar per sekund** i alla profiler. `feed_for` tar 15–125 ms
  per anrop (mätt direkt), och flödet räknas ut innan ETag jämförs -- ett 304 kostar
  därför samma CPU som ett fullt svar. Över kapaciteten svämmar anslutningskön över:
  "fel" är avvisade anslutningar, och p95 ≈ 7,8 s är TCP:s omsändning av
  anslutningsförsök, inte långsamma svar.
- **Kapningen och ETag gav bandbredd, inte kapacitet:** 808 kB → 71 kB per svar, och
  51–60 % 304 utan kropp när appen skickar tillbaka sin ETag.
- **50 anrop/s motsvarar ungefär 3 000 förare med appen öppen samtidigt** (en hämtning
  per minut). 300 förare är ~5 anrop/s. Två workers räcker för de första kunderna, inte
  för 3 000 förare -- se blockerare 10.
- Siffrorna är från en bärbar dator med lastgeneratorn på samma maskin och macOS
  standardkö för anslutningar. De ska göras om på den riktiga servern.

---

## P1-läget 2026-09-14

| Steg | Läge | Belägg |
|---|---|---|
| Flödescache (kapacitet) | Klar lokalt | Fast takt, två workers: se tabellen nedan |
| AIS-pilot, Visby och Värtahamnen | Kod klar; livekörningen gav inga anlöp (se *P2-läget*) | `run_ais_pilot`: register med tre fartyg sedda i AIS (DROTTEN, GOTLAND, SILJA SERENADE), en MMSI-filtrerad anslutning, positionsbuffert, kajtid med redovisad grund (sträcka/fart eller AIS-ETA, aldrig blandat) och iland-fönster separat; varje anlöp i `ferry_calls`. Första 15 minuterna live: ansluten, 2 positioner, inget anlöp (fartygen låg still) |
| Positionsbuffert i `run_ais_stream` | Klar | Test: en färja som saktar in innan typen hörts blir nu en ankomst |
| Nästa avgång | Klar lokalt via ResRobot (2026-09-15) | Se *Järnväg och nästa resa*. Trafiklab Realtime APIs saknar fortfarande nyckel |
| Evenemang med rättighetsreferens | Klar | `events/rights.py`: lagring och visning i appen kräver både brytare och referens. Standard: Ticketmaster lagras enligt villkoren men visas inte i appen; PredictHQ varken lagras eller visas |
| Kommun som förfining av län | Klar i backend och app | Län och 290 kommuner från SCB Digitala gränser (CC0) i stället för Natural Earth; kontrollpunkter Stockholm, Göteborg, Malmö, Kiruna, Visby, Arlanda, Umeå, Uppsala i rätt kommun |
| Genkit som textolkare | Spärr klar | Prompten bär inga förar-, bolags- eller positionsuppgifter (test). En AI-höjning får synas i listan men aldrig ensam väcka en telefon (`ai_only`); pipelinens nästa skrivning återställer regelvärdena |

**Lasttest efter flödescachen** (samma förutsättningar som ovan):

| Profil | Takt | p50 | p95 | p99 | Fel | 304-andel | CPU |
|---|---|---|---|---|---|---|---|
| GPS | 50/s | 15 ms | 17 ms | 54 ms | 0 % | — | 29 % |
| GPS | 100/s | 15 ms | 23 ms | 65 ms | 0 % | — | 55 % |
| Län | 100/s | 15 ms | 98 ms | 253 ms | 0 % | — | 57 % |
| GPS + ETag | 100/s | 17 ms | 97 ms | 124 ms | 0 % | 100 % | 57 % |
| Län + ETag | 100/s | 18 ms | 255 ms | 366 ms | 0 % | 100 % | 58 % |

## P2-läget 2026-09-14

| Steg | Läge | Belägg |
|---|---|---|
| Kombinationslagret | Klar lokalt; påverkar listan, inte notiserna | `core/combine.py`, jobbet `combine_signals` var 60:e sekund. Tre regler med regel-id och skälrad: `combo.duplicate` (samma färdsätt från två källor inom 400 m med överlappande tid visas som en rad, och den andra källan står som skäl), `combo.hub` (störningar i olika färdsätt inom 400 m, +5) och `combo.arrival` (flyg- eller färjeankomst medan kollektivtrafik inom 2 km står still, +10). Ett tips med utskrivet alternativ förstärks aldrig, och väghändelser kombineras inte. Live lokalt: 4–5 dubbletter (Skånetrafiken och Trafikverket om samma inställda tåg), inga knutpunkts- eller ankomstpåslag. Påslagen är okalibrerade och når därför inte notisbeslutet |
| "I tjänst": personliga platsnotiser | Klar i backend och app; inte provad på telefon | `core/presence.py`, `GET/POST /api/presence`, brytare i notisinställningarna. Servern sparar bara rutan (0,05° × 0,1°, ungefär 5 km) på enhetens enda rad. Raden gäller 30 minuter och gallras var femte minut; av tar bort den direkt. Appen förnyar högst var femte minut och bara från skärmens hämtning, som inte körs i bakgrunden. Så länge rutan gäller ersätter den körområdet i `decide()`: `near_driver` inom 30 km, annars `too_far_from_driver`. Svaret innehåller aldrig rutan (test). Integritetsmanifest och butikstext anger nu grov plats som kopplad till enheten |
| Kalibrering och analys | Rapporten klar; underlag saknas | `core/calibration.py`, `manage.py calibration_report` och ett kort i avsnitt 0b: feedback per regel och poängband (träffkvot 👍 / (👍 + 👎)), utkorgens status och tider, AIS-anlöp med förvarning och fel i kajtid. Rapporten flyttar inga trösklar och säger ut när underlaget är för tunt (under 20 utfall). Lokalt nu: 0 feedbackutfall, 27 skickade rader från tidigare simuleringar, 0 anlöp — inget att kalibrera. Gallringen tar feedback efter sju dygn tillsammans med tipsen, så fönstret är högst en vecka tills aggregat sparas |
| AIS-pilot, livekörning | Körd, 0 anlöp | Se nedan |

**AIS-piloten live, 2026-09-14.** Körd 07:04–18:07 lokal tid på den här datorn med en
MMSI-filtrerad anslutning (DROTTEN, GOTLAND, SILJA SERENADE). Resultat: 24
positionsmeddelanden och 2 statiska, **0 anlöp i `ferry_calls`**, 0 tips. Anslutningen
stängdes 14 gånger utan close frame och återanslöts varje gång.

1. `--duration 12600` (3,5 h) avslutade inte körningen. Asyncios tidsgräns går på den
   monotona klockan, som på macOS står still medan datorn sover. pmset-loggen visar 44
   insomningar under fönstret. Rättat: körtiden stäms av mot väggklockan var 30:e sekund
   (test).
2. Körningen säger därför inget om AISStreams täckning vid Visby och Värtahamnen: hur
   länge anslutningen faktiskt lyssnade går inte att fastställa. Kajtid och iland-fönster
   (+10/+45 min) är okalibrerade. Nästa steg är minst en veckas körning på en server som
   inte sover (staging), sedan `calibration_report`. Inga AIS-tips i produkten innan dess.

Inget av P2 är driftsatt. Rutan i "I tjänst" är en ny personuppgift på servern; den
behöver stå i integritetspolicyn (blockerare 7) innan funktionen släpps.

## Järnväg och nästa resa 2026-09-15

Utlöst av en jämförelse: avbrott.se visade 87 inställda tåg, vår sida betydligt färre.

| Fynd | Belägg | Ändring |
|---|---|---|
| Rälspollen såg ungefär en fjärdedel av avgångarna | Dagtid 14 000–15 000 avgångar i 8 h-fönstret mot `limit="4000"`. Natten mot 15/9 fanns 13 av 77 kommande inställda tåg i svaret | Två sidindelade frågor (störda avgångar; avgångar vid drabbade stationer) med komplett-flagga. Live: 54 av 54 unika inställda tåg, 2 sidor, 2,4 s |
| Tips är inte samma sak som inställda tåg | Ett tips per tåg vid första stoppet, en störning per station, 8 h framåt | Oförändrat. Pipeline-sidan visar nu unika inställda tåg bredvid antalet tips |
| "Nästa avgång" räknade tåg åt båda hållen | Lindome: nästa tåg från stationen kan gå mot Kungsbacka när det inställda skulle till Göteborg | ResRobot `trip` mot samma slutstation för inställda tåg utan ersättning, inom budget; annars som förut. Första liverundan: 7 svar på 20 anrop |
| ResRobot föreslog det inställda pendeltåget | SL:s pendeltåg bär linjenummer, inte tågnummer | Ett tåg inom 2 min från den inställda avgången räknas som samma tåg (test) |
| Ett ResRobot-fel kostar budget | Första rundan via beat: `INT_HAFAS_CONNECTION_ERROR` på 8 av 11 anrop, en minut senare normalt | Tre fel i en runda pausar anropen i 10 min, även nästa runda (test) |

Riktig körning via worker och beat 22:02 och 22:05: 52 unika inställda tåg, 27 tips, komplett på
2 sidor, 1,4-2,3 s. Svaren återanvändes (6 av 12 uppslag i andra rundan kostade inget anrop).
Stickprov mot Trafikverket: pendeltåg 2575 Kallhäll 22:10 mot Nynäshamn inställt, nästa avgång
mot Nynäshamn 23:10 -- ResRobot svarade 23:10, medan stationens nästa avgång hade sagt tio
minuter och menat tåget mot Bålsta.

Poängreglerna är desamma. Det som ändras är underlaget för "nästa avgång", och skälraden säger
"nästa resa mot X" när det kommer från ResRobot. Inget är driftsatt. Nyckeln behöver roteras och
sättas som miljövariabel i den miljö som ska köra (blockerare 9).

## Färjor på väg in, live (2026-09-18)

Pipeline-sidans avsnitt 2c visar stora passagerarfärjor i inseglingsområdena till 17 svenska
passagerarhamnar på en karta, med kurs, fart, sträcka kvar och beräknad ankomst. Den uppdateras
var 20:e sekund.

| Del | Läge | Belägg |
|---|---|---|
| Terminalregister | 17 hamnar: Helsingborg, Strömstad, Kapellskär, Grisslehamn, Oskarshamn, Varberg, Karlshamn, Malmö och Umeå är nya | Urval efter Trafikanalys, Sjötrafik 2024; terminalpunkter från OpenStreetMap |
| Inseglingsområden | Prenumerationen lyssnar på 16 områden i stället för 8 hamnrutor | Ankomsten avgörs fortfarande i hamnrutan (tester oförändrade och gröna) |
| På väg in | Passagerarfartyg på minst 100 m, läge högst 15 min gammalt, minst 6 knop, kursen högst 35° från terminalen | `maritime/approach.py`, tester för riktning, kaj, urval och närmaste terminal |
| I hamnen | Vid kaj (under 1 knop), lägger till (under 6 knop med kursen mot terminalen), i hamn (annars) | Test för varje läge |
| Beräknad ankomst | Sträcka × farledsfaktor / fart; AIS-ETA visas bara som fritext | Farledsfaktorerna är okalibrerade |
| Karlskrona | Terminalpunkten låg 3,5 km fel och användes för tips; nu rättad | STENA ESTELLE förtöjd 25 m från OSM:s färjeterminal "Karlskrona - Gdynia" |
| Tips | Nya hamnar ger inga tips förrän terminalpunkten stämts av mot AIS; Helsingborg aldrig (pendeltrafik) | Test: ankomst i Helsingborg ger beslutet "bara karta" |

Liveprovet 2026-09-18: efter 20 minuter visade kartan 19 stora passagerarfärjor i elva
hamnområden, bland dem VIKING GLORY vid kaj i Stadsgården, VISBY i Oskarshamn, GOTLAND i
Nynäshamn samt SILJA SYMPHONY och BALTIC QUEEN på väg genom Stockholms skärgård. AURORA BOTNIA
mot Umeå fick beräknad ankomst 19:19 (kl. 18:52, 10,3 km kvar), 19:17 (kl. 19:01) och 19:18
(kl. 19:11). Den stod still i hamnrutan 19:13:39, 1,1 km från den dåvarande terminalpunkten:
beräkningen var 4–6 minuter sen, främst för att punkten låg fel. Ett enda anlöp, ingen kalibrering.
Öresundsfärjornas typ och längd hördes först 23–25 minuter efter start (TYCHO BRAHE 110 m,
HAMLET 106 m). Ett separat prov mot bara Helsingborgs område visade att AISStream skickar dem;
det tar bara tid, och efter en omstart läses de in från databasen. Efter omstart med rättade
punkter kl. 19:20: STENA ESTELLE 0,0 km och AURORA BOTNIA 0,2 km från sina terminalpunkter,
HAMLET vid kaj i Helsingborg, COLOR HYBRID på väg in mot Strömstad. Kryssningsfartyg har också
AIS-typ 60 och räknas med (SKY PRINCESS, 330 m, i Stadsgården).

Kvar:

- Stäm av terminalpunkterna mot AIS-spår, särskilt Varberg, Malmö och Umeå, som bara har
  hamnområdet.
- Kalibrera farledsfaktorerna mot faktiska ankomster.
- Kontrollera AISStreams villkor innan positionerna visas i den betalda appen.
- Kör lyssnaren på en server: lokalt står kartan still när datorn sover.

## Appen: färjor live och evenemang (2026-09-18)

| Del | Läge | Belägg |
|---|---|---|
| `/api/ferries` | Färjor på väg in, som lägger till eller ligger vid kaj vid terminaler i förarens län och kommuner, annars inom 150 km från positionen. Samma behörighet som flödet; läget delas mellan förare i 15 s | Tester: länsval, position, inget område, utan behörighet |
| Kartan i appen | Pil i fartygets kurs och lägets färg, streckad linje till terminalen, ankare för terminalerna; tryck öppnar detaljer. Lägena hämtas var 30:e sekund medan appen är öppen, aldrig i bakgrunden | `flutter analyze` rent, 33 tester |
| Evenemang per datum | Egen sida "Evenemang": I dag, I morgon, Helgen, 7 dagar, 30 dagar, 3 månader, valfri dag eller period (svensk datumväljare), dagrad med antal per dag och listan grupperad per dag och månad. `/api/events?from=&to=` upp till 120 dagar fram, samma horisont som hämtningen; `dayCounts` per dag i området. Huvudlistan visar de tre närmaste med kalenderruta och en ingång till sidan, även när inget finns de närmaste två veckorna | Tester: en dag, horisonten, period i det förflutna; 245 lagrade evenemang sep–jan |
| Ett områdesfilter | "Län och kommuner": alla 21 län med kommunerna under. Det gamla filtret med marknader och orter är borttaget; sparade val flyttas en gång till län (samma tabell som `core/areas.MARKET_COUNTY`) och kommuner med samma namn, och de gamla fälten töms i notisinställningarna. Kartan lägger inte längre till ett dolt ortfilter | Telefonen 2026-09-18: Stockholm behölls vid flytten, `regions` tom på servern |
| Listan i appen | Avsnitten "Färjor" och "Evenemang" med kort (tid, sluttid, när folk går, storlek, plats, källa); källfiltret har "Färjor" och "Evenemang"; tomt filter säger varför | — |
| `/api/events` | Filtreras på förarens län och kommuner; utan område och position som förut, hela landet | Tester: länsval, förhandsvisning |
| Evenemang i appen | Rättighetsspärren är orörd: Ticketmaster saknar avtalsreferens för appen. Förhandsvisning bara med DEBUG och `EVENTS_APP_PREVIEW=1`, märkt i svaret och i appen | Test: utan DEBUG ingen förhandsvisning |

Mätt mot telefonens enhet (Skåne valt): 5 färjor, bland dem POLONIA på väg in mot Ystad (19,7 km)
och TYCHO BRAHE vid kaj i Helsingborg. Evenemang: 0 i Skåne de närmaste 14 dagarna. Ticketmaster
har 26 synliga evenemang i hela landet (Stockholm 16, Skellefteå 6), så kalendern räcker inte
utanför Stockholm.

AISStream har inga publicerade villkor om visning eller kommersiell användning (startsidan och
dokumentationen lästa 2026-09-18). Fråga AISStream innan positionerna visas för betalande förare.

## Färjornas tidtabell (2026-09-19)

GTFS Sverige 3 statisk, importerad ur en redan hämtad fil (`import_ferry_timetable --zip`): 12 621
planerade anlöp, 2 190 färjeturer vid 408 färjelägen för två trafikdagar, 17 s. Pipeline-sidans
avsnitt 2c visar färjelägena som blå fyrkanter med nästa anlöp och en tabell över planerade ankomster
de närmaste tre timmarna. Destination Gotlands anlöp kopplas till AIS-terminalerna (Oskarshamn,
Nynäshamn, Visby), så att planerad tid står bredvid vad AIS ser; övriga rederier har inga färjor
på 100 m och kopplas inte. Trafiklab har ingen realtid för färjorna. Importen är inte schemalagd:
nyckeln får 50 hämtningar i månaden, delat mellan miljöer, och det avgör var den ska köras.

**Tidtabell + AIS per tur** (`maritime/voyages.py`, sidan `/farjor`): för varje tur som pågår enligt
tidtabellen räknas förväntad position (rak linje mellan hamnarna i proportion till tiden) och det
passagerarfartyg som ligger där med kurs mot nästa hamn kopplas, ett fartyg per tur. Beräknad ankomst
= sträcka kvar × 1,15 / fart plus uppehåll; avvikelse = beräknad minus planerad. Ligger färjan redan
vid kaj efter planerad tid visas "framme" utan avvikelse. Live 2026-09-19 kl 11: 106 turer, 44 kopplade,
26 utan träff, 36 utanför AIS-områdena; VISBY kopplad till Nynäshamn–Visby. Pipeline-sidans avsnitt 2c är
nu bara en länk dit.

## Färjor för taxiföraren (2026-09-19)

`maritime/relevance.py` bygger ankomsterna och sidan `/farjor` visar dem först. Principen, på
uppdragsgivarens begäran: **visa så mycket som möjligt och låt föraren avgöra.** Bara det som inte är
en känd ankomst tas bort: dubbletter, sådant utanför tidsfönstret (hämtningen över, eller mer än 3 h
bort) och stora fartyg vid kaj som AIS inte sett komma in (de kan vara på väg ut). Allt annat visas med
en **sort** och **kännetecken**:

| Sort | Vad | Hämtning |
|---|---|---|
| Stor färja | Destination Gotland och passagerarfartyg ≥ 100 m (AIS-längd) | 10–45 min efter ankomst |
| Pendelfärja | Helsingborg–Helsingør, bara AIS; motparten ur hamnregistret | 0–15 min |
| Öbåt | båtar från öar och längre skärgårdsturer | 0–15 min |
| Pendelbåt | under 3 km, eller under 8 km med buss/spårvagn i båda ändar | 0–15 min |
| Rundtur | samma brygga som start och mål | 0–15 min |
| Vägfärja | Trafikverkets bilfärjor | 0–15 min |

Kännetecken: *ingen bilväg* (ingen buss, spårvagn eller tåg inom 600 m från bryggan i samma GTFS-fil,
kolumnen `stop_has_road`, migration `maritime 0005`), *buss/spårvagn i båda ändar*, *sen enligt AIS*.
Föraren slår av och på sorter och kännetecken; "Förslag" visar stora färjor, pendelfärjan och öbåtar
med bilväg. Valet sparas i webbläsaren. Varje kort säger vart, varifrån, när och vilken sort; en
detaljpanel visar sorten, kännetecknen, hur tiden räknades och AIS-data. Utrikesfärjor och
kryssningsfartyg heter "Stort passagerarfartyg" med "ursprung okänt", eftersom AIS inte säger varifrån.

**Hamnarna**: alla 17 AIS-hamnar visas även utan ankomst, med fartyg vid kaj, ankomster vars hämtning
är över, senaste stora ankomst och hur långt ut AIS ser (8 km/16 min i Helsingborg, 37 km/80 min i
Umeå). Utrikesfärjorna syns först i inseglingsområdet, ungefär en timme före ankomst. Den tekniska
tabellen (alla pågående turer och AIS-kopplingen) ligger hopfälld; en rad säger om turen visas och som
vilken sort, eller varför den inte visas (`taxi.decisions`).

Rättat på vägen: fartyg på 100 m eller mer kopplas inte till skärgårdsturer (MSC MAGNIFICA hade kopplats
till en SL-båt), Gotlandsfärjorna har 1,5 km kajradie, och en Gotlandsfärja som AIS ser men som inte
kunde kopplas räknas som dubblett i stället för utrikes.

Live 2026-09-19 kl 13: 393 ankomster in, 323 visas (4 stora, 1 pendelfärja, 54 öbåtar, 158 pendelbåtar,
29 rundturer, 77 vägfärjor; 36 utan bilväg), "Förslag" 38. Borttagna 70: dubbletter 6, utanför fönstret
58, vid kaj utan sedd ankomst 6. Kontrollerat i headless Chrome, utan JS-fel. Kända begränsningar:
kopplingen är närmaste fartyg (ett forskningsfartyg kunde kopplas till en Styrsöbåt; panelen visar
avståndet); Öregrund–Gräsö står under UL i GTFS och blir därför pendelbåt, fast det är en vägfärja;
hämtningsfönstren är antaganden, inte mätta.

## Pipeline-vyn, en tjänst i taget (2026-09-19)

localhost:4000 var en enda sida på 35 MB (alla 19 700 råhändelser och 7 250 aktiva tips i ett svar).
Nu har varje tjänst en egen sida: tåg, buss/tunnelbana/spårvagn, väg, flyg, färjor, evenemang och
väder, och `/` är en översikt med färskhet och vad föraren får per tjänst. Varje sida svarar i samma
ordning: 1) källorna och hur färska de är, 2) analysstegen med filen där de bor och hur mycket som är
kvar efter varje steg, 3) sorterna och poängreglerna med antal och poäng, 4) vad föraren får, grupperat
som *notis och lista*, *bara i listan* och *visas inte* (med exempel), med kartan bredvid. Ett tips
öppnar hela kedjan: källhändelserna med rådata, tolkningen, poängregeln och skälen, och notisbeslutet
grind för grind. Svaren är 5–240 kB och kommer på under 0,25 s (`core/service_view.py`). Den gamla
helsidan finns kvar på `/system`.

Tågsidan tar alla tåg-tips (Trafikverket plus pendel- och regionaltåg från SL, Västtrafik och
Trafiklab); buss/spårvagnssidan resten av kollektivtrafiken. Vägtexten säger nu vad koden gör:
grundpoäng högst 15 plus väder 12, alltså högst 27, aldrig en notis.

Två fel som vyn gjorde synliga, båda rättade:

- **`/api/pipeline` svarade utan DEBUG**, med alla aktiva tips och rådata utan inloggning. Nu 404 utan
  DEBUG, som de andra pipeline-endpointerna. Inget annat anropar den (sökt i app, webb och backend).
- **`source_events.fetched_at` flyttades aldrig** efter första skrivningen: SMHI-punkterna, vars
  prognos byts varje timme, såg elva dygn gamla ut. Nu sätts den när innehållet ändras
  (`core/repository.py`), med test.

## Ändrat i den lokala miljön

Django-migrationerna 0017–0019 är körda mot utvecklingsdatabasen. Supabase-migrationerna
`20260913000002` och `20260913000003` är körda där med `psql`. `gunicorn==23.0.0`
(samma version som `requirements.txt`) är installerad i `.venv`. Integrationskörningarna
uppdaterade pipelinens data (vägtips, källstatus). `manage.py backfill_areas` gav 6 910 tips
ett län (51 gick inte att placera). Testrader från webhookscenarierna är
borttagna. Redis-containern och webhookfunktionen är stoppade igen.

P1 lade till migrationerna core `0020`–`0021`, maritime `0003` och events `0002`, körda mot
utvecklingsdatabasen, och `backfill_areas` fyllde i kommunkoder på befintliga tips.

P2 lade till migrationerna core `0022` (`opportunity_combinations`) och `0023`
(`device_presence`), körda mot utvecklingsdatabasen. Båda tabellerna står i
låsningsmigrationen `20260913000003`. Worker och beat startades om lokalt med
`combine-signals` och `purge-presence` i schemat. AIS-pilotens körning stoppades
18:07 med SIGINT.
