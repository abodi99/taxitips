# Konton, billicenser och abonnemang

Kundlivscykeln: hur ett taxiföretag registrerar sig, får ett prov, köper
billicenser, ansluter telefoner, byter skift, ändrar län, betalar och säger
upp — utan att någon på TaxiTips behöver ingripa.

Koden bor i `taxitips-backend/fleet/`. Den här filen beskriver reglerna och
utrullningen; koden beskriver sig själv i sina docstrings.

---

## 1. Grundmodellen

```
companies (Supabase)            avtalspart, land + normaliserat orgnr
  └─ fleet_company_profile      kontakt, verifiering, fakturauppgifter, övergångsfönster
  └─ fleet_subscription         ETT samlat abonnemang, versionerad prisplan
       └─ fleet_order           beställningar med uträkningen kunden godkände
       └─ fleet_pending_change  allt som ska gälla från nästa förnyelse
  └─ fleet_trial                provhistorik, nyckelad på organisationsnumret
  └─ fleet_vehicle              registrerade bilar
  └─ fleet_license              BILLICENSEN — det som faktiskt köps
       ├─ fleet_license_county      baslän + extra län, med giltighetstid
       ├─ fleet_vehicle_assignment  vilken bil licensen betjänar, över tid
       ├─ fleet_device_approval     godkända telefoner för bilen
       └─ fleet_vehicle_session     den EN aktiva telefonen just nu
devices (Supabase)              telefonraden, push-token, notisinställningar
  └─ fleet_device_credential    hashad hemlighet (SHA-256)
```

`companies`, `company_members` och `devices` ägs fortfarande av Supabases
migrationer och nås via `managed=False`-modeller i `billing/models.py`. Den nya
modellen hänger på dem i stället för att ersätta dem.

**Ingen fleet-tabell är åtkomlig via PostgREST.** All läsning går genom Djangos
vyer, som kontrollerar behörigheten i Python. Se
`fleet/migrations/0003_revoke_postgrest_access.py`.

---

## 2. Roller

| Roll | Får |
|---|---|
| `company_owner` | allt: bilar, telefoner, län, köp, uppsägning, medlemmar, ägarbyte, kontostängning |
| `fleet_admin` | bilar, telefoner, länsval — **inte** köpa eller säga upp |
| `finance` | abonnemang, fakturor, köp, uppsägning — **inte** parkoppla telefoner |
| `driver` | inget administrativt; enhetens väg |

Plattformens egna roller ligger i `fleet_staff_role`, åtskilda från kundens:
`sales` kan skapa kortfria inbjudningar, `support` kan läsa, `platform_admin`
kan avgöra granskningsärenden. **Ingen av dem kan återställa provhistorik.**

Enmansföretag behöver inget särfall: ägaren har samtliga kundbehörigheter.

**Tvåfaktor** krävs för köp, uppsägning, medlemshantering och ägarbyte när
`FLEET_TWO_FACTOR_REQUIRED_FROM` har passerats. Tomt värde = kravet är inte
påslaget. Kontrollen läser `aal`-anspråket ur den verifierade Supabase-JWT:n.

---

## 3. Förarens telefon

### Så ansluts den

1. Administratören väljer bil i portalen → `POST /api/fleet/pairing-codes`.
   Åtta tecken, giltiga **högst fem minuter**, högst fem försök, lagrade
   hashade.
2. Föraren skriver in koden i appen → `POST /api/fleet/pair`. Svaret bär en
   256-bitars hemlighet **en gång**; appen lägger den i Keychain respektive
   Android Keystore (`lib/device_credential.dart`).
3. Servern har bara SHA-256-hashen (`fleet_device_credential`).

### Bolagskoden

Får hitta företaget och lägga en **ansökan** (`POST /api/fleet/join-request`).
Inget mer. Den gamla `join_device()`-RPC:n delade ut en permanent enhetstoken
direkt ur koden; den är stängd i
`20260920000001_join_code_is_not_a_credential.sql` — `anon` nekas helt,
`authenticated` får ett förklarande felmeddelande för äldre appversioner.

### Spärr

`POST /api/fleet/approvals/<id>/block`. Kräver inte tillgång till telefonen,
tar effekt vid nästa begäran, avslutar den aktiva sessionen och nollar
push-token. Redan levererat innehåll går inte att återkalla.

### Ominstallation

Ny hemlighet och nytt godkännande. **Provtiden rörs inte** — den bor på
`fleet_trial`, nyckelad på organisationsnumret.

---

## 4. Skiftbyte

