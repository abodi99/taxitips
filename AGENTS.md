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

Affärsmodellen är B2B: taxibolag betalar en Stripe-prenumeration per
**billicens** (en registrerad bil med ett baslän). Förare ansluter sin telefon
med en engångskod från företagets administratör -- bolagskoden ger inte längre
åtkomst, den skickar en ansökan. Ingen App Store-prenumeration, ingen IAP.
**Appen säljer ingenting**: inga priser, köpknappar eller betallänkar. Nya
kunder registrerar sig i appen och får ett kortfritt prov; betalning sker
utanför appen (säljare, faktura, kundportalen på webben). Skälet och reglerna:
`docs/fleet-abonnemang.md` §9c.

## 2. Var koden ligger

```
taxitips-backend/   Django. Hämtning, klassificering, poängsättning, förar-API, kundlivscykel. Tyngdpunkten.
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
sju källor          → source_events → klassificering → poängsättning → opportunities → /api/alerts → appen
(Trafikverket järnväg,  (rå payload)   taxi_relevance    scoring.py        (tipset)      core/api.py
 Trafikverket väg,                     text_scoring      flight_scoring.py
 SL, Västtrafik,                       mode.py           thresholds.py
 Trafiklab, SMHI,                                        compensation.py
 Swedavia flyg)                                          alternatives.py
```

Swedavia är den enda källan som inte rapporterar en störning: den räknar
ankomster. Enheten är därför ett 30-minutersfönster per flygplats, inte ett
flyg, och klassificeringen sker i `core/flight_scoring.py` i stället för i
text_scoring-kedjan. Se `docs/data-sources.md` för varför `DEL` inte betyder
"försenad".

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
| `entitlement.py` | **Enda ingången till allt skyddat.** Delegerar till `fleet/access.py`. |
| `repository.py` | Rå SQL-upsert. Läs kommentaren om `notified_at` innan du rör den. |

Kundlivscykeln i `taxitips-backend/fleet/`:

| Fil | Ansvar |
|---|---|
| `access.py` | **Åtkomstkontrollen.** Sex frågor per begäran, svaret bär alltid skälet. Spärrar prövas först. |
| `accounts.py` | Spärrar (företag, konto, e-post) och kontokatalogen. |
| `registration.py` | Självregistrering från appen: företag + kortfritt prov, ingen betalning. |
| `pricing.py` | **Enda prismotorn.** Heltal ören, volymnivå, introduktion, proportionering, moms. |
| `pairing.py` | Engångskod -> godkänd telefon. Hashade hemligheter. Spärr. |
| `sessions.py` | Skiftbyte. En telefon per licens, en bil per telefon -- via databasen. |
| `licensing.py` | Bilar, licenser, länsrättigheter, bilbyten. |
| `orders.py` | Beställningar, minskningar, uppsägning, betalningsfrist. |
| `webhook_events.py` | Stripe -> rättigheter. Ordning, dubbletter, gamla fakturor. |
| `roles.py` | Behörigheter och tvåfaktorskravet. |
| `risk.py` | Riskgränser. Blockerar nästa ändring, aldrig åtkomsten. |
| `push_gate.py` | Mottagarkontroll strax före sändning. |

## 4. Kör lokalt

```bash
colima start
cd taxitips-api && supabase start                       # Postgres på 54322
cd ../taxitips-backend && ./.venv/bin/python manage.py runserver 8000
cd ../taxitips-pipeline-viz && VIZ_BACKEND=http://127.0.0.1:8000 node server.js   # http://localhost:4000
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
./.venv/bin/python manage.py poll_flights --force   # --force förbigår kvotkadensen
./.venv/bin/python manage.py run_ais_stream         # färjor: långlivad WebSocket, Ctrl-C för att stoppa
./.venv/bin/python manage.py poll_events            # evenemang (Ticketmaster), hela Sverige
# PredictHQ sparas bara med en rättighetsreferens till ett skriftligt avtal (events/rights.py,
# EVENTS_PREDICTHQ_STORE + _STORE_REFERENCE). Utan den: live i pipeline-sidan, bara med DEBUG.
# /api/events visar bara källor med referens för visning i appen (EVENTS_*_APP_REFERENCE).
```

