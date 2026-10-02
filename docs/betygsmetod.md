# Så bedöms ett tips — läge, omständigheter och styrka

*Omskriven 2026-10-02 ur koden. Varje siffra har en fil i `taxitips-backend/`.
Ändras en regel ska den här filen ändras i samma commit.*

---

## 1. Frågan

Föraren undrar en sak: **står det folk som behöver taxi, och hur troligt är det att
de tar en?** Bedömningen svarar i två delar:

| Del | Frågan | Var |
|---|---|---|
| **Läge** | Hur strandsatta är resenärerna? (nästa resa, sista avgången, hela linjen, ersättningstrafik) | `core/scoring.py` (tåg), `core/text_scoring.py` (fritext), `core/flight_scoring.py`, `maritime/tips.py` |
| **Omständigheter** | Gör tid, ersättningsrätt, väder och stationens storlek att de tar taxi? | `core/taxi_context.py` |

**Poäng = läge + omständigheter (högst +20).** Poängen avgör ordningen i listan.
**Styrkan** (Stark / Medel / Svag) avgör färgen, filtret och notisen. Den räknas
**när tipset skrivs**, sparas i `Opportunity.level` och läses därifrån av flödet,
notiserna och favoriterna.

Föraren ser aldrig poängen, bara styrkan och **skälen** (`Opportunity.factors`):
högst fyra korta rader på enkel svenska, både det som talar för och det som talar emot.
Vi visar fakta. Föraren avgör.

---

## 2. Styrkan — en regel för alla källor

`taxi_context.final_level`:

| Styrka | Villkor |
|---|---|
| **Stark** | poäng ≥ 60 **och** strandsatt (inget alternativ inom 30 min) **och** inte låg säkerhet |
| **Medel** | poäng ≥ 35 (eller ≥ 60 utan strandsättning) |
| **Svag** | poäng < 35, ersättningstrafik angiven, eller tipset har tagit slut |

Två hårda regler:

1. **Stark kräver strandsättning.** Omständigheter kan aldrig ensamma göra ett tips
   Starkt. En enstaka inställd buss i rusningen är fortfarande en enstaka buss.
2. **Omständigheter räknas inte** när resenären har ett alternativ inom 10 min,
   ersättningstrafik är insatt, eller läget är under 25 (inget att förstärka).

Flyg och färja är aldrig strandsatta i den här meningen (de som landar har ofta en
plan) och blir därför högst Medel.

---

## 3. Notisen

`thresholds.is_notify_worthy` + `notify.candidates`: **Stark**, poäng ≥ 60
(`NOTIFY_SCORE_FLOOR`), typen `line_paused` / `vehicle_cancelled` / olycka, inget
angivet alternativ och ingen AI-ändring. Sedan förarens egna val (kategorier, lägsta
styrka, område, paus).

I praktiken: hela linjen står still, sista avgången, eller ett glapp där
omständigheterna gör läget Starkt.

---

## 4. Läget per källa

### 4.1 Tåg — Trafikverket (strukturerat, säkrast)

`core/scoring.py` `classify`. Glappet mäts från den inställda avgången och ändras inte
medan tipset lever.

| Läge | Poäng | Strandsatt | `rule_id` |
|---|---|---|---|
| Ersättningstrafik insatt | 30 | nej | `train.vehicle_cancelled.replacement` |
| Inställt, nästa resa ≤ 10 min | 15 | nej (omständigheter räknas inte) | `train.vehicle_cancelled.alternative_soon` |
| Inställt, nästa resa 11–20 / 21–30 min | 28 / 40 | nej | `train.vehicle_cancelled.alternative_soon` |
| Inställt, nästa resa 31–59 min | 50 | ja — Stark först med omständigheter | `train.line_paused.long_gap` |
| Inställt, nästa resa ≥ 60 min | 68 | ja | `train.line_paused.long_gap` |
| Sista avgången | 80 | ja | `train.line_paused.last_departure` |
| Inställt, okänt när nästa går | 50, låg säkerhet → högst Medel | ja | `train.line_paused.unknown` |
| Försenat 30–59 / ≥ 60 min | 40 / 55 | nej / ja | `train.line_delayed` |

Nästa resa frågas i första hand från reseplaneraren (mot samma slutstation), annars
stationens nästa tåg. Föraren ser bara resan, aldrig vilken tjänst som svarade.

### 4.2 Buss, spårvagn, tunnelbana — SL, Västtrafik, Trafiklab (fritext)

`core/text_scoring.py` `classify_transit_alert`, prövas i ordning:

| Läge | Poäng | Strandsatt |
|---|---|---|
| Alternativ angivet ("ersättningsbuss", "övriga avgångar") | 25 | nej |
| Känd nästa avgång (SL slår upp den) | tågens glappskala | över 30 min |
| Hela linjen står still ("ingen trafik", "trafikstopp") och inte en enstaka tur | 70 | ja |
| **En enstaka avgång** ("Inställd avgång", "kl 16:59 är inställd", "delsträcka", "hänvisas till nästa avgång") | 20 | nej |
| "Reducerad hastighet" | räknas som försening | nej |
| Allvarligt men oklart (spårtrafik) | 45, högst Medel | nej |
| Buss inställd utan klockslag | 45 | nej |
| Försening: spårtrafik / buss | 30 / 15 | nej |
| Oklassad | högst 30 | nej |

