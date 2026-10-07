# Bearbetningen: mätt läge och förbättringar

Fyra spår har mätts parallellt mot produktion 2026-10-07, **enbart läsande**
(`SELECT`/`EXPLAIN`/`SHOW`, inga skrivningar, inga `manage.py`-kommandon i prod).
Varje siffra går att återskapa; frågan står i rapporten den kommer från.

Fönster: `ai_call` 2026-10-04 → 10-07, `pg_stat_statements` sedan 2026-09-27
(≈10,5 dygn), tabellräkningar vid mättillfället.

---

## 1. Läget i korthet

Fem saker sticker ut, i den ordning de skadar produkten:

| # | Vad | Mätta siffror | Typ |
|---|---|---|---|
| **1** | **Ingen notis har någonsin levererats** | `push_delivery` = **0 rader**, `notify` svarar `no_devices`; 867 tips har ändå `notified_at` | Akut |
| **2** | **AI-vägen är i praktiken avstängd** | `brief` 12,5 % lyckade, `extract` 30,6 %; sedan 14:24Z är felet 429 (kvoten) | Akut |
| **3** | **Retry-stormen äter AI-kvoten** | 7 854 `brief`-anrop för 1 238 tips = **6,34 försök/tips**, upp till 133 | Akut |
| **4** | **Notisgrinden `ai_gate` har aldrig körts** | `purpose='gate'` = **0 anrop**, 154 `*.ambiguous`-tips, 76 av dem notifierade | Akut |
| **5** | **PredictHQ är död** | 402 "subscription ended", **33 misslyckanden i rad** sedan 2026-09-26 | Akut |
| 6 | **Vägens `active_to` glider varje poll** | **119,7 M raduppdateringar** mot 141 k inserts på 10,5 dygn | Struktur |

---

## 2. Fynd 1 — notisvägen: urvalet filtrerar bort varje telefon

`core/notify._devices` (rad 872) väljer enheter med **legacy-fältet**:

```python
active = set(Company.objects.filter(status__in=("trial", "active"))...) \
       | set(Company.objects.filter(subscription_status="active")...)
return [d for d in rows if d.company_id in active]
```

I den kontobaserade modellen bor rätten i `fleet_trial` och `fleet_subscription`
— inte i `companies.status`. Mätt i prod:

```
companies:  Taxi Tips Demo AB  status=active    subscription_status=active
            Abbes Person       status=canceled  subscription_status=incomplete_expired
devices:    1 rad, 1 med push_token
push_delivery: 0 rader (hela tabellens liv)
```

`Abbes Person` har ett giltigt prov (`fleet_trial` aktiv till 10-14) och ett
tilldelat medlemskap, men `_devices` ser `canceled` → telefonen filtreras bort
**innan `push_gate` tillfrågas** → `no_devices` → ingen leveransrad skrivs.

Det förklarar varför `manage.py send_test_push` *fungerar* (den loopar över
`Device.objects.filter(company_id=…)` direkt, förbi urvalet) medan en riktig
störning aldrig når telefonen. Vår tidigare grindfix (`fleet/push_gate.py`) är
nödvändig men **otillräcklig**: urvalet står före grinden.

**Åtgärd:** `_devices` ska fråga samma sanning som allt annat — `fleet.access.
company_window(company_id).ok` — i stället för `companies.status`. En telefon
vars bolag har en giltig period (prov, betald, frist) ska med; en spärrad eller
uppsagd ska inte.

---

## 3. Fynd 2–4 — AI-vägen: kvot, läcka och en storm som äter budgeten

**Kostnaden är inte problemet.** 9 116 anrop på fyra dygn = 0,386 USD ≈
**0,97 kr/dygn**. Problemet är att anropen inte lyckas och att de görs om.

| purpose | anrop | ok | ok % | försök/tips |
|---|---:|---:|---:|---:|
| `brief` (var 2:a min) | 7 854 | 979 | **12,5 %** | **6,34** |
| `extract` (var 5:e min) | 1 259 | 385 | **30,6 %** | 1,89 |
| `report` (1/dygn) | 3 | 1 | 33 % | 1,00 |
| `gate` (i push-cykeln) | **0** | — | — | — |

**Felklassen skiftar över tid:**
- **10-05/10-06:** `GenkitError: INTERNAL … [Errno 24] Too many open files`
  (2 097 + 2 682 anrop). Containrarna kör `ulimit -n = 1024`. Mekanismen är
  bekräftad i biblioteket: `genkit_google_genai` bygger sin klient som
  `loop_local_client(...)`, cachen nycklas på den körande event-loopen, och
  `core/ai_client._run` gör `asyncio.run(...)` **per anrop** → en ny klient per
  anrop som aldrig stängs. Läckan kunde **inte** reproduceras lokalt (0 läckta fd
  i fyra tester), så *var* de 1 024 fd:na sitter är **inte mätt**.
