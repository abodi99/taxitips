# Bedömningen, AI-granskningen och helhetsbilden — nuläge och plan

*Skriven 2026-09-30. Beskrivning och plan, ingen kod ändrad. Siffrorna är mätta i
produktionen samma dag om inget annat sägs.*

Tre frågor från ägaren:

1. Färgerna och poängen skiljer sig mellan notiser och källor. Vad händer om vi
   bedömer fel och leder en taxiförare vilse — kan vi gardera oss?
2. Vad skulle det kosta per månad att låta AI:n (Genkit) granska alla notiser och
   API-svar?
3. Kan vi visa en helhetsbild av ett område, t.ex. tågförseningar och
   flygplatsproblem samtidigt, där problemen hänger ihop?

---

## 1. Nuläget, mätt

| Vad | Värde (produktion) | Vad det betyder |
|---|---|---|
| Källhändelser senaste 7 dygn | 47 041 från 8 källor | ~6 700 per dygn |
| Tips (opportunities) som startat senaste 7 dygn | 39 607 | ~5 700 per dygn; 8 378 aktiva just nu, 95 av dem starka (≥ 50) |
| Tips per typ, 7 dygn | tåg ~11 300, buss ~10 600, okänt färdsätt ~11 200, väg ~5 500, färja 250, flyg 130 | "okänt färdsätt" är fritext vi inte kunnat placera |
| **Förarnas feedback (🚕/👍/👎), totalt** | **1** | **Vi har inget facit.** Ingen av poängsättningarna är kalibrerad mot verkligheten. |
| AI-granskningar (Genkit), 30 dygn | 942 unika bedömningar (cachen gör att samma text inte bedöms två gånger) | Bara tips med `confidence=low` granskas |
| … AI:n sänkte / höjde | 750 sänkta, 33 höjda | AI:n är försiktig, som avsett |
| … över notisgränsen 50 | 5 lyfta över, 72 sänkta under | AI:n väcker sällan någon i onödan |
| Kombinationer (samma plats och tid, flera källor) | 4 rader just nu | Kombinationslagret finns men gör nästan ingenting än |
| Notiser skickade, 7 dygn | 33 | |

### Varför färgerna skiljer sig

Färg och storlek kommer från **styrkan** (`level`, ur `demand_score` 0–100), och
samma par används överallt i appen (`lib/signal_kinds.dart`). Poängen räknas däremot
av **olika regelverk per källa**:

* tåg: strukturellt (`core/scoring.py`) — inställt, nästa avgång, sista tåget,
  ersättningstrafik. Den säkraste bedömningen vi har.
* buss, spårvagn, tunnelbana: fritext (`core/text_scoring.py`) — nyckelord och
  mönster, därav `confidence=low` och AI-granskningen.
* flyg: antal ankomster per 30 minuter (`core/flight_scoring.py`) — räknar plan,
  aldrig resenärer (invariant 15).
* färja: fartygsstorlek och ankomsttid (`maritime/`).
* väg: kapad till 15 poäng, visas bara som olycka (invariant 3).

En 70:a från tåget och en 70:a från en bussfritext betyder alltså inte samma sak.
Skalan ser gemensam ut men är det inte. **Det är kärnan i risken:** föraren läser
färgen som ett löfte om lika mycket, och den löftet har vi inte mätt.

---

## 2. Risken: vad händer om vi har fel — och hur vi garderar oss

En felbedömning kostar föraren en bomresa (tid, bränsle, en missad körning där hen
stod). Det går inte att få bort helt: källorna själva har fel (Trafikverket ändrar,
en buss sätts in som ingen rapporterat). Det som går att göra är att **aldrig lova
mer än vi vet, mäta hur ofta vi har rätt, och säga det öppet**.

AI löser inte det här ensam. En modell som läser samma text som regelverket har
inte mer facit än regelverket. Facit kommer från utfallet: blev det en körning?

### 2a. Juridiskt och i villkoren (snabbt, ingen kod)

* Avtalet med bolaget (B2B) och appens villkor: tipsen är **bedömningar av
  offentliga trafikdata, inte garantier**; föraren avgör själv; TaxiTips ansvarar
  inte för utebliven förtjänst. Låt en jurist läsa formuleringen — det här är en
  ansvarsbegränsning mellan näringsidkare, och den håller bättre än i
  konsumentförhållanden.