`run_ais_stream` är ingen engångshämtning utan en lyssnare (AISStream.io). Den
kräver `migrate maritime` och `AISSTREAM_API_KEY`, stöder `--duration N`,
`--dry-run` och `-v 2`, och körs i produktion som egen Coolify-tjänst med
`APP_ROLE=ais` -- en instans, se kommandots docstring.

`run_ais_pilot` är P1-piloten för Visby och Värtahamnen: registrets färjor
(`maritime/register.py`, bara fartyg som setts i AIS) följs hela vägen in och får en
förutsagd kajtid (`berth_eta`, med grund: sträcka/fart eller fartygets AIS-ETA, aldrig
en blandning) och ett separat iland-fönster. Varje anlöp sparas i `ferry_calls` med
förutsagd mot faktisk kajtid. En egen filtrerad anslutning (`FiltersShipMMSI`) --
räkna anslutningarna över alla miljöer, AISStream tillåter tre per konto och IP:

```bash
./.venv/bin/python manage.py run_ais_pilot --duration 900   # --dry-run skriver inga tips
```

`run_ais_stream` lyssnar på inseglingsområdena till 17 passagerarhamnar (`maritime/ports.py`);
ankomsten avgörs i hamnrutan, och hamnar med `tips=False` visas bara på kartan. Färjor på väg in
visas live i pipeline-sidans avsnitt 2c (`/api/pipeline/ferries`, bara med DEBUG,
`maritime/approach.py`).
I appen: `/api/ferries` (förarens område, samma behörighet som flödet) och `/api/events`
(län och kommuner, `from`/`to` upp till 120 dagar, `dayCounts` per dag; förhandsvisning bara med
DEBUG och `EVENTS_APP_PREVIEW=1`). Appens sida: `lib/screens/events_screen.dart`.

Färjornas tidtabell (GTFS Sverige 3, planerad tid, ingen realtid för färjorna):
`manage.py import_ferry_timetable --zip <sweden.zip> [--download] [--days 2]`. `--download` räknas
mot 50 hämtningar/månad per nyckel och vägrar inom 20 h; inte schemalagt än. Turerna kopplas till AIS i
`maritime/voyages.py` och visas på pipeline-vyns egen sida `http://localhost:4000/farjor`. Ankomsterna för
taxiföraren görs i `maritime/relevance.py` och ligger överst på sidan: allt som är en känd ankomst visas,
med sort (stor färja, pendelfärja, öbåt, pendelbåt, rundtur, vägfärja) och kännetecken, och föraren
filtrerar. Bara dubbletter, sådant utanför tidsfönstret och fartyg vid kaj utan sedd ankomst tas bort. Importen räknar också `stop_has_road` (buss, spårvagn eller tåg inom 600 m);
efter en ändring av regeln behöver importen köras om ur samma zip.

Förarkartan i appen (ombyggd 2026-09-21, för förare med begränsad svenska):

* **En sanning för typ och styrka: `lib/signal_kinds.dart`.** Kategori (Tåg & buss, Väg, Flyg,
  Färja, Event) ger ikonen, styrkan ger färg, storlek och ett ord. Samma par på kartan, i
  listan, i detaljvyn, i filtret och i förklaringen (`?`-knappen, `map_legend_sheet.dart`).
  Väghinder har egen skala och egen form (triangel, rött = olycka/avstängt) så att de aldrig
  läses som en körning; styrkefiltret gäller inte dem.
* **Kategoriraden** (`category_bar.dart`) överst styr både kartan och listan: Alla, en
  kategori, eller Följer. Ersätter de gamla flikarna i bottenpanelen.
* **Kartan** (`signal_map.dart`): flutter_map + CARTO Voyager, ljus och ofiltrerad (en mörk
  variant upplevdes som för mörk i bilen). Nyckeln `CARTO_KEY` skickas in vid bygget och
  checkas aldrig in -- repot är publikt. Utan nyckel ritas Esri World Street Map; CARTO
  utan nyckel stämplar "API KEY REQUIRED" över varje ruta. Klustrar under zoom 15;
  väghinder klustras för sig. Första GPS-positionen flyttar kartan till föraren.
