# taxitips-backend

Django-tjänst som ska ersätta Node-workern: hämtning, klassificering,
poängsättning och push. Körs lokalt först, deployas till Coolify när
resultatet stämmer.

Ersätter **inte** Supabase. Auth, Stripe och appens API ligger kvar där
tills Spår B (app-API) eventuellt påbörjas.

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

| Kommando | Gör |
|---|---|
| `dump_truth` | Skriver databasens sanning till `schema/` |
| `seed_rules` | Fyller `ScoringRule` från scoring.js |
| `poll_rail` | Hämtar och poängsätter tågstörningar. `--dry-run` |
| `review_uncertain` | AI-granskar osäkra tips. `--dry-run` |
| `purge_old --days 7` | Retention. `--dry-run` visar utan att radera |

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