- **10-07 eftermiddag:** `RESOURCE_EXHAUSTED (429)` — kvoten är slut. AI-vägen är
  i praktiken avstängd sedan 14:24Z.

**Stormen är kodmässig, inte cache-relaterad.** `core/briefs.run()` skriver
`brief_key` **först när anropet lyckats**; `due()` väljer just de tips vars
`brief_key` saknas. Ett misslyckat anrop lämnar alltså tipset i urvalet och nästa
körning (2 min senare) försöker igen — **ingen backoff, inget försökstak, ingen
negativ cache**. Under EMFILE-dygnet maldes samma ~30 tips (`AI_BRIEF_MAX_PER_RUN
= 30`, topp-30 på `demand_score`) varannan minut hela dygnet.

`spend()` räknar **alla** `ai_call`-rader, även misslyckade → stormen äter
`AI_DAILY_CALL_CAP = 3000` (10-05: 3 488 anrop, dvs. över taket) och svälter
`extract` och grinden. **Det är den största förlusten i AI-vägen: 2 564 tips
borde granskats, 385 gjorde det — 70 % blev aldrig granskade.**

**`ai_gate` har aldrig anropats.** 154 tips har `rule_id LIKE '%.ambiguous'`,
76 av dem fick `notified_at`, och `purpose='gate'` finns i **0** rader. Varför är
inte mätt (cacheträff, `failOpen` eller `deferred` ger alla noll `ai_call`-rader)
— och det är den första mätningen som ska göras.

### Åtgärder, i ordning

1. **Negativ cache + backoff i `briefs`** (och `review_uncertain`): skriv
   `brief_key` även vid fel med försökstal/tidsstämpel, och försök igen tidigast
   efter N minuter, högst K gånger. Liten ändring, stoppar stormen, räddar hela
   dagsbudgeten.
2. **Rör inte dagsbudgeten för anrop som inte gick fram:** låt `spend()` räkna
   lyckade anrop mot taket (eller räkna felanrop separat), så en felstorm inte kan
   stänga av AI:n för resten av dygnet.
3. **En event-loop för hela processen** i `core/ai_client._run` (kör `generate` i
   en egen tråd med en långlivad loop, eller stäng klienten per anrop) så att
   bibliotekets loop-nycklade klientcache träffar. Höj `ulimit -n` som skydd.
4. **Mät fd-kurvan** (`len(os.listdir('/proc/1/fd'))` före/efter varje anrop i en
   timme) — den enda mätning som avgör var läckan sitter.
5. **Rätta `ai_gate`** och lägg en räknare i notissvaret
   (`gated`/`blocked`/`failOpen`/`cached`) så att grinden syns i drift.
6. **Kvot:** nyckeln klarar inte volymen ens utan stormen. Antingen betald nyckel,
   eller skriv `brief` bara för tips som faktiskt ska notifieras (§5).


---

## 4. Optimeringar i bearbetningen (rangordnade, mätta)

| # | Åtgärd | Uppmätt nuläge | Vinst | Risk |
|---|---|---|---|---|
| 1 | **Sluta skriva om `active_to` varje poll** (Trafikverket väg, `poll_road.py:93-96`) | `opportunities` **59,7 M** + `source_events` **59,6 M** raduppdateringar mot 141 k inserts (10,5 d). `active_to` sätts till `min(source_end, now+4h)` → nytt mikrosekundsvärde varje runda, så `_is_distinct` ser "ändrat" och varje väghändelse skrivs om var 90:e sekund | Tar bort merparten av ~120 M uppdateringar: mindre WAL, bloat (`n_dead_tup` 13 486/6 756), CPU och latens i hela pollcykeln | Medel — `active_to` styr hur länge ett vägtips visas; `min(source_end, horizon)` måste bestå |
| 2 | **Index på `rail_assessment(opportunity_id)`** | 17,4 mdr lästa rader, ~69 min DB-tid sedan 09-27 | Sekunder i stället för minuter vid FK-prövning och gallring | Låg |
| 3 | **Släpp `gtfs_stop_departures`** | **1 998 961 rader / 457 MB**, 0 anrop sedan statistikstarten | 644 MB disk (med index), mindre backup | Låg — verifiera att ingen kod läser den |
| 4 | **Städa döda index** på `opportunities`/`source_events` | 0 `idx_scan` sedan 09-27 | ~13 MB + mindre skrivförstärkning på just de två mest skrivna tabellerna | Låg |
| 5 | **Index på `stop_area(operator)` eller cacha hållplatsuppslaget** | 164 M lästa rader, ~9 min | Kortare poll-runda | Låg |
| 6 | **`combine_signals` läser om alla tips var 60:e sekund** | Producerade **3 rader totalt** | Skippa körningen när `opportunities` inte ändrats sedan förra varvet | Medel (misstänkt, ej kvantifierat i SQL) |
| 7 | **Batcha `upsert_source_events`** (en sats per rad) | 65 M enstaka satser | Färre klientturer och mindre parse | Låg |
| 8 | **Städa `_backup_*_20260910`** | 2 tabeller, ~1 MB | — | Låg |

