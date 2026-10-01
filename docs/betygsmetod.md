# Så bedöms ett tips — metod, kriterier och kvalitetskontroll

*Skriven 2026-10-01 ur koden (inte ur minnet). Varje siffra har en fil och rad i
`taxitips-backend/`. Ändras en regel ska den här filen ändras i samma commit.*

---

## 1. Två mått, två frågor

Varje tips har **två** mått, och de svarar på olika frågor:

| | Vad | Avgör | Var |
|---|---|---|---|
| **Poäng** 0–100 (`demand_score`) | Hur stor störningen är enligt källans regelverk | **Ordningen** i listan och om en notis *kan* gå | `core/scoring.py`, `core/text_scoring.py`, `core/flight_scoring.py`, `maritime/tips.py` |
| **Betyg** Stark / Medel / Svag (`level`) | Hur troligt det är att det står folk kvar som behöver taxi | **Färgen** på kortet och filtret "Bara starka" | `core/thresholds.py` `customer_likelihood` |

Poängen räknas olika per källa, så **en 70 från tåget och en 70 från en bussfritext
betyder inte samma sak**. Betyget är därför det föraren ska läsa. Det räknas med
samma regel för alla källor och väger in sådant som poängen inte gör, t.ex. att
källan själv anger ersättningstrafik.

---

## 2. Kedjan från källa till kort

```
källhändelse ──▶ källans regel ──▶ poäng, typ, säkerhet, motivering
                                         │
                 påslag (väder +12 för fritext; natt för flyg/färja)
                                         │
                 AI-granskning (bara säkerhet = låg; får sänka, och omklassa)
                                         │
                 betyg (thresholds.customer_likelihood) ──▶ färg
                 notisregel (thresholds.is_notify_worthy) ──▶ får väcka någon?
                                         │
                 appen: kort + "Varför visas detta?" (backend förklarar, appen visar)
```

Allt räknas på servern. Appen räknar inte om betyget (utom en dokumenterad reserv
när fältet saknas, `severity_labels.dart`).

---

## 3. Betyget — beslutslistan

Kriterierna prövas i ordning. Det **första** som avgör vinner
(`core/thresholds.py` `customer_likelihood`, i ord: `explain_grade`).

| # | Kriterium | Utfall |
|---|---|---|
| 1 | Tipset har avslutats | **Svag** |
| 2 | Källan anger ersättningstrafik (`has_alternative`) | **Svag** — resenärerna har redan ett alternativ |
| 3 | Typ *hela linjen stoppad / sista avgången* (`line_paused`) | **Stark**, oavsett poäng |
| 4 | Typ *en avgång inställd* (`vehicle_cancelled`) och poäng ≥ 50 | **Stark** |
| 5 | Typ inställd (< 50), försenad linje, ankomstvåg, sista ankomst | **Medel** |
| 6 | Allt annat (enstaka buss sen, väg, oklassad fritext) | **Svag** |

**Konsekvens att känna till:** flyg och färja kan aldrig bli Stark (steg 5), hur många
som än landar. Det är medvetet: en ankomst är ingen strandsättning, de som landar
har oftast en plan.

---

## 4. Notisregeln — får tipset väcka en förare?

Strängare än betyget, med avsikt: en notis avbryter någon som kör
(`thresholds.is_notify_worthy`).

1. Typen måste vara *hela linjen stoppad*, *avgång inställd* eller *olycka/avstängd väg*.
2. Ingen angiven ersättningstrafik.
3. Poäng ≥ 50.

Sedan förarens egna val (kategorier, lägsta betyg, område) och att AI:n inte nyss
har ändrat tipset (`core/notify.py`). Flygvågor väcker ingen förrän tröskeln per
flygplats är kalibrerad.

---

## 5. Poängen per källa

### 5.1 Tåg — Trafikverket (strukturerad data, säkrast)

Ett tips skapas bara för inställt tåg eller ≥ 30 min försening, ett per station
(`core/sources/trafikverket_rail.py`). Regler i `core/scoring.py` `classify`:

| Regel (`rule_id`) | Villkor | Typ | Poäng | Säkerhet |
|---|---|---|---|---|
| `train.line_delayed` | Försenat ≥ 30 min | Försenad linje | 45 (försening + 20, tak 45) | Hög |
| `train.vehicle_cancelled.replacement` | Inställt, ersättningstrafik insatt | Avgång inställd | 40 | Hög |
| `train.vehicle_cancelled.alternative_soon` | Inställt, nästa resa ≤ 30 min efter | Avgång inställd | 55 | Hög |
| `train.line_paused.last_departure` | Inställt, sista avgången | Linjen stoppad | 85 | Hög |
| `train.line_paused.long_gap` | Inställt, nästa resa > 30 min efter | Linjen stoppad | 78 | Hög |
| `train.line_paused.unknown` | Inställt, okänt när nästa går | Linjen stoppad | 70 | **Låg** |

Påslag: **+6** på station med ≥ 20 avgångar i fönstret (tas bort av taket på försening).

**Nästa resa.** I första hand frågas reseplaneraren ResRobot (Trafiklab) om nästa
resa *mot samma slutstation*, annars nästa tåg från stationen (oavsett riktning).
Två tider, med avsikt:

* **Glappet** som poängen bygger på mäts från den *inställda* avgången och ändras
  inte medan tipset lever — annars skulle ett gammalt tips stiga i prioritet.
* **Avgången som visas** är den som går *efter nu*. Efter den inställda avgången
  frågas reseplaneraren om från nu, och en resa som redan gått visas aldrig som
  "nästa" (rättat 2026-10-01; förut föll tipset tillbaka till stationens nästa tåg
  åt fel håll fem minuter efter avgången).

