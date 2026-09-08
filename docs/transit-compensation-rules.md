# Lagstadgad förseningsersättning per län

Research cachad här per CLAUDE.md:s regel: extern regel-/API-research skrivs
till `docs/` en gång, i stället för att göras om varje session. Källan för
`taxitips-backend/core/management/commands/seed_compensation_rules.py`s
tabell och för `core/compensation.py`s logik.

**Senaste omgången: 2026-09-08.** Samtliga rader nedan är hämtade den dagen
från respektive huvudmans egen villkorssida (inte tredjepartssammanfattningar,
inte minne). Föregående omgång (2026-09-07) täckte 15 län och hade fel på
tre punkter som är rättade här — se §7.

---

## 1. Rättslig grund — tre regelverk, inte ett

Vilket regelverk som gäller styrs av **fordonets hela linjesträckning**, inte
av hur långt resenären själv åker. Nästan alla huvudmän skriver ut det här
själva (JLT, X-trafik, Jämtland, Västerbotten, Norrbotten, Halland,
Tåg i Bergslagen).

| Regelverk | Gäller | Tröskel för egen transport | Taxi ersätts? |
|---|---|---|---|
| **Lag (2015:953)** om kollektivtrafikresenärers rättigheter | Linjesträckning **under 15 mil** (buss och tåg) | 20 min till slutdestinationen | **Ja** — taxi nämns uttryckligen |
| **EU 2021/782** (tågpassagerarförordningen) | Tåg med linjesträckning **150 km eller längre** | 100 min utan erbjuden ombokning | **Nej** — bara "tåg eller buss" |
| **EU 181/2011** (busspassagerarförordningen) | Buss med linjesträckning **15 mil eller längre** | 120 min | **Nej** — ombokning/återbetalning i stället |

Den skillnaden är avgörande för produkten: **på långa tåg- och busslinjer finns
ingen lagstadgad rätt att ta taxi och få den betald.** Se §6.

### Prisbasbelopp (grunden för nästan alla tak)

De flesta huvudmän anger taket som *1/40 av prisbasbeloppet enligt 2 kap. 7 §
socialförsäkringsbalken för det år resan skulle ha avslutats*.

| År | Prisbasbelopp | 1/40 | 1/20 (bara Skånetrafiken) |
|---|---|---|---|
| 2024 | 57 300 kr | 1 432,50 kr | — |
| 2025 | 58 800 kr | 1 470 kr | — |
| **2026** | **59 200 kr** | **1 480 kr** | **2 960 kr** |