* **Releasebygget** läser alla inställningar ur `taxitips-app/dart_defines.local.json`
  (git-ignorerad; API_BASE_URL, SUPABASE_URL, SUPABASE_ANON_KEY, CARTO_KEY):
  `flutter build apk --release --dart-define-from-file=dart_defines.local.json`.
* **Licensens län gäller överallt**: tips, väghändelser, evenemang, färjor och
  notisinställningarna (`request_area`/`area_blocked` i `core/api.py`). Länsväljaren i appen
  visar bara licensens län. Förarens val får smalna av, aldrig vidga.
* **Väg visar bara trafikolyckor** (beslut 2026-09-21, `thresholds.ROAD_SHOWN_CONDITIONS`).
  `core/text_scoring.road_tier` klassar ändå alla väghändelser (olycka, avstängd, kö, hinder
  på huvudled, stor störning på huvudled, övrigt) och villkoret står i `rule_id`
  (`road.<nivå>.<villkor>`), så att varje dold händelse går att förklara i pipeline-vyn.
  Urvalet görs i SQL i `feed_for`. En Trafikverket-situation med flera avvikelser visas en
  gång. Ett väghinder har inget "Kör dit" och ingen "Fick körning?".
* **Notisregler per förare** (`core/notify.decide`): kategorier, lägsta nivå (alla / medel+ /
  bara starka) och paus i högst 24 h, satt på serverns klocka. Skälen `paused`,
  `category_off:<kategori>` och `below_level` i `REASONS`.
* **Favoriternas `owner_key` är `device:<uuid>`**, aldrig telefonens råa token (migration
  `core/0025`).
* **Kör dit** (`navigation.dart`) öppnar telefonens navigering (`google.navigation:` på
  Android, Apple Kartor på iPhone). Appen har ingen egen ruttplanering.
* **Följ**: tips på servern (`OpportunityFavorite`), evenemang på telefonen
  (`followed_events.dart`, en kopia per evenemang, rensas dagen efter).
* Google Maps-varianten (`traffic_map.dart`, `--dart-define=GOOGLE_MAPS=true` + `MAPS_API_KEY`)
  finns kvar men har inte den nya designen. Maps är inte aktiverat i GCP-projektet
  `taxibehov` (Static Maps svarar 403).

Pipeline-vyn (localhost:4000) har en sida per tjänst: `/tag`, `/kollektivtrafik`, `/vag`, `/flyg`,
`/farjor`, `/evenemang`, `/vader`, och en översikt på `/`. Varje sida visar källorna och deras
färskhet, analysstegen med filen där de bor, hur mycket som är kvar efter varje steg, sorterna och
poängreglerna, och vad föraren får (notis och lista, bara listan, visas inte) med varför. Ett tips
öppnar hela kedjan: rådatan, tolkningen, poängen och notisbeslutet. Data från
`/api/pipeline/services`, `/api/pipeline/service/<tjänst>` och `/api/pipeline/tip/<id>`
(`core/service_view.py`), bara med DEBUG som `/api/pipeline`. Den gamla helsidan ligger på `/system`.

`--duration` räknas på väggklockan: en Mac som sover stoppar den monotona klockan,
och en körning på 3,5 h pågick annars i elva.

Kombinationslagret (`combine_signals`, var 60:e sekund i beat, `core/combine.py`) visar
samma störning från två källor som en rad och förstärker knutpunkter och ankomster i
listan, inte i notiserna. "I tjänst" (`/api/presence`, `core/presence.py`) sparar en
ruta på ungefär 5 km i 30 minuter och ersätter då körområdet i notisbeslutet; ingen
historik, ingen bakgrundsplats. `manage.py calibration_report` ställer feedback,
utkorg och AIS-anlöp mot utfall och flyttar inga trösklar.

`poll_rail` hämtar störda avgångar och avgångarna vid drabbade stationer sida för sida
(`complete` och `cancelled_trains` i `source_status.detail`). För inställda tåg utan
ersättning frågar den ResRobot (`RESROBOT_API_KEY`, `core/sources/resrobot.py`) efter nästa
resa mot samma slutstation: högst 20 anrop per runda och 25 000 per månad.

Förarflödet (`/api/alerts`) delas i 20 s mellan förare med samma filter och avrundade
position (`core/api.shared_feed`). En instans använder minnescache; flera repliker
sätter `CACHE_REDIS_URL` så att de delar den.