Kvoterna är inte problemet: ResRobot 4 054/25 000 (≈17 000/mån projicerat),
Swedavia 1 160/9 000, AIS **1** anslutning i prod (taket är 3 per konto och IP).

**Kadens-fyndet (från kedjekartläggningen):** `push_cycle` kör var 30:e sekund
och `write_briefs` var 2:a minut — men det finns **0 enheter att skicka till**
(§2) och `combine_signals` har gett 3 rader totalt. Att hoppa över
`write_briefs` när det inte finns någon mottagare sparar ~2 600 AI-anrop/dygn
utan att ändra ett enda tips.

---

## 5. Genkit: var, hur och varför

AI:n ska läsa **fakta**, aldrig sätta poäng (invariant 9). Med den regeln är
ordningen given av vad rådatan faktiskt visar:

**1. Hållplats och klockslag ur SL:s fritext (punkt 5 i `api-field-inventory`).**
Mätt: 3 926 SL-rader, **3 030 (77 %) har tomma `areas`** och **0 har `geometry`**
→ dagens SL-tips är platslösa. Men **3 268 (83 %) har " från " i `description`**
och **1 657 (42 %) har både `kl HH:MM` och " från "**. Det är exakt vad en modell
kan läsa ur en mening: `places` + avgångstid. Effekt: platslösa tips blir
placerade, kan mätas mot körområdet och får en "Kör dit"-väg i appen. Grind:
`places` får bara fyllas med strängar som finns i texten (samma princip som
`briefs.valid`). Kostnad: en `extract`-insats på de tips som saknar `places`.

**2. `ai_gate` — få den att köra alls.** 154 `*.ambiguous`-tips, 76 notifierade,
0 gate-anrop. Det är ingen ny funktion, bara en trasig koppling; utan den kan
varje ny AI-insats inte skyddas.

**3. Förarbeskedet (`brief`) — låt det läsa fakta vi redan läst ut.** Beskedet
skrivs i dag för varje medel/starkt tips, även de utan mottagare (7 854 anrop).
Skriv det bara för tips som faktiskt ska notifieras, och låt underlaget vara
`TipFacts` (redan utlästa fakta) i stället för rå text — då blir raden både
kortare och omöjlig att fylla med påhitt.

**4. Orsakstexten (punkt 17).** `source_events` har **0 rader** med `operative`-
källa, så den vägen är inte öppen än; järnvägens `cause`-kod finns men används
inte i poängen. Effekt: "varför" i tipset — men kräver att källan börjar sparas
först.

**5. Vad som INTE ska göras.** Inte poäng, inte notisbeslut, inte alternativ och
inte koordinater (invariant 2/15: vi hittar aldrig på ett alternativ eller en
siffra), och inte att tolka vad ett externt fält "betyder" när fältets innebörd
är omätt (`Deviation.Suspended`, punkt 18) — där ska mätas först.

### Mätplan

| Mått | Före | Efter (mål) |
|---|---|---|
| `brief` försök/tips | 6,34 | < 1,5 |
| `brief` ok-andel | 12,5 % | > 90 % |
| `extract` lyckade / `low`-tips | 385 / 2 564 | > 80 % granskade |
| `purpose='gate'`-rader | 0 | > 0 varje dygn, med `blocked` synligt |
| SL-tips med tomt `places` | 77 % | > 50 % placerade |
| "dagstaket nått" i loggen | 1 dygn av 4 | 0 |
| Påhittade siffror i `brief` | 63 kastade, skäl ej separerade | 0, med skälet loggat per avvisning |
| DB-uppdateringar mot inserts | 119,7 M / 141 k | −90 % |