En enstaka avgång slutar gälla 45 min efter sitt klockslag (`core/ingest.py`).
`ScoringRule` i databasen innehåller bara **tak** för de här lägena
(`seed_rules`), aldrig golv. En regelrad får skärpa men aldrig lyfta.

### 4.3 Flyg — Swedavia

Räknar **plan, aldrig resenärer** (invariant 15). Bara 21:00–06:00.

| Regel | Villkor | Poäng (tak) |
|---|---|---|
| `flight.arrival_wave` (Arlanda, Landvetter) | ≥ 8 resp. ≥ 3 ankomster på 30 min | 45 + 5 per extra ankomst (80) |
| `flight.last_arrival` (övriga) | Inget mer landar inom 2 h | 40 + 6 per extra ankomst (65) |
| påslag | Plan ≥ 40 min sena | +6 per plan, högst +18 |
| påslag | Fönstret börjar 23–03 | +10 |

Säkerhet: hög när minst hälften av planen har livetid, låg mer än 6 h fram.

### 5.4 Färja — AIS

`maritime/tips.py`: fartyg ≥ 170 m 55 p, ≥ 130 m 45 p, ≥ 100 m 35 p; +15 kl. 21–06;
tak 85. Säkerhet medel när fartyget saktat in i hamn, låg när bara AIS-ETA finns
(handinmatad). Hur många som reser framgår inte av AIS och står så i motiveringen.

### 5.5 Väg — Trafikverket

**Tak 15 poäng** (invariant 3, `thresholds.ROAD_SCORE_CAP`): en olycka försenar dem
som redan sitter i bil, den strandsätter ingen. Bara olyckor visas för föraren.
Olycka 15, avstängd väg 15, kö 10, vägarbete 5–8.

### 4.4 Färja — AIS

`maritime/tips.py`: fartyg ≥ 170 m 55 p, ≥ 130 m 45 p, ≥ 100 m 35 p; +15 kl. 21–06;
tak 85. Högst Medel. Hur många som reser framgår inte av AIS och står så i motiveringen.

### 4.5 Väg — Trafikverket

**Tak 15 poäng** (`thresholds.ROAD_SCORE_CAP`): en olycka försenar dem som redan sitter
i bil, den strandsätter ingen. Inga omständigheter. Bara olyckor visas.

---

## 5. Omständigheterna

`core/taxi_context.py`. Räknas mot **den drabbade avgångens tid** (tåg: avgången,
fritext: klockslaget i texten eller nu), i svensk tid. Sammanlagt högst **+20**.

| Omständighet | Påslag | Föraren läser |
|---|---|---|
| Vardag 06–09 | +8 | Morgon en vardag – folk ska till jobbet |
| Vardag 15–18 | +5 | Eftermiddag en vardag – folk ska hem |
| Alla dagar 21–24 | +6 | Sent på kvällen – färre alternativ |
| Alla dagar 00–05 | +10 | Natt – nästan inga andra sätt att ta sig hem |
| Rätt till ersättning för taxi | +8 | Resenären kan få taxin betald (upp till 2 960 kr) |
| Kraftigt väder: ≥ 3 mm/h, byar ≥ 18 m/s, snöfall, åska ≥ 50 % | +10 | Kraftigt regn / Snöfall / Hård blåst / Åska |
| Dåligt väder (SMHI-gränserna i `core/sources/smhi.py`) | +4 | Regn / Hård vind / … |
| Stor station (≥ 20 avgångar i fönstret) | +5 | Stor station – många resenärer |

**Ersättning** (lag 2015:953, `core/compensation.py`) påstås bara när väntan säkert når
huvudmannens gräns (20 min): känt glapp eller försening över gränsen, eller sista
avgången. För tåg bara regional trafik vi kan knyta till en huvudman: Pågatågen,
Västtågen, SL Pendeltåg, VTAB, samt Öresundståg/Krösatågen efter stationens län. SJ och
andra fjärrtåg lyder under EU-regler och får ingen rad. Reglerna ligger i
`region_compensation_rule` (`manage.py seed_compensation_rules`).

**Inte med än:** röda dagar räknas som vardag om de infaller mån–fre, och ett
evenemang som slutar räknas inte som omständighet.

---

## 6. Hur länge ett tips syns

| Vad | Slutar |
|---|---|
| Inställt tåg, känt glapp | 10 min efter att nästa resa gått, högst avgången + 1 h |
| Ersättningstrafik | avgången + 30 min |
| Försenat tåg | 10 min efter den nya avgången, högst + 1 h |
| Enstaka avgång i fritext | klockslaget + 45 min |