Exakt **en aktiv telefon per billicens** och **en aktiv bil per telefon**.
Båda är partiella unika index i `fleet_vehicle_session` — inte kontroller i
Python, eftersom två förare som trycker samtidigt läser båda innan någon
skriver.

* `POST /api/fleet/session` utan `force` svarar `takeover_required` med vem
  som har bilen. Appen frågar; `force: true` är svaret på frågan.
* Övertagandet är atomiskt: telefonen låses först, sedan licenserna i stigande
  id-ordning (så att två samtidiga byten blir en kö, inte en baklåsning).
* **En avslutad session återupplivas aldrig.** `heartbeat()` uppdaterar bara en
  öppen rad, så bakgrundsuppdatering, tokenförnyelse och återanslutning kan
  inte ta tillbaka bilen.
* **Ingen tidsgräns stänger en session.** Nätbortfall och app i bakgrunden
  släpper inte licensen.

---

## 5. Åtkomstkontrollen

`fleet/access.py` kontrollerar på **varje** skyddad begäran: företagstillhörighet,
enhetsbehörighet, licens, aktuell aktiv session, giltig tidsperiod (serverns
UTC) och länsrättighet.

Den anropas från `core.entitlement.entitlement_for_request`, som är den enda
ingången för allt skyddat: lista, karta, detaljer, direktlänkar, historik,
favoriter, notisinställningar, färjor och evenemang. En ny vy som använder den
funktionen får grinden automatiskt.

Push kontrolleras dessutom **strax före sändning**
(`fleet/push_gate.py`): mellan köandet och sändningen kan telefonen ha
spärrats eller bilen tagits över, och kön bär en titel som beskriver ett
skyddat tips. En sådan leverans får status `suppressed`.

Tre vägar in:

| Väg | Räckvidd |
|---|---|
| `driver` | förartoken + godkännande + aktiv session → licensens län |
| `member` | inloggad ägare/admin → de län företaget faktiskt betalar för, aldrig mer |
| `legacy` | daterat övergångsfönster för konton från före licensmodellen |

**Tågtips utan länskoder släpps igenom länsfiltret.** Trafikverkets tågdata
saknar länsfält (invariant 14 i AGENTS.md); avståndsgrinden i `within_reach()`
håller dem i stället.

---

## 6. Priser

Prisversion `2026-09-v1`, alla belopp **exklusive moms**, i ören:

| Post | Pris |
|---|---|
| 1–9 köpta billicenser | 799 kr per bil och månad |
| Minst 10 köpta billicenser | 749 kr per bil och månad, för **samtliga** licenser |
| Extra län | 199 kr per bil, extra län och månad |
| Introduktion | 699 kr per bil och månad, företagets första tre sammanhängande betalmånader |

Moms: 25 % (`vat_rate_bp = 2500`), ett fält på prisversionen. Det fanns ingen
momshantering att återanvända i kodbasen — bara strängen "exkl. moms" i en
Flutter-vy — så satsen är konfigurerad, inte hårdkodad.

### Tolkningen av "kombineras inte"

Uppdraget säger att introduktion och volymrabatt inte kombineras, men inte
vilken som vinner. Motorn staplar dem aldrig och tar **den lägsta** av
introduktionspriset och volymnivåns pris. Med dagens tal betyder det 699 kr.
Reglerna finns på ett ställe (`fleet/pricing._unit_price_ore`); säger avtalet
något annat är det den funktionen som ändras.

### Proportionering

Ett tillägg mitt i perioden kostar återstående del, räknat på sekunder.
Beloppet "nu" är **skillnaden** mellan nytt och gammalt månadsbelopp — enda
sättet att få 9 → 10 rätt: den tionde bilen gör alla nio billigare, och kunden
betalar mellanskillnaden (10 × 749 − 9 × 799 = 299 kr/mån), inte 749 kr.

Beloppet nu är aldrig negativt. Minskningar ger ingen kreditering; de gäller
vid nästa förnyelse.

### Introduktionskampanjen är AV

`intro_enabled = False`, `launch_date = None`. Den får inte startas från ett
gissat lanseringsdatum. Slå på den med:

```bash
manage.py seed_pricing --enable-intro --launch-date 2026-10-01
```

Kommandot vägrar `--enable-intro` utan `--launch-date`.

### Villkorsversion

`terms_version` är **tom**. Fyll den innan riktiga beställningar läggs — en
order utan villkorsversion går inte att knyta till ett avtal i efterhand.
`seed_pricing` varnar om den saknas.

---

## 7. Prov

* 14 dagar, högst tre provbilar, högst **en gratisperiod per företag per 24
  månader**.