Alla stöder `--dry-run`. Utan `--skip-sites` uppdateras hållplatsregistret
(~18 000 rader, tar en stund). Kör det efter `supabase db reset`.

Notiser testas utan Firebase-nyckel:

```bash
./.venv/bin/python manage.py push_cycle --dry-run    # visar besluten, rör inget
./.venv/bin/python manage.py push_cycle --simulate   # skriver push_delivery, skickar inget
```

`--dry-run` skriver ut varje kandidat med skälet den föll på
(`no_area`, `outside_area`, `unplaced_tip`, `type_off:…` -- alla i `core/notify.REASONS`) och är
det snabbaste svaret på "varför fick föraren ingen notis?". `--simulate` kör
samma beslut men skriver `push_delivery` och `notified_at` på riktigt, så
appens notishistorik går att fylla utan att någon telefon väcks. Riktig
sändning kräver `FIREBASE_SERVICE_ACCOUNT_JSON` i `.env`; utan den svarar
sändsteget `skipped: no_service_account` i stället för att kasta.

**På en riktig telefon** måste Django lyssna utåt och appen peka på LAN-IP:n
— `127.0.0.1` är telefonen själv:

```bash
./.venv/bin/python manage.py runserver 0.0.0.0:8001      # inte bara 127.0.0.1
cd ../taxitips-app && flutter run -d <enhet> \
  --dart-define=API_BASE_URL=http://<macens-ip>:8001 \
  --dart-define=SUPABASE_URL=http://<macens-ip>:54321 \
  --dart-define=SUPABASE_ANON_KEY=<PUBLISHABLE_KEY>
```

Android blockerar okrypterad HTTP sedan API 28. `src/debug/AndroidManifest.xml`
tillåter den för debugbyggen — utan det dör anropen i plattformslagret innan
appens egna felmeddelanden hinner formuleras, och symptomet blir "inga
störningar just nu" i stället för ett nätverksfel.

Prenumerationer testas utan Stripe-konto:
`manage.py simulate_stripe_event --company "Malmö Taxi AB" --type
customer.subscription.updated --status past_due` bygger och signerar en
riktig event-payload mot den lokala webhooken. `.mcp.json` registrerar
dessutom Supabase CLI:s egen MCP-server (`supabase-local`) mot den lokala
instansen — inte att förväxla med `taxitips-selfhosted`, som är produktion.

**Pipelinen på riktigt, med Redis, worker och beat.** `.env` har
`CELERY_TASK_ALWAYS_EAGER=1` för testerna, och då kör beat varje task själv i
stället för att lägga den i kön -- sätt 0 i skalet (skalets värde vinner över `.env`):

```bash
cd taxitips-backend && docker compose up -d redis
export CELERY_TASK_ALWAYS_EAGER=0
# Inga riktiga notiser till testtelefoner, ingen Genkit, ingen gallring av lokal data:
export TAXITIPS_BEAT_DISABLE=push-cycle,review-uncertain,poll-events,poll-flights,purge-old
./.venv/bin/celery -A config worker -l info --concurrency=2
./.venv/bin/celery -A config beat -l info -s /tmp/celerybeat-schedule
curl -s localhost:8000/health/pipeline        # 503 tills hjärtslag och kärnkällor är färska
./.venv/bin/python manage.py check_pipeline   # samma kontroll som exit-kod
```

Körområden: `manage.py backfill_areas` fyller i län på befintliga tips och
`manage.py report_area_prefs` visar hur sparade notisinställningar blir län
(läser bara). Utan körområde skickas ingen notis (`no_area`).

Drift inför lansering: backup och återställningsprov i `ops/backup/README.md`,
Stripe-webhookens scenarier i `ops/stripe/webhook_scenarios.py`, lasttest i
`ops/loadtest/feed_load.py`, och läget i `docs/lansering-p0.md`.