Flödet (`api.feed_for`) visar pågående tips plus de som tagit slut **de senaste 15
min**, som appen visar gråmarkerade under **"Nyss slut"**. Tips som börjar mer än
**2 h** fram visas inte. Sparade tips och notisloggen påverkas inte.

I appen är **Svaga dolda som standard**. Raden "N svaga tips dolda · Visa" och
brytaren "Visa svaga tips" i filtret tar fram dem.

---

## 7. Efter läget

| Steg | Vad det gör | Får det höja? |
|---|---|---|
| **AI-granskning** (Genkit) | Granskar tips med låg säkerhet | Styrkan räknas om från AI:ns poäng men aldrig uppåt förbi pipelinens egen (`thresholds.effective_level`). Ett AI-ändrat tips väcker ingen. |
| **Kombination** (var 60:e s) | Dubbletter slås ihop; knutpunkt +5; ankomst vid inställd kollektivtrafik +10 | Bara listordningen |
| **Personal döljer** | Tipset försvinner och skrivs aldrig över | — |

---

## 8. Hur föraren ser varför

I tipsets detaljvy, direkt under nästa avgång: **2–4 rader** med grön bock (talar för)
eller grått streck (talar emot), t.ex.

> ✓ Nästa tåg går först 45 min senare
> ✓ Resenären kan få taxin betald (upp till 2 960 kr)
> ✓ Morgon en vardag – folk ska till jobbet
> – Ersättningstrafik är insatt

Raderna kommer från `factors` i flödet. `GET /api/opportunities/<id>` fältet `grade`
bär samma rader plus regel, säkerhet och notisregel, för felsökning.
Den tekniska motiveringen (`reasons`) med påslagen i siffror finns för pipelinevyn,
inte för föraren.

---

## 9. Effekt, uppskattad mot prod 2026-09-25 – 10-02

Omräknat med SQL från sparade fält (glapp, sista avgången, alternativ, station,
avgångstid). Vädret är inte med, så uppskattningen är något försiktig.

| | Före | Efter |
|---|---|---|
| Tåg, Stark | 2 281 | ~514 |
| — nästa tåg inom 30 min | 1 412 Starka | 0 (446 Medel, 1 340 Svaga) |
| Fritext, Stark | 1 867 | ~73 (hela linjen, långa kända glapp) |
| — enstaka avgång (SL m.fl.) | 1 364 Starka | 0 (Svaga) |

---

## 10. Kvalitetskontroll — tre frågor, tre verktyg

| Fråga | Verktyg | När |
|---|---|---|
| Kommer datan in, och är den färsk? | `manage.py check_pipeline` (`/health/pipeline`) | Hela tiden (healthcheck) |
| **Är varje aktivt tips internt korrekt?** | **`manage.py audit_tips [--hours 24] [--json] [--strict]`** | Efter varje regeländring och dagligen |
| Hade tipsen rätt, mätt mot utfall? | `manage.py calibration_report` | Veckovis, när feedback finns |

`audit_tips` (`core/tip_audit.py`) är rent läsande och säker mot produktionen. Den prövar:

| Kontroll | Allvar |
|---|---|
| Poäng utanför 0–100 | fel |
| Vägtips över 15 | fel |
| Tips utan regel, motivering eller källhändelse | fel |
| Fryst "om X min" i sparad text | fel |
| Notis trots angiven ersättningstrafik | fel |
| Källhändelse som inte finns | varning |
| Sparad styrka följer inte gränserna (Stark < 60, Medel < 35) | varning |
| Notis på tips som inte klarar notisregeln i dag | varning |
| Starttid efter sluttid | varning |
| Visar en avgång som redan gått | varning |
| Låg säkerhet med betyget Stark utan AI-granskning | varning |
| Aktivt mer än 48 h framåt | info |

Första körningen mot lokal data (442 tips, 2026-10-01) hittade 25 vägtips på 27 poäng
(väderbonus över taket — rättat), 62 avslutade vägarbeten med starttid efter sluttid,
och att alla 442 sparade betyg följde den gamla tumregeln (≥ 60 = high — rättat; nya
skrivningar och notiser använder nu samma regel som flödet).

**Det viktigaste som saknas är facit**: förarnas 🚕/👍/👎 är i princip noll
(se `docs/bedomning-och-helhetsbild.md`). Ingen poängsättning är kalibrerad mot
verkligheten förrän den finns.

---

---

## 11. Kända svagheter

1. **Inget facit.** Förarnas 🚕/👍/👎 är i princip noll. Siffrorna ovan är
   principbaserade, inte kalibrerade. `calibration_report` visar när det finns nog.
2. **Röda dagar** räknas som vardagar.
3. **Flyg och färja** har inga "Därför"-rader än. De passerar bara styrkeregeln.
4. **Listan sorteras på poäng**, färgen kommer från styrkan: ett Medel på 65 utan
   strandsättning hamnar före ett Starkt på 62.
5. **AI-justeringar fladdrar** mellan pollning (var 90:e s) och granskning.
6. **Knutpunktsbonusen** i kombinationslagret finns bara för Skåne/Kastrup.