* Spärren räknar på `land + normaliserat organisationsnummer`, inte på
  company_id, e-post, telefon, Stripe-kund eller administratör — alla fem går
  att byta på en eftermiddag.
* Klockan startar vid **första telefonaktiveringen**, inte vid registreringen.
  Start och slut skrivs atomiskt en gång; alla provbilar delar slutdatum.
* Provbilar är inte beställda licenser. Tre provbilar blir aldrig tre
  debiterade licenser utan en uttrycklig beställning av vilka bilar som
  fortsätter.
* Kortfritt prov kräver en personlig engångsinbjudan från en säljare, giltig
  sju dagar, med **dokumenterad verifierad företagskontakt** (obligatoriskt
  fält). Utan aktiv betalbeställning avslutas provet utan debitering.

---

## 8. Abonnemang

| Händelse | Verkan |
|---|---|
| Uppgradering | Betalas proportionellt nu. Rättigheter **först när betalningen lyckats**. |
| Väntande betalning | Ger ingen åtkomst och förstör ingen befintlig. |
| Minskning | Nästa förnyelse. Kunden väljer vilka bilar/län och ser kommande totalpris. |
| Baslänsbyte | Nästa förnyelse. Behövs länet nu: köp som tillägg, tillägget tas bort automatiskt vid bytet. |
| Uppsägning | Stoppar nästa period. Åtkomst den betalda perioden ut. Ingen extra frist, inget supportsamtal. |
| Ångra uppsägning | Går fram till slutdatumet. Introduktions- och provhistorik behålls. |
| Misslyckad förnyelse | Högst **7 dagars** frist, räknad från **ursprunglig** förfallotid. Bara för den som betalat förut. |
| Återförsök | Förlänger **aldrig** fristen (`grace_origin` sätts en gång). |
| Första felet efter gratisprov | **Ingen** frist alls. |
| Efter slutligt fel | Löpande förnyelse stoppas. Obetald faktura hanteras separat enligt ekonomipolicyn. |
| Ta bort förare / avinstallera | Avslutar **inte** abonnemanget. |
| Avsluta kontot | Stoppar framtida förnyelse och förklarar kvarvarande data och åtkomst. |

Fakturor och beställningar är åtkomliga för behörig kund **även när
liveinformationen är spärrad** — `/api/fleet/orders/list` kräver
`view_billing`, inte en giltig period.

---

## 9. Stripe

* **Beloppen räknas hos oss.** Abonnemanget i Stripe är en post med
  `price_data` och vårt månadsbelopp; uppgraderingar debiteras som egna
  engångsposter, och prenumerationen uppdateras med
  `proration_behavior="none"` så att Stripe inte lägger på sin egen.
* **Inga subscription schedules.** En uppsägning ska inte behöva leta rätt på
  och avbryta ett schema först. Finns ett ändå (skapat i dashboarden) släpps
  det innan uppsägningen.
* **Portalen används bara för betalmetod och fakturor.** Den kan inte uttrycka
  den här prismodellen och skulle lämna Stripe och appen med olika sanningar.
* **Ordningen är inte garanterad.** `Subscription.last_stripe_event_at` kastar
  händelser som kommer efter en nyare.
* **Idempotens** i två lager: `processed_webhook_events` på händelse-id, och
  `Order.paid_at` / `status = applied` på betalningen.
* **En äldre betald faktura återöppnar inte ett avslutat abonnemang.**
* **Aktivering litar aldrig på klientens success-redirect.** Det finns ingen
  endpoint att anropa från webbläsaren för att bli aktiverad.
* **Avstämning** var sjätte timme (`fleet.tasks.reconcile_stripe`). Den
  **rapporterar**, rättar inget — en automatisk rättning hade spridit ett fel
  tyst i endera riktningen.

### Vad som måste konfigureras innan produktion

`fleet.stripe_sync.check_billing_config()` listar det:

| Variabel | Varför |
|---|---|
| `STRIPE_SECRET_KEY` | — |
| `STRIPE_WEBHOOK_SECRET` | signaturverifiering |
| `STRIPE_VAT_TAX_RATE_ID` | **utan den saknar fakturorna moms** |
| `STRIPE_PRODUCT_ID` | prenumerationsposterna får annars ingen produkt |

`STRIPE_ALLOW_LIVE=1` krävs innan koden får röra en livenyckel. Spärren finns
för att den här modulen byggdes utan tillstånd att röra riktiga abonnemang.

---

## 10. Risk och granskning

Konfigurerbara i `fleet_risk_config`. Startvärden:

| Gräns | Värde |
|---|---|
| Nya telefonanslutningar per bil / 24 h | 3 |
| Övertaganden per licens / timme | 6 (det sjunde slår i taket) |
| Separata bilbyten per licens / 30 dagar | 2 |

En risksignal **blockerar nästa ändring, aldrig åtkomsten som redan gäller**.
Förarna fortsätter se tips medan ärendet granskas, och kunden ser en begriplig
status. Återgång från en ersättningsbil i samma ärende (`case_ref`) räknas inte
som ett nytt byte.

Undantaget är konkret kontokapning, som inte är en räknad signal utan ett
beslut: då spärras enheterna, vilket är en annan väg med en egen revisionsrad.

---

## 11. Utrullning

### Ordning

```bash
# 1. Backup FÖRE migrering (CLAUDE.md:s regel — ersätter mänsklig granskning)
ops/backup/backup.sh

# 2. Djangos tabeller (bara CREATE — expand, inget destruktivt)
manage.py migrate fleet

# 3. Supabase: stäng bolagskodsvägen och lås domäntabellerna
supabase db push     # 20260920000001, 20260920000002

# 4. Läs vad som skulle hända med befintliga kunder
manage.py migrate_legacy_fleet --dry-run

# 5. Öppna övergångsfönstren
manage.py migrate_legacy_fleet --price-version <id> --days 30

# 6. Informera kunderna. De lägger upp bilar och ansluter telefoner i portalen.

# 7. När fönstren löpt ut:
FLEET_ENFORCE_LICENSES=1
```

### Vad `migrate_legacy_fleet` INTE gör

* **Skapar inga bilar och inga licenser.** Vilken telefon som sitter i vilken
  bil vet bara kunden — `devices` bär "Anna" eller "Bil 3", inte ett
  registreringsnummer. Att gissa hade gett fel bil på fel licens och fel län.
* **Rör inget pris.** En befintlig kund ska inte upptäcka den nya prislistan
  genom en högre faktura. Ange en prisversion som speglar vad kunden redan
  betalar.
* **Anropar inte Stripe.**
* **Gissar ingen betalperiod.** En okänd period betyder "vet inte", inte
  "utgången" — annars hade varje befintlig kund låsts ute i samma sekund
  kommandot kördes.

### Återställning

| Steg | Återställning |
|---|---|
| `FLEET_ENFORCE_LICENSES=1` | sätt tillbaka till `0`. Ingen data rullas tillbaka. |
| Övergångsfönster | `migrate_legacy_fleet --close` stänger, en ny körning öppnar igen. |
| `fleet`-migrationerna | bara CREATE/REVOKE. En `migrate fleet zero` tar bort tabellerna men **inte** något i `companies`/`devices`. |
| `20260920000001` | hela den gamla `join_device`-kroppen finns i `20260829000000_rpc_functions.sql`. **Gör inte det utan att först ha stängt hålet på annat sätt.** |
| `20260920000002` | `disable row level security` per tabell. Samma varning. |

Ingen av återställningarna kan orsaka dubbeldebitering: beloppen ligger på
`fleet_order` med `paid_at` och idempotensnyckel, och ingen av dem skrivs om
av en nedgradering.

---

## 12. Automatisering

`fleet.tasks.fleet_tick` varje timme (`CELERY_BEAT_SCHEDULE`): verkställer
väntande ändringar, avslutar utgångna prov, påminner tre dagar före provslut,
stoppar förnyelsen när betalningsfristen gått ut, förfaller koder och
ansökningar, skickar utkorgen.

**Klockan är inte sanningen.** Åtkomsten avgörs vid varje anrop av serverns
UTC-tid mot periodens fält. Ett tick som uteblir kan inte ge extra åtkomst,
bara försena en påminnelse.

Utskicken går via `fleet_outbox_message` med unik `dedupe_key`, så en
dubblerad webhook inte skickar två mejl. Utan `FLEET_OUTBOX_SENDER` skrivs
raderna men skickas inte — en utvecklingsmiljö kan inte nå en riktig
mottagare. Tjänstemeddelanden (`SERVICE_CATEGORIES`) kan aldrig tystas av ett
marknadsföringsval.

## 13. Gallring

Föreslagna utgångspunkter, ännu inte automatiserade:

* **Provhistorik: minst 24 månader.** Kortare tid gör spärren verkningslös.
* **Detaljerade sessionsloggar: 90 dagar.**
* **Avtal och bokföringsunderlag gallras inte** av en generell loggrensning.
  `fleet_order`, `fleet_subscription` och `fleet_audit_event` bär
  bokföringsunderlag.
* Hashade personuppgifter är inte automatiskt anonyma och räknas som
  personuppgifter.