Prisbasbeloppet 2026 är fastställt av regeringen till 59 200 kr
([regeringen.se, pressmeddelande 2025-09](https://www.regeringen.se/pressmeddelanden/2025/09/prisbasbelopp-for-2026-faststallt/)).
Beloppen växlar 1 januari — **hela tabellen nedan måste ses över varje årsskifte.**

## 2. Gemensamt för i princip samtliga huvudmän

- **20 minuters försening till slutdestinationen** (eller skälig anledning att
  tro att den blir så lång) är tröskeln för både det trappade
  biljettprisavdraget (50 % vid 20 min, 75 % vid 40 min, 100 % vid 60 min)
  och rätten att själv ta taxi och få den ersatt.
- **Störningar annonserade minst tre dygn i förväg undantas genomgående.**
  Planerat banarbete/ersättningstrafik ger ingen rätt till ersättning hos
  någon av de undersökta huvudmännen. (Din Tur och UL skriver "tre vardagar"
  respektive "tre dagar" i stället för "tre dygn.")
- **Anmälningsfrist två månader** hos alla utom SL (tre månader) och
  Sörmlandstrafiken (60 dagar, uttryckligen i dagar). Fristen är i regel
  formulerad som "en reklamation inom två månader ska alltid anses ha
  lämnats i rätt tid", dvs. senare krav *kan* prövas vid särskilda skäl.
- **Följdkostnader ersätts aldrig** — förlorad arbetsinkomst, missad läkartid,
  missat flyg, teaterbiljetter. Gäller samtliga.
- **Ersättning för annan transport kan inte kombineras med prisavdrag** för
  biljetten. Samtliga.

## 3. Huvudtabell — samtliga 21 län

Tröskel = minuter innan resenären får ordna egen transport. Tak = maxbelopp
för taxi 2026. Alla länkar hämtade **2026-09-08**.

| Län | Huvudman | Regionnyckel | Tröskel | Taxitak 2026 | Buss/tåg-skillnad | Undantagna färdsätt | Frist | Källa |
|---|---|---|---|---|---|---|---|---|
| Skåne | Skånetrafiken | `skane` | 20 min | **2 960 kr** (1/20) | Nej — samma villkor buss/Pågatåg/Öresundståg | Inga (Närtrafik/SkåneFlex omfattas, kräver blankett) | 2 mån | [skanetrafiken.se](https://www.skanetrafiken.se/sa-reser-du-med-oss/villkor/villkor-for-ersattning-vid-forsening/) |
| Stockholm | SL | `sl` | 20 min | 1 480 kr | Nej — buss/tunnelbana/pendeltåg lika | Inga angivna | **3 mån** | [sl.se](https://sl.se/kundservice/forseningsersattning) |
| Västra Götaland | Västtrafik | `vt` | 20 min | **1 500 kr**/person (fast) | Nej — buss, spårvagn, tåg, båt lika | Färdtjänst, riksfärdtjänst, skolskjuts, förbeställda sjukresor, abonnerad trafik, museispårvagn, sightseeingbuss | 2 mån | [vasttrafik.se](https://www.vasttrafik.se/kundservice/forseningsersattning/) |
| Uppsala | UL | `ul` | 20 min | 1 480 kr | Nej | Inga (dricks ersätts ej) | 2 mån | [ul.se](https://www.ul.se/kundservice/forseningsersattning/) |
| Östergötland | Östgötatrafiken | `otraf` | 20 min | 1 480 kr (per person vid delad taxi) | Nej | Skolbiljett (endast prisavdrag) | 2 mån (kvitton upp till 4 mån) | [ostgotatrafiken.se](https://www.ostgotatrafiken.se/kontakt-och-hjalp/forseningsersattning) |
| Kalmar | Kalmar länstrafik | `klt` | 20 min | 1 480 kr (summeras vid samåkning) | Nej | Inga | 2 mån | [kalmarlanstrafik.se](https://kalmarlanstrafik.se/Kundservice/ansok-om-forseningsersattning/) |
| Kronoberg | Länstrafiken Kronoberg | `krono` | 20 min | 1 480 kr | Nej | Inga | 2 mån | [lanstrafikenkron.se](https://lanstrafikenkron.se/forseningsersattning) |
| Jönköping | Jönköpings Länstrafik | `jlt` | 20 min | 1 480 kr (per person) | Nej (men <15 mil = lag, ≥15 mil = EU 2021/782) | Inga | 2 mån | [jlt.se](https://www.jlt.se/kundservice/forseningsersattning/) |
| Blekinge | Blekingetrafiken | `blekinge` | 20 min | **1 500 kr**/resenär (fast) | Nej | Färdtjänst/Närtrafik har egen 10-minutersregel i stället | 2 mån | [blekingetrafiken.se](https://www.blekingetrafiken.se/kundservice/forseningsersattning/) |
| Halland | Hallandstrafiken | *(ingen — ej pollad)* | 20 min | **1 500 kr**/resenär | Nej | Inga | 2 mån | [hallandstrafiken.se](https://hallandstrafiken.se/reklamation-och-forseningsersattning) |
| Värmland | Värmlandstrafik | `varm` | 20 min | 1 480 kr | Nej | **Båtbuss** (anropsstyrd trafik omfattas däremot) | 2 mån | [varmlandstrafik.se](https://www.varmlandstrafik.se/varmlandstrafik/kundservice/forseningsersattning) |
| Örebro | Länstrafiken Örebro | `orebro` | 20 min | 1 480 kr | Beloppet lika, men biljettvärderingen skiljer (30-dagars delas på 36 för buss, 22 för tåg) | Inga | 2 mån | [lanstrafiken.se](https://www.lanstrafiken.se/kundservice/forsenad-och-kvarglomd/vad-galler-for-forseningsersattning/) |
| Västmanland | VL | `vastmanland` | 20 min | 1 480 kr (1/40, ej utskrivet på sidan) | Nej | Skolkort/avgiftsfri linje: endast annan transport, inget prisavdrag | 2 mån | [vl.se](https://vl.se/biljetter/villkor-och-ersattning/forseningsersattning/) |
| Dalarna | Dalatrafik | `dt` | 20 min | **1 470 kr** för taxi / 1 480 kr för egen bil (se §5) | Nej | Skolkort/vårdkallelse: endast annan transport | 2 mån | [dalatrafik.se](https://www.dalatrafik.se/kundservice/vanliga-arenden/forsenad-eller-utebliven-tur/) |
| Gävleborg | X-trafik | `xt` | 20 min | 1 480 kr/resa | **JA — taxi ersätts endast för buss.** Tåg: "Ersättning ges inte för taxi eller resa med egen bil" | Tåg | 2 mån | [xtrafik.se](https://xtrafik.se/forseningsersattning) |
| Västernorrland | Din Tur | `dintur` | 20 min (linje 40: **120 min**) | 1 480 kr | Endast buss — Din Tur kör inga tåg (Norrtåg har egna villkor) | Ungdomsbiljett, skolbiljett | **Obekräftad** | [dintur.se](https://www.dintur.se/det-har-galler-for-ersattning-vid-forsening/) |
| Jämtland | Länstrafiken i Jämtlands län | *(ingen — ej pollad)* | 20 min (≥15 mil: 120 min) | 1 480 kr/kvitto | Endast buss | Skolkort (endast annan transport) | 2 mån | [ltr.se](https://ltr.se/kundservice/57675.forseningsersattning.html) |
| Västerbotten | Länstrafiken i Västerbotten | *(ingen — ej pollad)* | 20 min (≥15 mil: 120 min) | 1 480 kr/kvitto | Endast buss | Kostnadsfria biljetter: endast annan transport | 2 mån | [tabussen.nu](https://www.tabussen.nu/lanstrafiken/kundservice/forseningsersattning-och-reklamation/) |
| Norrbotten | Länstrafiken Norrbotten | *(ingen — ej pollad)* | 20 min (≥15 mil: 120 min) | 1 480 kr/kvitto | Endast buss | — | 2 mån | [lanstrafikennorrbotten.se](https://lanstrafikennorrbotten.se/forseningsersattning) |
| Södermanland | Sörmlandstrafiken | *(ingen — ej pollad)* | 20 min | 1 480 kr | **JA — vid tågresa gäller respektive tågoperatörs villkor**, men reklamationen görs till Sörmlandstrafiken | Dricks | **60 dagar** | [sormlandstrafiken.se](https://sormlandstrafiken.se/kundservice/forseningsersattning/fragor-och-svar-om-forseningsersattning/) |
| Gotland | Region Gotland / Gotlands kollektivtrafik | `gotland` | 20 min | 1 480 kr (formel; sidan visar ännu 2024 års 1 432,50 kr) | Endast buss — det finns ingen tågtrafik | Närtrafik, skolskjuts, färdtjänst, förbeställda sjukresor | 2 mån | [gotland.se](https://gotland.se/trafik-gator-och-parker/kollektivtrafik/vanliga-fragor-om-kollektivtrafiken/forseningsersattning) |

Fem län (Halland, Jämtland, Västerbotten, Norrbotten, Södermanland) saknar
regionnyckel eftersom pipelinen inte hämtar dem — Trafiklab 404:ar på deras
operatörskoder, se `docs/data-sources.md` och `core/coverage.py`. Reglerna är
ändå researchade så att de finns färdiga den dag en källa tillkommer.

## 4. Buss/tåg-skillnader — det som uttryckligen efterfrågades

Bara fyra huvudmän har en verklig skillnad mellan buss och tåg:

1. **X-trafik (`xt`)** — den enda som helt nekar taxi vid tågförsening.
   Motiveringen på deras sida: båda deras tåglinjer (Gävle–Ljusdal och
   Gävle–Sundsvall) är längre än 15 mil och lyder därför under EU 2021/782,
   som inte omfattar taxi. Kodas som `excluded_modes=["train"]`.
2. **Sörmlandstrafiken** — "Om du åker med Sörmlandstrafikens resekort på tåg,
   likställs Sörmlandstrafikens förseningsersättning med respektive
   tågoperatörs förseningsersättning." Taket 1 480 kr gäller alltså inte
   automatiskt på tåg. Inte seedad (ingen datakälla).
3. **Länstrafiken Örebro** — samma taxitak, men biljettens *värde* räknas
   olika för buss och tåg, vilket påverkar prisavdraget (inte taxitaket).
4. **Dalatrafik** — separata villkorspunkter för buss (22.1) och tåg (22.2),
   men samma 20-minuterströskel och samma 1/40-tak.

Din Tur, Jämtland, Västerbotten, Norrbotten och Gotland har inga tågvillkor
alls — deras villkor gäller bara egen busstrafik. Övriga (Skånetrafiken, SL,
Västtrafik, UL, Östgötatrafiken, KLT, Kronoberg, JLT, Blekinge,
Hallandstrafiken, Värmlandstrafik, VL) tillämpar samma tröskel och samma tak
oavsett färdsätt, så länge linjen är kortare än 15 mil.

## 5. Avvikelser och fallgropar per operatör

- **Skånetrafiken** — ensam om **1/20** av prisbasbeloppet, dubbelt mot alla
  andra. Ordagrant: *"Kostnaden för taxi ersätts med ett maximalt belopp som
  motsvarar 1/20 av gällande prisbasbelopp. Nämnda maxbelopp gäller per
  betalande resenär."* Taxibolagsägare får inte ersättning för resa utförd av
  det egna bolaget.
- **SL** — tre månaders reklamationsfrist, inte två: *"Du måste reklamera
  resan inom 3 månader efter förseningen för att kunna få ersättning."*
  Taket gäller per resa: *"Ersättningen blir inte högre om du samåker med
  någon annan."*
- **Västtrafik och Blekingetrafiken** — fasta 1 500 kr, inte prisbasbeloppsformel.
  Hallandstrafiken skriver 1 500 kr *och* kallar det 1/40 av prisbasbeloppet,
  vilket inte stämmer räknemässigt (1/40 av 2025 års belopp är 1 470 kr) —
  1 500 kr är den siffra de faktiskt betalar ut, så det är den som gäller.
  Hallandssidan säger fortfarande "för 2025"/"från 250101" och är alltså inte
  uppdaterad för 2026.
- **Dalatrafik** — motsäger sig själv. Villkorssidan (punkt 22.1) säger
  1/40 av prisbasbeloppet, vilket vore 1 480 kr för 2026. FAQ-sidan säger
  *"Högsta ersättning för resa med taxi är 1470 kronor per resenär"* men
  *"Maxbeloppet som betalas ut för resa med egen bil är 1480 kronor"* — dvs.
  taxisiffran ser ut att vara kvarglömd från 2025. **Vi seedar 1 470 kr**,
  det lägre av de två publicerade beloppen, för att aldrig lova en förare
  mer än operatören själv skrivit ut.
- **Gotland** — sidan är märkt "Senast uppdaterad 9 juni 2026" men innehåller
  fortfarande *"för år 2024 är högsta ersättningsbeloppet 1432,50 kronor"*.
  Regeln de anger är formeln (1/40 av prisbasbeloppet för resans år), så
  1 480 kr för 2026 följer av deras egen text — men siffran står inte där.
- **VL** — anger bara formeln, inget kronbelopp ("aktuell maxersättning hittar
  du på vl.se/forseningsersattning"). 1 480 kr är härlett ur formeln.
- **Värmlandstrafik** — anropsstyrd trafik **omfattas**, båtbusstrafiken inte.
  Ovanligt: de flesta gör tvärtom.
- **Östgötatrafiken, KLT, JLT, Blekingetrafiken, Hallandstrafiken** — taket
  gäller **per resenär** och kan läggas ihop vid samåkning, mot delat
  taxameterkvitto. SL, VL och Tåg i Bergslagen gör uttryckligen tvärtom
  (taket är per resa, samåkning höjer inte).
- **Kronoberg** — *"Handskrivna taxikvitton eller kontokortskvitton godkänns
  ej"*, taxameterkvitto i original krävs. KLT, Hallandstrafiken, Norrbotten
  och Västerbotten kräver också original.
- **Din Tur** — linje 40 (Örnsköldsvik–Östersund via Sollefteå) är över 15 mil
  och har därför 120-minutersgräns i stället för 20. Ingen uttrycklig
  ansökningsfrist finns på sidan, bara "så snart som möjligt".

## 6. Fjärrtåg och långa busslinjer — håll tydligt isär

**Detta är inte samma sak som länsreglerna ovan och får aldrig blandas ihop i
en motivering.**

### Tåg med linjesträckning ≥ 150 km (SJ, MTR, Snälltåget, Flixtrain, Norrtåg, Öresundståg, Mälartåg m.fl.)

Gäller **EU 2021/782** (som från 2023-06-07 ersatte EU 1371/2007 — den äldre
förordningen som stod i förra versionen av det här dokumentet är alltså
inaktuell).

- Prisavdrag: 25 % vid 60–119 min, 50 % vid 120 min eller mer.
- **100-minutersregeln:** om operatören inte inom 100 minuter från planerad
  avgångstid har erbjudit ombokningsalternativ får resenären själv ordna
  ersättningsresa och få skäliga kostnader ersatta.
- **Men bara med tåg eller buss.** Tåg i Bergslagen formulerar det ordagrant:
  *"har du rätt att själv ordna en ersättningsresa med tåg eller buss ...
  och du har då rätt till ersättning för resa på jämförbara villkor"*
  ([tagibergslagen.se](https://tagibergslagen.se/ersattning-vid-forsening/),
  hämtad 2026-09-08). **Taxi ingår inte.**

Slutsatsen för produkten: en försening på ett fjärrtåg ger normalt **ingen**
lagstadgad rätt till betald taxi. Enskilda operatörer kan vara mer generösa i
sina egna villkor, men det är inte verifierat här — SJ:s egen villkorssida är
helt klientrenderad och gick inte att läsa maskinellt 2026-09-08.

### Buss med linjesträckning ≥ 15 mil

Gäller **EU 181/2011**. Vid minst 120 minuters försening, inställd tur eller
överbokning får resenären välja mellan fortsatt resa, ombokning eller full
återbetalning. **Ingen rätt till ersatt taxi.** Bekräftat på Din Turs
(linje 40), Jämtlands, Västerbottens och Norrbottens sidor.

### Följd för `core/compensation.py`

Modulen är redan begränsad till textkällorna (SL/Västtrafik/Trafiklab) och rör
inte Trafikverkets `TrainAnnouncement`. Det är fortfarande rätt beslut, men av
en skarpare anledning än vad som stod tidigare: Trafikverkets tågdata skiljer
inte på korta regionaltåg (lag 2015:953, taxi ersätts) och långa fjärrtåg
(EU 2021/782, taxi ersätts **inte**). Utan tågets hela linjesträckning går det
inte att avgöra vilket regelverk som gäller, och att gissa fel åt fel håll ger
en förare en motivering som är direkt osann inför resenären.

## 7. Rättelser mot 2026-09-07 års version

1. **EU 1371/2007 är ersatt av EU 2021/782** sedan 2023-06-07. Förra versionen
   pekade genomgående på den upphävda förordningen.
2. **"Taxi ersätts inte alls under EU-reglerna"** — förra versionen antydde att
   EU-reglerna bara hade "andra trösklar/belopp". Den viktiga skillnaden är
   färdsättet: EU 2021/782 ersätter tåg eller buss, inte taxi.
3. **Blekingetrafikens frist är bekräftad** (två månader, i
   [resevillkoren för södra Sverige](https://www.blekingetrafiken.se/kundservice/regler-och-villkor/resevillkor-for-kollektivtrafiken-i-sodra-sverige/)),
   inte obekräftad som tidigare flaggats.
4. **Dalatrafiks frist är bekräftad** (två månader, i
   [resevillkoren punkt 22.1](https://www.dalatrafik.se/kundservice/info/vara-resevillkor/)),
   inte obekräftad.
5. **Östgötatrafikens URL hade flyttat** och Örebros likaså — båda uppdaterade.
6. **SL:s källa** var `sl.se/artikel/avsnitt-2`; den kanoniska sidan är
   `sl.se/kundservice/forseningsersattning`.
7. Sex nya län tillkomna: Halland, Södermanland, Jämtland, Västerbotten,
   Norrbotten, Västernorrland (Din Tur).

## 8. Kvarvarande obekräftat

| Vad | Status | Vad som saknas |
|---|---|---|
| **Din Turs ansökningsfrist** | Obekräftad | Sidan säger bara "så snart som möjligt". Seedas som 60 dagar med flagga i `note` — inte en verifierad Din Tur-siffra. |
| **Dalatrafiks taxitak** | Motstridigt | 1 470 kr (FAQ, taxi) vs 1 480 kr (FAQ, egen bil) vs 1/40-formeln (resevillkor). Seedas som 1 470. Kontrollera efter årsskiftet. |
| **Gotlands taxitak** | Härlett | Sidan visar 2024 års belopp. 1 480 kr följer av deras egen formel men står inte utskrivet. |
| **VL:s taxitak** | Härlett | Bara formeln anges på sidan. |
| **Östgötatrafikens taxitröskel** | Delvis | 20-minutersgränsen är utskriven för prisavdraget; taxistycket säger bara "på grund av förseningen". Samma tröskel är rimlig men inte ordagrann. |
| **SJ:s egna villkor** | Ej läsbara | sj.se är helt klientrenderad; ingen serverrenderad villkorstext gick att hämta 2026-09-08. Fjärrtågsavsnittet vilar därför på EU 2021/782 via Tåg i Bergslagens formulering. |
| **Skånetrafikens beslutsunderlag** | Ej åtkomligt | `skane.se` blockerar maskinell hämtning (Akamai 403). Villkoren är i stället lästa direkt från skanetrafiken.se, vilket är den bindande kundtexten. |