**Adminwebben** (`taxitips.se/admin`, `fleet/admin_api.py`): kunder, abonnemang,
notiser, evenemang och riskgranskningar över ALLA bolag. Kräver en aktiv rad i
`fleet_staff_role` -- en kunds roll i `company_members` ger ingenting där, hur hög
den än är. `support` läser, `sales` säljer (företag, paket, prov, kuponger,
förare, betallänkar, uppsägning till periodens slut), `platform_admin` gör allt
och ensam det som ger åtkomst utan betalning (kuponger, betald utanför Stripe,
avsluta direkt). Säljflödet: `docs/fleet-abonnemang.md` §9b. Spärrar av
företag, konton och e-postadresser, personalroller och egna evenemang
(manuellt eller CSV/JSON): §9d. Kundsidan visar "Kundens väg" -- sex steg från
företag till betalning, med nästa steg markerat. Grundaren
(`bbf6ca6c-…`) är platform_admin. Konton skapade med Google har inget lösenord
och Google-inloggning är inte konfigurerad i produktionens Supabase Auth, så
adminwebben loggar in med en e-postlänk.

**Driftfällor i produktion (2026-09-21):**

* **Push skickas från workern** (`taxitips-celery-worker`, beats `push-cycle`).
  Workern fick `FIREBASE_SERVICE_ACCOUNT_JSON` (base64) 2026-09-21 och den
  tillfälliga schemalagda uppgiften på `taxitips-backend` är borttagen. Lägg
  inte tillbaka den: två avsändare = dubbla notiser.
* **Färjor: egen app `taxitips-ais`** (`8x3hdgz1g5q8fa8dcoo4q5yn`, APP_ROLE=ais,
  ingen HTTP, EN instans). Den ansluter som rollen `taxitips_ais`
  (migration `20260921000002_ais_listener_role.sql`) -- inte som postgres --
  och får bara skriva fartyg, anlöp, sina tips och sin källstatus. Lösenordet
  finns bara i appens `DATABASE_URL` i Coolify. Tips ges bara för fartyg
  ≥ 100 m; skärgårdsbåtarna loggas som ankomster utan tips. Färjornas
  tidtabell (`import_ferry_timetable`) kräver `GTFS_SWEDEN3_STATIC_KEY`, som
  ännu saknas.
* **Evenemang i appen kommer från PredictHQ** (ägarbeslut 2026-09-21).
  Rättighetsreferensen i `EVENTS_PREDICTHQ_*_REFERENCE` säger det rakt ut:
  beslutet är ägarens, inget skriftligt avtal är registrerat. Ticketmaster och
  TheSportsDB lagras men visas inte. Nycklarna (PredictHQ, Ticketmaster,
  Swedavia, ResRobot) ligger på workern; web har PredictHQ-token och
  rättighetsflaggorna, eftersom evenemangslistan och pipeline-sidan körs där.
* **Produktionens Supabase saknar `supabase_migrations`.** `apply_migration`
  i MCP:n misslyckas; migrationer körs med `execute_sql` och ligger ändå som
  filer i `taxitips-api/supabase/migrations/`.
* **Coolify kapar schemalagda kommandon vid 255 tecken.** Längre SQL går via
  produktionens Supabase-MCP (`claude.ai taxitips mcp`), inte via `psql -c`.
* **`api.taxitips.se` har svarat 502** (Traefik når inte Kong) i perioder.
  Förarvägen går via `backend.taxitips.se` och påverkas inte.
* **`flutter build … | tail` ljuger om exitkoden.** Kontrollera flutters egen,
  annars installeras den gamla APK:n i tron att den är ny.

Testverktyg: `manage.py seed_test_company` (testbolag + anslutningskod, utan
Stripe) och `manage.py send_test_push --company "…"` (genom samma mottagargrind
som riktiga notiser, med skäl per telefon).

Kundlivscykeln (konton, billicenser, abonnemang): **`docs/fleet-abonnemang.md`**
-- datamodellen, affärsreglerna, utrullningsordningen och återställningen.
Utrullningen styrs av `FLEET_ENFORCE_LICENSES`, som är AV tills
`manage.py migrate_legacy_fleet` körts och kunderna informerats.

Tester — båda ska vara gröna innan något deployas:

```bash
cd taxitips-backend && CELERY_TASK_ALWAYS_EAGER=1 ./.venv/bin/python manage.py test   # 903
cd taxitips-app && flutter test && flutter analyze                                     # 72
cd taxitips-web && npx vite build                                                      # index + portal + admin
```