* Samma sak kort i appen, en gång: första gången föraren öppnar ett tips
  ("Tipsen bygger på trafikdata och kan ändras. Du avgör själv om det är värt att
  köra.").

### 2b. Språket och färgen (liten kod)

* Färgen ska betyda **styrka på signalen**, inte "kunder väntar". Orden finns redan
  ("starkt tecken", "värt att titta på"); gå igenom att ingen text, notis eller
  butiksbild lovar kunder.
* Visa **säkerheten** bredvid styrkan: ett tips byggt på fritext (`confidence=low`)
  får en markering ("osäker källa"), ett strukturellt tågtips inte. Föraren ska se
  skillnaden mellan "Trafikverket säger inställt, nästa tåg om 90 min" och "en
  busstext som låter allvarlig".
* Visa **källan och åldern** på varje kort ("Trafikverket, uppdaterat 2 min sedan").
  Finns delvis i "Varför visas detta?".

### 2c. Mäta om vi har rätt (det viktigaste)

1. **Feedback som faktiskt används.** En feedback på två veckor räcker inte.
   * Fråga efter körningen, inte före: när föraren tryckt "Kör dit" och sedan
     stannat nära platsen en stund, fråga i ett tryck "Fick du en körning?"
     (🚕 / nej). Kräver ingen positionshistorik — bara "var nära målet" i stunden,
     samma princip som "i tjänst" (`core/presence.py`).
   * Räkna feedback per källa och regel i `manage.py calibration_report` (finns),
     och visa den i adminwebben.
2. **Utfall utan föraren.** Vi kan se efteråt om källan höll: blev tåget faktiskt
   inställt (Trafikverket `Canceled` blev kvar), kom flyget, sattes en
   ersättningsbuss in som vi inte visste om? Spara "vad vi sa" mot "vad som hände"
   per tips — det ger en träffsäkerhet per källa varje dag, helt automatiskt.
3. **Kalibrera skalan per källa.** När det finns utfall: justera poängen så att en
   70:a betyder ungefär samma sak oavsett källa. Tills dess: sänk taket för
   fritextkällor (t.ex. högst 60 utan strukturellt stöd) så att bara tåg med känd
   nästa avgång kan bli "starkt".
4. **Stickprov varje vecka.** 20 slumpade tips, en människa bedömer "hade jag kört
   dit?". Tio minuter i veckan, sparas i databasen, blir testfall för AI:n.

### 2d. Skyddsräcken runt AI:n

AI:n är redan försiktig (sänker 80 %, lyfter sällan över notisgränsen). Behåll och
skärp:

* AI:n får **aldrig ensam lyfta ett tips över notisgränsen** — bara sänka, eller
  lyfta inom listan. En notis ska vila på en strukturell signal.
* Spara modellens motivering per bedömning och visa den i pipeline-vyn, så att en
  människa kan se *varför* poängen ändrades.
* En fast testmängd (från stickproven ovan) som körs när prompten eller modellen
  byts: blev det bättre eller sämre?

---

## 3. Vad kostar det att låta AI:n granska allt?

Modellen i dag: **Gemini Flash-Lite** (`googleai/gemini-flash-lite-latest` via
Genkit, `core/management/commands/review_uncertain.py`).

**Priser att verifiera** innan beslut — de ändras. Räknat med Googles listpriser
som de var vid senaste kontroll: Flash-Lite ≈ 0,10 USD per miljon inmatade tokens och
0,40 USD per miljon utmatade; Flash ≈ 0,30 / 2,50; Pro ≈ 1,25 / 10. 1 USD ≈ 10,5 kr.

Antaganden: en granskning ≈ 2 000 tokens in (tipset + rå källtext) och ≈ 150 ut.

| Vad som granskas | Anrop per månad | Flash-Lite | Flash | Pro |
|---|---|---|---|---|
| **I dag**: bara `confidence=low`, med cache | ~1 000 | < 5 kr | ~15 kr | ~60 kr |
| Alla nya tips, med cache på normaliserad text (uppskattat ~10 % unika) | ~20 000 | ~20 kr | ~60 kr | ~250 kr |
| **Alla nya tips, utan cache** | ~170 000 | ~450 kr | ~1 400 kr | ~5 800 kr |
| Varje källhändelse vid varje hämtning | ~200 000 | ~550 kr | ~1 700 kr | ~7 000 kr |
| Helhetsbild per län, bara när läget ändrats (se §4) | ~10 000 à 3 000 tokens | ~40 kr | ~120 kr | ~500 kr |

**Slutsats.** Pengarna är inte problemet — även "allt, utan cache" med Flash-Lite
är några hundralappar i månaden. Problemen är andra:

* **Fördröjning.** En granskning tar 1–3 s. Tips ska inte vänta på AI:n; granska i
  efterhand och uppdatera, som i dag.
* **Kvot och driftstopp.** Om Google svarar långsamt eller slutar svara får
  pipelinen aldrig stå still — regelsvaret gäller då, som i dag.
* **Mer AI ger inte mer rätt.** Utan facit (§2c) vet vi inte om AI:n förbättrar
  eller försämrar. Att granska alla tåg (som redan är strukturellt säkra) med AI
  tillför lite; nyttan sitter i fritexten.

**Rekommendation:** utöka AI-granskningen till **alla fritexttips** (buss,
spårvagn, tunnelbana, "okänt färdsätt") — inte bara `low` — med cache, Flash-Lite,
bara sänkning ovanför notisgränsen. ~20–100 kr i månaden. Tåg, flyg och färja
behåller sina strukturella regler. Byt inte till en dyrare modell förrän
testmängden i §2d visar att den gör skillnad.

---

## 4. Helhetsbilden: "läget i området just nu"

### Vad som finns

* **Kombinationslagret** (`core/combine.py`, var 60:e sekund): hittar samma
  störning från två källor (`combo.duplicate`), flera färdsätt vid samma knutpunkt
  (`combo.hub`) och en ankomstvåg (flyg/färja) samtidigt som kollektivtrafiken från
  samma knutpunkt är stoppad (`combo.arrival`). Påslagen ändrar listans ordning men
  inte notiserna. Bara 4 kombinationer finns i produktionen nu — avstånden är
  snäva (400 m, 2 km vid flygplats) och kopplingen mellan en flygplats och tåget
  dit saknas (Arlanda ↔ Arlanda Express/pendeltåg Märsta).

### Vad som saknas

En vy som svarar på "vad händer i Stockholm just nu, och hänger det ihop?" —
både för föraren och för er i adminwebben.

### Förslag

**Steg 1 — Knutpunkter som data (ingen AI).**
Ett register över knutpunkter med vad som hör ihop: Arlanda = flygplatsen +
Arlanda Express + pendeltåg Märsta + flygbussar; Stockholm C = fjärrtåg + pendeltåg +
T-Centralen + Cityterminalen; Malmö C, Göteborg C, Kastrup-förbindelsen,
Värtahamnen osv. Kombinationslagret kopplar då på knutpunkt i stället för bara på
meter. Det här är det som gör "tågproblem OCH flygproblem samtidigt" synligt.

**Steg 2 — Lägesbild per län/knutpunkt (ingen AI).**
Räkna ihop per område var 60:e sekund: antal aktiva tips per kategori och styrka,
de tre starkaste, sammanhängande händelser (kluster: samma knutpunkt, samma
tidsfönster, ev. samma orsak — väder från SMHI, strömavbrott, signalfel). Resultatet
en rad per område, härledd och omräknad varje gång, precis som kombinationerna.

* **I appen:** ett kort överst: "Läget i Stockholm: tåg stoppat Märsta–Arlanda,
  3 plan landar 22:30–23:00 → Arlanda starkt". Tryck → de tips det bygger på.
* **I adminwebben / pipeline-vyn:** karta per län med kluster, källhälsa och vad
  som kopplats ihop och varför.

**Steg 3 — AI-sammanfattning, bara över det vi redan vet.**
Låt Genkit skriva lägesmeningen utifrån den strukturerade lägesbilden i steg 2 —
aldrig utifrån egen kunskap. Regler: varje påstående hänvisar till ett tips-id;
inga siffror som inte finns i datan (samma princip som GTFS-beläggning och flyg:
aldrig antal resenärer); genereras bara när lägesbilden ändrats; saknas AI-svar
visas den regelbaserade texten. Kostnad: ~40 kr/månad med Flash-Lite (§3).

**Steg 4 — Förstärkning av notiser, när det är mätt.**
Först när utfallen (§2c) visar att kombinationer ger fler körningar får de påverka
notiserna. Tills dess ändrar de bara ordningen i listan, som i dag.

---

## 5. Plan i ordning

| # | Vad | Varför först | Storlek |
|---|---|---|---|
| 1 | Villkor + en engångstext i appen om att tipsen är bedömningar | Garderar direkt, ingen risk | liten, jurist läser |
| 2 | Säkerhet och källa synliga på varje kort; fritext kapad under "starkt" utan strukturellt stöd | Minskar risken att fritext leder vilse | liten–medel |
| 3 | Utfallsloggning: "vad vi sa" mot "vad som hände" per tips, per källa, dagligen | Första facit, utan förare | medel |
| 4 | Feedback efter "Kör dit" (ett tryck) + kalibreringsrapporten i adminwebben | Facit från förarna | medel |
| 5 | AI-skyddsräcken: aldrig ensam över notisgränsen, motivering sparad, testmängd | Säkrar det som redan körs | liten |
| 6 | Knutpunktsregistret + kombinationslagret kopplat på knutpunkt | Grunden för helhetsbilden | medel |
| 7 | Lägesbild per område i appen och adminwebben | Helhetsbilden | medel–stor |
| 8 | Utöka AI-granskningen till all fritext (Flash-Lite, cache) | Billigt, men först när 3–5 kan visa effekten | liten |
| 9 | AI-sammanfattning av lägesbilden | Sist: bygger på 6–7 och skyddsräckena i 5 | liten–medel |
| 10 | Kalibrera poängskalan per källa och låt kombinationer påverka notiser | När det finns några hundra utfall | medel |

Punkt 1–2 går att göra samma vecka. 3–5 är det som gör att vi kan svara på frågan
"hur ofta har vi rätt?" med en siffra i stället för en känsla — utan det är varje
ändring av poäng eller AI en gissning.

## 6. Öppna frågor till ägaren

* Vilken ansvarsformulering vill ni ha i avtalet — och vem läser den juridiskt?
* Får appen fråga "Fick du en körning?" automatiskt när föraren varit nära platsen,
  eller bara när föraren själv trycker?
* Vilka knutpunkter är viktigast att börja med (förslag: Arlanda, Stockholm C,
  Malmö C/Kastrup, Göteborg C/Landvetter)?