### 5.2 Buss, spårvagn, tunnelbana — SL, Västtrafik, Trafiklab (fritext)

Två steg. Först grovpoäng ur texten (`core/taxi_relevance.py` `score_alert`):

| Text säger | Poäng |
|---|---|
| Allvarlig störning | 70 |
| … och "inställd / inga avgångar / ingen trafik" | 85 |
| … och ersättningsbuss | +5 |
| Försening / påverkan | 35 |
| Vid en känd knutpunkt (bara Skåne/Kastrup i dag) | +4 till +7 |
| Hiss, toalett, enstaka hållplats, omledning, allmän info | 0 (visas inte) |

Sedan typ och tak (`core/text_scoring.py`):

| Regel | Villkor | Typ | Poäng | Säkerhet |
|---|---|---|---|---|
| `{spår}.line_paused.whole_line_stop` | Hela linjen stoppad, inget alternativ | Linjen stoppad | ≥ 85 | Hög |
| `{spår}.vehicle_cancelled.stated_alternative` | Allvarlig, alternativ angivet | Avgång inställd | ≤ 55 | Medel |
| `{spår}.line_paused.ambiguous` | Allvarlig, i övrigt oklart | Linjen stoppad | ≥ 70 | **Låg** (Medel om SL/VT själva anger högsta allvar) |
| `{spår}.line_delayed.mediumish` | Försening | Försenad linje | ≤ 45 | Hög |
| `bus.vehicle_cancelled.serious` | Buss, allvarlig | Avgång inställd | ≤ 60 | Hög om "inställd", annars **Låg** |
| `bus.vehicle_delayed.mediumish` | Buss försenad | Enstaka försening | ≤ 25 | Hög |
| `{färdsätt}.unclassified` | Färdsätt okänt | Oklassad | grovpoängen | **Låg** |

*{spår} = tåg, tunnelbana eller spårvagn.*

Vid skrivning (`core/ingest.py`): **väder +12** vid nederbörd ≥ 1 mm/h, vind ≥ 12 m/s,
åska ≥ 30 % eller frysrisk (SMHI); aldrig på väg. Ersättningsrätt (Lag 2015:953)
skrivs som motivering men ändrar aldrig poängen.

### 5.3 Flyg — Swedavia

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

---

## 6. Efter källans regel

| Steg | Vad det gör | Får det höja? |
|---|---|---|
| **AI-granskning** (Genkit, var 5:e min) | Granskar tips med låg säkerhet: ny poäng, typ, finns alternativ | Ja, bara för låg säkerhet; annars bara sänka. Motiveringen får raden "AI sänkte/höjde: …". Ett AI-ändrat tips väcker ingen. |
| **Kombination** (var 60:e s) | Samma störning från två källor slås ihop; flera störningar vid samma knutpunkt +5; ankomst vid inställd kollektivtrafik +10 | Bara listordningen — inte betyg, poäng eller notis |
| **Utgång** | När tipset avslutas blir betyget Svag och det sjunker i listan | — |
| **Personal döljer** | Poäng 0, avslutas, skrivs aldrig över av pipelinen | — |

---

## 7. Hur föraren ser varför

I appen: kortet → **"Varför visas detta?"**

* **Bedömning** — typen i klartext.
* **Betyg** — t.ex. "Stark — Typ: hela linjen står still … → Stark oavsett poäng".
* **Så räknas betyget** (hopfällt) — kriterierna i ordning med bock/streck, poäng
  och regel (`rule_id`, golv/tak), säkerhet i ord och om tipset kan ge notis.
* **Därför** — källregelns motiveringar ("inställd avgång", "nästa resa mot
  Göteborg C 11 min efter den inställda avgången", "väder: hård vind").

Allt kommer från `GET /api/opportunities/<id>` fältet `grade`
(`core/api.py` `_grade_explanation`), så appen och förklaringen kan inte säga olika saker.

---

## 8. Kvalitetskontroll — tre frågor, tre verktyg

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
| Sparat betyg följer inte regeln | varning |
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

## 9. Kända svagheter — kräver beslut

Inget av detta är ändrat; varje punkt ändrar vad förarna ser.

1. **Inställt tåg med nästa tåg om 10 min kan bli Stark.** Regeln sätter 55 (61 på
   stor station) och kommentaren säger "tak 55", men inget tak finns, och 55 ≥ 50 ger
   Stark och notis. Kommentaren säger att de resenärerna "tar inte taxi". Förslag:
   tak 45 för `alternative_soon`.
2. **Väderbonusen går förbi taken**: buss sen 25→37, spårförsening 45→57, angivet
   alternativ 55→67 (Stark). Förslag: lägg bonusen före taket, eller låt den bara
   gälla typer utan tak.
3. **Listan sorteras på poäng, färgen kommer från betyget.** En "Medel" färja på 85
   och en "Svag" oklassad fritext på 97 hamnar före en "Stark" linjestopp på 70.
   Förslag: sortera på betyg först, poäng sedan.
4. **AI-justeringar fladdrar.** Pollen var 90:e s skriver över AI:ns värden; nästa
   granskning lägger tillbaka bara poängen ur cachen, inte typ/alternativ.
   Förslag: spara AI-utfallet per regel-hash och applicera det i skrivsteget.
5. **Försening på tåg är alltid 45** oavsett om den är 30 eller 120 min.
6. **Kombinationernas motivering når aldrig föraren** (den läggs bara på listraden,
   inte i förklaringen). Förslag: lägg den i `grade` i detaljen.
7. **Knutpunktsbonusen finns bara för Skåne/Kastrup**, och försvinner under taken.
8. **Poängreglerna i databasen (`ScoringRule`) påverkar inte tåg** — inga villkor
   matchar tågreglerna, så tågets siffror är ren kod.
