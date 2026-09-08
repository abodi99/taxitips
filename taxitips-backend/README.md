# taxitips-backend

Django-tjänst som ska ersätta Node-workern: hämtning, klassificering,
poängsättning och push. Körs lokalt först, deployas till Coolify när
resultatet stämmer.

Ersätter **inte** Supabase. Auth, bolag, enheter och Stripe ligger kvar
där. Sedan Spår B påbörjades ligger däremot **tipsflödet** här: appen
hämtar listan, förklaringen och feedbacken från `/api/*` i stället för
Supabase-RPC:erna (se "Förar-API:t" nedan).

## Kom igång

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
cp .env.example .env        # fyll i API-nycklar
./.venv/bin/python manage.py migrate
./.venv/bin/python manage.py seed_rules
./.venv/bin/python manage.py runserver 8000
```

Förutsätter att `supabase start` kör. Django använder en **egen databas**
(`taxitips`) på samma Postgres-instans (54322) — Supabase-schemat rörs inte.

| Vad | Var |
|---|---|
| Admin | http://127.0.0.1:8000/admin/ (`admin` / `taxitips`) |
| Health | http://127.0.0.1:8000/health |

## Kommandon

## Förar-API:t (Spår B)

Appen läser tips här i stället för `get_smart_alerts`. Sätt `API_BASE_URL`
när du kör appen; utan den går den via Supabase precis som förut:

```bash
cd ../taxitips-app
flutter run --dart-define=API_BASE_URL=http://127.0.0.1:8000
# Android-emulator: http://10.0.2.2:8000
```

| Endpoint | Gör |
|---|---|
| `GET /api/alerts?lat&lon` | Tipsflödet. `X-Device-Token` eller `Authorization: Bearer <supabase-jwt>` |
| `GET /api/opportunities/<uuid>` | "Varför visas detta?" — källhändelse + regel |
| `POST /api/feedback` | 🚕/👍/👎 → `opportunity_feedback` |
| `GET /api/config` | Tröskelvärdena appen slutar hårdkoda |

**Varför flytten.** Samma bedömning gjordes på tre språk: poängen i Python,
urvalet och avståndet i plpgsql, nivågränserna i Dart. `get_smart_alerts`
hann bli omdefinierad sju gånger över 25 migrationsfiler. Nu görs den en
gång, i `core/api.py` + `core/thresholds.py`. Fältnamnen är RPC:ns
(`worth_it_score`, `is_active`, `distance_km`) med avsikt — kort, karta och
sortering i appen behövde inte skrivas om för att byta väg.

Tre saker blev bättre på köpet, inte som features utan för att flytten
avslöjade dem:

1. **Feedbacken hade aldrig fungerat.** `alert_feedback.alert_id` har en
   främmande nyckel mot `alerts(id)`, men appen skickar sedan flytten till
   `opportunities` ett opportunity-id. De två id-rymderna överlappar i noll
   av 4345 rader, så varje tumme upp avvisades av databasen — tyst, i ett
   catch-block. Tabellen har noll rader. `opportunity_feedback` pekar på
   rätt tabell.
2. **Koordinatlösa tips nådde bara tre regioner.** RPC:n hade tre
   hårdkodade lat/lon-rutor (Skåne, Stockholm, Göteborg); en förare i Falun
   såg aldrig ett enda tips utan koordinat, oavsett `MARKET_SCOPE=national`.
   `thresholds.market_region()` härleder marknaden ur `REGION_ANCHOR` — alla
   femton regioner.
3. **Ersättningsrätten nådde aldrig en förare.** `compensation_eligible` och
   `compensation_amount_kr` räknades ut av `core/compensation.py` men RPC:n
   skrevs innan fälten fanns och exponerade dem aldrig.

Entitlement (`core/entitlement.py`) är en port av `current_entitlement`, med
båda vägarna kvar: förartoken **och** inloggad ägare via Supabase-JWT. Att
bara ta med den första hade återinfört buggen som
`20260902000005_entitlement_for_authenticated_owners.sql` en gång rättade —
en ägare utan parad enhet såg tomt, oskiljbart från "inga störningar".

Ett obehörigt anrop får tomt flöde med `reason`, inte 403: skärmen ska bete
sig som förut, men felsökningen ska inte kräva en databasfråga.

## Kommandon

| Kommando | Gör |
|---|---|
| `dump_truth` | Skriver databasens sanning till `schema/` |
| `seed_rules` | Fyller `ScoringRule` från scoring.js |
| `poll_rail` | Hämtar och poängsätter tågstörningar. `--dry-run` |
| `poll_road` | Trafikverkets väghändelser. `--counties skane,stockholm` eller `all` |
| `review_uncertain` | AI-granskar osäkra tips. `--dry-run` |
| `purge_old --days 7` | Retention. `--dry-run` visar utan att radera |

## Källorna, och hur man ser att de lever

Sex källor: Trafikverket järnväg, Trafikverket väg, SL, Västtrafik,
Trafiklab och SMHI. Vägen var den sista som låg kvar i Node -- både
`taxi_relevance.py` och `text_scoring.py` hade en gren som kastade
`NotImplementedError("no road source in Django")`. Den är portad nu
(`core/sources/trafikverket_road.py`).

**Vägen är kontext, inte tips.** `score_road_alert` kapar vägpoängen till
max 15, och `/api/alerts` skickar väghändelser i ett eget fält (`context`)
i stället för i tipslistan. Skälet är mätbart: en vanlig förmiddag i Skåne
gav 129 vägrader mot 5 kollektivtrafiktips. En olycka försenar dem som
redan sitter i bil -- ingen lämnar sin bil i en kö för att ta taxi. Det
enda verkliga taxifallet, en avstängning som ställer in en busslinje,
kommer redan som ett eget kollektivtrafiklarm.

**`core/coverage.py`** svarar på frågan "hämtar vi något i län X?" län för
län, genom att lägga ihop tre saker som annars ser identiska ut i en tom
tabell: källan finns inte (404 hos Trafiklab), källan svarade tomt, eller
nätet är litet. Operatörsutfallen kommer från `SourceStatus.detail`, som
poll_trafiklab fyller per operatör -- summan ensam döljer att en region
tyst fallit bort.

**`SourceStatus` (core/health.py)** skriver en rad per källa vid varje
hämtning: gick den igenom, hur många larm, hur många tips, och felet om det
blev fel. Den finns för att en död källa och en lugn trafikdag ser
*identiska* ut i `source_events` -- båda är noll rader. Upptäckt när
Trafiklabs nyckel svarade `429 has exceeded its quota` på samtliga fjorton
regioner utan att något i systemet visade det. Pipeline-vyn (avsnitt 2 på
localhost:4000) läser tabellen och färgar källan röd.

## "Vad gör resenären i stället?" — core/alternatives.py

Det är frågan som avgör om en störning är värd att köra till, och svaret
fanns redan i pipelinen utan att nå fram: järnvägen räknade ut nästa avgång
och läste Trafikverkets `ReplacementTraffic`, textkällorna matchade "buss
ersätter" för att sätta rätt tier -- och sedan blev allt det bara ett tal i
en poängformel. Föraren fick se poängen, inte skälet.

Nu bär varje tips `travel_options` i API-svaret:

    Nästa avgång 14:35 (om 22 min) · Buss ersätter
    Sista avgången härifrån
    Nästa avgång gick 10:16

Tre saker är medvetna:

1. **Klockslaget, inte bara minuterna.** `next_departure_minutes` mättes när
   tipset skrevs och åldras med det -- ett tips från för 20 minuter sedan
   påstod "om 45 min" när sanningen var 25. `next_departure_at` är absolut,
   och minuterna räknas om vid varje läsning.
2. **Källans egna ord, aldrig våra.** Vi hittar aldrig på ett alternativ.
   En förare som kör till en perrong där ersättningsbussen redan står gör en
   bomresa; ett tomt fält kostar ingenting.
3. **Formuleringen bor i backend.** Samma skäl som poängtrösklarna: två
   klienter som skriver om samma mening själva börjar förr eller senare säga
   olika saker. Appen väljer bara färg -- sista avgången är grön (ingen tar
   sig hem själv), en angiven ersättningsbuss är grå (resenären behöver
   sannolikt ingen taxi).

## Nästa avgång — signalen som blev data

`Opportunity.next_departure_minutes` och `is_last_departure` skrivs av
järnvägspipelinen. Båda har räknats fram sedan Fas 2, men överlevde bara
som en mening i `reasons` ("nästa avgång först om 322 min") -- omöjlig att
filtrera, sortera eller kalibrera mot. Det är skillnaden mellan att en
signal finns och att den går att använda.

NULL betyder "vet inte", inte "ingen lucka": bara källor med tidtabell kan
svara. SL:s och Västtrafiks avvikelsetexter innehåller ingen -- "Linje 4 är
inställd" säger inget om när nästa går. Täckningen syns i avsnitt 5b i
pipeline-vyn, och är i sig måttet på hur långt Transport Gap (P1) kommit.

## AI-granskningen — var den gör nytta

Körs **bara** på `confidence: low`. Efter tågsignalerna ligger alla
tågtips på `high`, så kommandot rapporterar "inga osäkra tips" — det är
rätt svar, inte ett fel. Osäkerheten sitter i buss- och spårvagnsflödena,
där bedömningen görs på fritext:

    85  "Hållplats Elektravägen inställd pga vägarbete"   ← ett vägarbete
    97  "Linje 4 klockan 22:59 är inställd från Angered"  ← rimlig
    35  "Ny avgångstid"                                    ← säger inget

Fyra regler gör det säkert:

1. **Får bara sänka.** `min(regelpoäng, modellpoäng)`, klämt både i
   `genkit.py` och i `RailAssessment.save()`. Ett falskt högt tips kostar
   en förare en bomresa; ett falskt lågt kostar ingenting.
2. **Cache på normaliserad form**, inte titel — tågtitlar bär tågnummer
   och klockslag och är nästan unika (28 av 28 i en mätning).
3. **Fallerar anropet behålls regelsvaret.** Blockerar aldrig en skrivning.
4. Kräver `GEMINI_API_KEY` i `.env`. Utan den gör kommandot ingenting.

## Tågpoängen — vad Fas 2 rättade

Node gav **alla** inställda tåg samma poäng. Mätt samma stund:

| | Poängfördelning |
|---|---|
| Node | `{97: 26, 85: 11, 0: 1}` — i praktiken en nivå |
| Django | `{85: 2, 78: 6, 61: 2, 55: 4, 45: 1}` — fem nivåer |

Orsaken var inte saknad data utan bortkastad data. Trafikverket svarar med
varje annonserad avgång; Node frågade bara efter de störda och kunde
därför aldrig veta om ett inställt tåg hade en ersättare. Django hämtar
hela fönstret och härleder tre signaler:

| Signal | Effekt |
|---|---|
| Nästa avgång inom 30 min | `vehicle_cancelled`, tak 55 — ingen är strandsatt |
| Sista avgången härifrån | `line_paused`, golv 85 |
| Långt glapp (t.ex. 322 min) | `line_paused`, 78 |
| Stor station (≥20 avgångar) | +6, rangordnar mellan lika starka |

Resultatet i praktiken: Haparanda (sista tåget) 85, Falkenberg (nästa om
322 min) 78, Mölndal (nästa om 5 min) 55.

## Push-invarianten — läs innan du skriver till opportunities

`notified_at` skrivs **bara** av push-steget. I Node överlevde det av en
tillfällighet: supabase-js skickar bara angivna kolumner.

Djangos `save()` och `update_or_create()` skriver **hela raden** och skulle
nolla fältet vid varje pollcykel — push skulle tro att tipset aldrig
notifierats, och varje förare få samma notis varje minut.

Använd därför `core.repository.upsert_opportunities()`, som namnger sina
kolumner explicit. `test_notified_at_survives_upsert` vaktar det.

## `dump_truth` — därför finns den

`get_smart_alerts` är omdefinierad **sju gånger** över 25 migrationsfiler,
och filnamnen sorterar inte i tidsordning. För att veta vad funktionen gör
*just nu* måste man läsa alla sju och lista ut vilken som är sist. Det är
varför arbetet i den här kodbasen krävt databasfrågor i stället för
kodläsning — ett läsbarhetsproblem, inte ett databasproblem.

Kommandot skriver databasens nuvarande sanning till `schema/`:

| Fil | Innehåll |
|---|---|
| `functions.sql` | De 8 SQL-funktionerna som de **faktiskt** ser ut. Sju versioner blir en. |
| `tables.md` | Alla tabeller med kolumner, typer och radantal |
| `models_reflected.py` | `inspectdb`-spegling för läsning |
| `constants.md` | Poängkonstanter och var de bor — visar dubbleringen |

Kör efter varje migration och checka in resultatet.

**Vad `constants.md` avslöjar:** talet `50` finns på fyra ställen i tre
språk — `fcmPush.js:179`, `severity_labels.dart:61`, `api_client.dart:802`,
`viz/server.js:104` — utan att något håller ihop dem. Listan ska krympa när
poängreglerna flyttas till `ScoringRule` i Fas 2. Gör den inte det har
flytten inte blivit av på riktigt.

`schema/` är genererad. Redigera inte för hand.