`flutter analyze` är rent (kontrollerat 2026-09-14).

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
| `TAXITIPS_STATUS.md` | Vad som faktiskt fungerar, med datum. §0 är nyast. **§7 är stale** — skriven mot den gamla Supabase/Node-arkitekturen; se §8 här i stället. |
| `taxitips-backend/core/notify.py` | Vem som väcks och varför. Grindarna i ordning, med mätningen bakom varje. |

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
   vägrader mot 5 kollektivtrafiktips i Skåne. Och bara olyckor når
   föraren (`ROAD_SHOWN_CONDITIONS`). Matcha aldrig "avstäng" eller "kö" som
   delsträng: båda finns i "Körfältsavstängningar", och 546 planerade
   körfältsavstängningar blev röda "Stopp".
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
9. **AI-granskningen (Genkit) på `confidence=low` får omklassa** poäng
   och `severity_tier` (även höja) -- regelverket har redan sagt att
   fritexten är osäker. På övriga tips gäller fortfarande bara sänkning
   (`min(regel, modell)`), klämt i `RailAssessment.save()` när
   `_allow_reclassify` saknas.
10. **Ett tips ska alltid gå att förklara**: vilka `source_event_ids`,
    vilken regel, vilken konfidens.
11. **`notify_worthy` är den riktiga notisgrinden, inte en poänggräns.**
    Fältet sa tidigare bara "över 50", så ett kort kunde lova en notis som
    aldrig kom. Det speglar nu hela beslutet i `core/notify.py` — typ,
    poäng och `has_alternative`. Ändrar du grindarna, ändra fältet i samma
    commit, annars ljuger appen igen.
12. **Notiser tystas när källan själv skrivit ut ersättningstrafik.**
    `has_alternative=True` betyder att bussen redan går. Mätt: 6 av 14
    push-kandidater. Kortet ligger kvar i listan — det är bara väckningen
    som uteblir, eftersom en bomresa mitt i natten kostar mer än en missad
    notis. Samma resonemang som invariant 2.
13. **Favoriter filtreras aldrig.** De skickas i en egen lista vid sidan av
    flödet och passerar varken marknadsradie, filter eller sluttid. Ett
    tips föraren aktivt sparat ska inte kunna gömmas av ett filter som
    ligger kvar sedan förra passet. `PushDelivery` bär dessutom en
    ögonblicksbild, så notishistoriken överlever `purge_old` efter sju
    dygn.
14. **Länsfiltret kan aldrig avgränsa tågtips.** Trafikverkets tågdata
    saknar länsfält, så de skrivs som `region="rail"` oavsett var
    stationen ligger. Utan avståndsgrinden i `within_reach()` väcktes en
    Malmöförare med "Skåne + järnväg" om Örnsköldsvik, 1 400 km bort, som
    appens egen lista aldrig visat. Notisvägen och listvägen måste hålla
    samma 150 km.
15. **Ett flygtips räknar ankomster, aldrig resenärer.** Swedavias svar bär
    varken flygplanstyp eller passagerarantal, så "tre plan ≈ 500 personer"
    vore påhittat — samma regel som håller GTFS-beläggning kategorisk.
    Nattpåslaget i `flight_scoring.py` är av samma skäl bara ett påslag:
    vi har ingen tidtabell för Arlanda Express eller flygbussarna och får
    därför aldrig skriva "sista tåget har gått" (invariant 2).
16. **En bolagskod är inte en credential.** `join_device()` delade ut en
    permanent enhetstoken ur en sexteckenskod som står på ett papper i
    fikarummet. Den är stängd (`20260920000001`). Telefoner godkänns av en
    administratör, för en bestämd bil, med en engångskod som gäller fem
    minuter. Se `fleet/pairing.py`.
17. **En aktiv telefon per billicens, en aktiv bil per telefon** -- som
    partiella unika index i `fleet_vehicle_session`, inte som kontroller i
    Python. Två förare som trycker "Ta över" samtidigt läser båda innan
    någon skriver. En avslutad session återupplivas aldrig: `heartbeat()`
    rör bara en öppen rad, annars tar en gammal telefon tillbaka bilen genom
    en bakgrundsuppdatering.
18. **Belopp räknas på servern, i heltal ören.** `fleet/pricing.py` är den
    enda prismotorn. En andra i klienten kan visa rätt när fakturan blir fel.