`manage.py eval_ai` mot `core/fixtures/golden_tips.jsonl` före och efter varje
prompt- eller modelländring (AGENTS §6.9).


---

## 6. Tipsförbättringar ur själva datan

| # | Vad datan visar | Förbättring | Effekt |
|---|---|---|---|
| 1 | **PredictHQ: 402 "subscription ended", 33 misslyckanden i rad sedan 09-26.** AGENTS §8 säger att appens evenemang kommer därifrån | Förnya abonnemanget eller peka om `EVENTS_*_APP_REFERENCE` till en källa som svarar (Ticketmaster pollas och fungerar) | Evenemangslistan i appen slutar vara tom |
| 2 | **SL: 77 % av tipsen har tomma `areas`, 0 har geometri** — men 83 % av texterna bär " från " och 42 % även klockslag | Läs ut plats + tid (§5.1) | Platslösa Stockholmstips blir placerade och körbara |
| 3 | **Vägen skriver 6 735 tips per poll** och dominerar både `opportunities` och skrivlasten; av 6 780 aktiva vägrader visas **6** | Sluta hämta icke-olyckor, eller visa dem som räknare i pipeline-vyn | Friar kvot, DB och poll-tid; förarens lista oförändrad |
| 4 | **15 069 tips är `ignore`** (unknown 5 009, train 4 583, road 3 730, bus 1 731) — 35 % av alla tipsrader | Skriv `ignore`-tips bara inom `FEED_MINOR_MAX_AGE_HOURS` (12 h) | ~35 % färre tipsrader, snabbare `feed_for` |
| 5 | **2 564 `low`-tips, bara 385 granskade** (70 % aldrig) | Laga AI-stormen (§3) | Granskningen når fram; fler osäkra tips blir rätt klassade |
| 6 | **`unknown`-hinken är stor** (mode-koden ger upp) | Fall tillbaka på källans `routes`/`stops` och `SERIOUS_RE` i stället för att ge upp (`mode.classify_mode:50`) | Tusentals rader blir förklarbara i stället för svarta hål |
| 7 | **4 feedback-rader, 0 rapporter, 0 favoriter** | Få igång facit i appen | Utan det är `calibration_report`, `audit_tips` och AI-höjningens tak **omätbara** — inget annat förslag går att verifiera på utfall |
| 8 | `smhi` har 15 rader totalt (sedan 10-07); `thesportsdb` inte pollad sedan 09-26 | Bestäm om källan ska användas; annars stäng av den | Mindre brus i källhälsan |

Betygskedjan i sig ser rimlig ut mätt: 143 aktiva transit-tips (3 `high
line_paused`, 6 `line_delayed`), 26 flyg (alla `medium` — flyg blir aldrig Stark,
som avsett), 1 färja, och vägens 15-poängstak håller (`road` kan aldrig nå hög
nivå). Det är **inte** poängsättningen som är problemet — det är att tipsen inte
kommer fram och att de osäkra aldrig granskas.

---

## 7. Mina egna fel på vägen (rättade av mätningarna)

Skrivet för att nästa läsare inte ska upprepa dem:

1. **"Retentionen kör inte"** — fel. `purge-old` är schemalagd (3600 s) och
   `TAXITIPS_BEAT_DISABLE` är inte satt. Bevis: `min(end_time)` för tips är
   exakt sju dygn, och 717 983 rader har gallrats sedan 09-27. Att `source_events`
   visade 18 dygn beror på att 8 022 långlivade situationer har `active_to` i
   framtiden — gallringen nycklar på `coalesce(active_to, created_at)`, vilket är
   avsiktligt.
2. **`[Errno 2]`** — fel. Felet var `[Errno 24] Too many open files`; min
   `LIKE '%Errno 2%'` matchade "Errno 24". Läs hela feltexten, inte ett prefix.
3. **"Kvoten dödar AI:n"** — bara delvis. Kvoten (429) dominerar 10-07
   eftermiddag; `Errno 24` dominerar 10-05/10-06. Två olika fel i samma tabell.

## Mätmetod

`pg_class.reltuples` och `pg_total_relation_size` för storlekar;
`pg_stat_user_tables.n_tup_*` för skrivlast; `pg_stat_user_indexes.idx_scan` för
indexanvändning; `pg_stat_statements` för långsamma frågor; `EXPLAIN` (aldrig
`ANALYZE` på skrivande sats) för planer; `source_status.detail` för kvoter;
`ai_call` för AI-anrop. `reltuples` är uppskattningar — exakta tal togs med
`count(*)`. Allt läsande; inget skrevs i prod.