19. **Djangos tabeller nås aldrig via PostgREST.** Supabase ger varje ny
    tabell rättigheter till anon och authenticated. `fleet`-migrationen 0003
    tar tillbaka dem uttryckligen i stället för att lita på att en annan
    migration kört först.

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
- **Swedavias `DEL` betyder "Borttagen", inte "Delayed".** Statusenum:t
  saknar förseningsstatus helt; `DEL`/`CAN` bär noll resenärer och räknas
  bort. Försening = `(actualUtc ?? estimatedUtc) − scheduledUtc`.
- **Swedavias `{date}` i sökvägen är lokalt datum, inte UTC.** Ett fönster
  som korsar midnatt kräver två hämtningar (idag + imorgon).

## 8. Var arbetet står

**Klart:** pipelinen (sju källor, nationellt), förar-API:t, appen läser från
Django, feedback (🚕/👍/👎), källhälsa, täckningsvy, nästa avgång +
ersättningstrafik, ersättningsregler för 16 län, API-inventering,
**kundlivscykeln** (`fleet/` -- bilar, billicenser, län som rättighet,
parkoppling med engångskod, skiftbyte, prov, prismotor, beställningar,
uppsägning, Stripe-synk, risk och revision; se
`docs/fleet-abonnemang.md`), **kundportalen** (`taxitips-web/portal.html`),
**push-pipelinen** (`core/notify.py` — fyra grindar, skäl vid varje nej),
**favoriter** och **notishistorik** (`OpportunityFavorite`, `PushDelivery`),
länsval i notisinställningarna. Inför lansering, lokalt och inte driftsatt:
hälsa och lås, utkorg, län och kommuner, flödescache, AIS-pilot,
kombinationslager, "i tjänst" och kalibreringsrapport -- läget och
blockerarna står i `docs/lansering-p0.md`.

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

**P0 — verifierat läge 2026-09-09.** `TAXITIPS_STATUS.md` §7 är skriven mot
den gamla Supabase/Node-arkitekturen (`alerts`-tabellen, `get_smart_alerts`,
edge functions) och beskriver inte längre var koden bor. Det faktiska läget,
kollat mot koden:

| Punkt | Läge |
|---|---|
| Entitlement-grind | **Klar.** Varje endpoint i `core/api.py` går via `entitlement_for_request`. Två vägar, se invariant 6. |
| Stripe-webhook | **Verifierat 2026-09-09 mot Stripe API (livemode):** exakt en webhook-endpoint är registrerad (`we_1U7aT0P67HXLcerWl52HJ5K0`, "TaxiTips Supabase webhook") och den pekar på `https://api.taxitips.se/functions/v1/stripe-webhook` — edge-funktionen i `taxitips-api/supabase/functions/stripe-webhook/`, inte Django. `billing/webhooks.py` är alltså fortsatt korrekt märkt "LOCAL, TEST-MODE ONLY"; Django-backenden finns inte ens som app i Coolify. **Rör inget här utan ett separat, uttryckligen godkänt migreringssteg** (byt webhook-URL i Stripe-dashboarden, verifiera med en riktig cykel, ta sedan bort edge-funktionen) — detta är produktionsnära och finansiellt närliggande per CLAUDE.md. |
| Push-pipeline | **Byggd, kan skicka så snart nyckeln är på plats lokalt.** `FIREBASE_SERVICE_ACCOUNT_JSON` är tom i `taxitips-backend/.env`, men samma nyckel är redan satt på `taxitips-worker` i Coolify (production + preview) — samma Firebase-projekt (`taxibehov`) backar båda tjänsterna. Kopiera värdet därifrån i stället för att generera en ny i Firebase Console. `push_cycle --simulate` kör hela beslutskedjan och skriver `push_delivery` utan att skicka. |
| Backuper | **Saknas helt.** Inget `pg_dump` någonstans i repot. Detta är den allvarligaste kvarvarande punkten: CLAUDE.md gör backup-före-migrering till det som *ersätter* mänsklig granskning. |
| Service-role-nyckeln | `SUPABASE_SERVICE_ROLE_KEY` används bara av `seed_local_demo` (lokal utveckling). Django-backenden skriver via sin egen DB-anslutning. Den gamla Node-workern i `taxitips-api/` är inte längre den som kör pipelinen. |

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
