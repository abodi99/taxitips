# Lokal utvecklingsmiljö

Allt körs lokalt. Ingenting av det här rör produktion.

## Starta (i ordning)

```bash
colima start                                     # containerruntime
cd taxitips-api && supabase start                # Postgres
cd ../taxitips-backend && ./.venv/bin/python manage.py runserver 8000
cd ../taxitips-pipeline-viz && node server.js    # visualiseraren
cd ../taxitips-app && flutter run --dart-define=API_BASE_URL=http://127.0.0.1:8000
```

Fyll på med färsk data när du vill — en källa per kommando:

```bash
cd taxitips-backend
./.venv/bin/python manage.py poll_rail                  # Trafikverket järnväg
./.venv/bin/python manage.py poll_road                  # Trafikverket väg
./.venv/bin/python manage.py poll_sl --skip-sites       # Stockholm
./.venv/bin/python manage.py poll_vasttrafik --skip-sites  # Göteborg
./.venv/bin/python manage.py poll_trafiklab             # övriga regioner
```

Utan `--skip-sites` uppdateras hållplatsregistret också (~18 000 rader,
tar en stund). Kör det efter en `supabase db reset`, annars saknar
Stockholms- och Göteborgstips lokala koordinater.

Vädret har inget eget kommando — det hämtas inifrån de andra och cachas.

Öppna sedan:

| Vad | URL |
|---|---|
| **Pipeline-visualiseraren** | **http://localhost:4000** |
| Django admin | http://localhost:8000/admin/ (`admin` / `taxitips`) |
| Django health | http://localhost:8000/health |
| Supabase Studio | http://localhost:54323 |
| Förar-API (appen) | http://localhost:8000/api/alerts?lat=55.6&lon=13.0 |

### Vad avsnitt 2 säger om källorna

Pipeline-vyn läser `source_status`, en rad per källa som skrivs vid varje
hämtning. En källa som slutat svara är röd med sitt felmeddelande — och det
är hela poängen: i `source_events` ser en död källa exakt likadan ut som en
lugn trafikdag, båda är noll rader.

Det var så Trafiklabs slut-på-kvot-fel hittades: nyckeln svarade `429 has
exceeded its quota` på alla fjorton regioner, och de tomma regionerna såg ut
som en lugn trafikdag. Nyckeln är utbytt mot en **GTFS Sweden 3 Realtime
(Gold)**-nyckel, som ger ~560 larm per cykel över fjorton regioner.

Nyckeln bor i `taxitips-backend/.env` och `taxitips-api/worker/.env.local`
(båda ogitade). Byter du den igen: samma variabelnamn på båda ställena,
`TRAFIKLAB_API_KEY`.

### Kartorna

Fyra kartor i avsnitt 8, ett steg i pipelinen var. **⛶ Helskärm** fäller ut
en karta över hela fönstret; scroll-zoom slås på när du klickat i kartan
(annars kapas sidscrollningen när man bara passerar förbi). Punkter som
ligger på exakt samma koordinat sprids i en spiral och växer när du zoomar
in — flera störningar landar ofta på samma stationskoordinat.

### "Hämtar ni något i Halland?" — avsnitt 6b svarar

Täckningstabellen visar län för län om kollektivtrafikkällan finns, vad den
gav just nu, och om vägdata hämtas där. Tre olika saker ser annars likadana
ut i en tom tabell: att källan inte finns (Halland, Sörmland, Jämtland,
Västerbotten, Norrbotten — 404 hos Trafiklab), att den svarade tomt
(Blekinge, en lugn stund), och att nätet helt enkelt är litet (Kalmar 11
larm mot Stockholms 201).

Visualiseraren läser från Django (`VIZ_BACKEND` i `.env`). Tas den raden
bort faller den tillbaka på Supabase — alltså Node-workerns data, med den
gamla poängsättningen. Bra för att jämföra före/efter.

### Appen mot Django (Spår B)

`--dart-define=API_BASE_URL=...` styr var appen hämtar tips. Utan den går
den via Supabase-RPC:erna precis som förut — samma fält, samma kort, så det
är ett rimligt sätt att jämföra de två vägarna mot varandra.

| Var appen kör | API_BASE_URL |
|---|---|
| iOS-simulator / macOS / web | `http://127.0.0.1:8000` |
| Android-emulator | `http://10.0.2.2:8000` |
| Fysisk telefon i samma nät | `http://<din-lan-ip>:8000` (kör `runserver 0.0.0.0:8000`) |

Svarar backenden inte faller appen tillbaka på Supabase av sig själv — ett
pass ska inte tappa listan för att en tjänst startar om. Kolla vilken väg
som faktiskt användes med `source` i svaret (`django` eller `trafiklab`).

Snabbtest utan app:

```bash
TOKEN=9a9bf67c6e8885f44c831232afd314788d86067b7ddfcced
curl -s "http://127.0.0.1:8000/api/alerts?lat=55.604981&lon=13.003822" \
  -H "X-Device-Token: $TOKEN" | head -c 400
```

Tomt flöde med `"reason": "unknown_device_token"` betyder utelåst, inte
"inga störningar" — den skillnaden var tidigare osynlig.

### Node-workern

Ligger kvar men behövs inte för tågdata längre. Starta den om du vill se
buss, väg och väder — den skriver till Supabase-databasen, inte Djangos:

```bash
cd taxitips-api/worker && node src/index.js
```

## Vad som körs

`worker/.env.local` styr allt, och står nu på:

- `SUPABASE_URL=http://127.0.0.1:54321` — lokal databas
- `MARKET_SCOPE=national` — hela Sverige
- `TRAFIKLAB_OPERATORS` — 15 operatörer
- `SL_ENABLED=1`, `VT_ENABLED=1` — Stockholm och Göteborg

En cykel tar ~3 sekunder och skriver ~630 tips.

## Efter `supabase db reset`

`supabase/seed.sql` lägger automatiskt in demobolaget och två förartokens.
Utan dem returnerar `get_smart_alerts` tomt för varje token — vilket ser ut
precis som "pipelinen hittade inget" i stället för "du är inte inloggad".

Hållplatsregistren fylls däremot **inte** av seedet (de är ~18 000 rader från
externa API:er). Kör den här engångsimporten efter en reset, annars saknar
Stockholms- och Göteborgstips koordinater:

```bash
cd taxitips-api/worker && node -e '
const fs=require("fs");
for(const l of fs.readFileSync(".env.local","utf8").split("\n")){
  const m=l.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/); if(m) process.env[m[1]]=m[2];
}
(async()=>{
  const {createClient}=require("@supabase/supabase-js");
  const c=createClient(process.env.SUPABASE_URL,process.env.SUPABASE_SERVICE_ROLE_KEY,{auth:{persistSession:false}});
  const {fetchSlSites}=require("./src/sl"); const vt=require("./src/vasttrafik");
  const sl=await fetchSlSites();
  for(let i=0;i<sl.length;i+=1000) await c.from("sl_sites").upsert(sl.slice(i,i+1000),{onConflict:"stop_area_id"});
  const va=await vt.fetchVasttrafikStopAreas(process.env.VASTTRAFIK_CLIENT_ID,process.env.VASTTRAFIK_CLIENT_SECRET);
  for(let i=0;i<va.length;i+=1000) await c.from("vt_stop_areas").upsert(va.slice(i,i+1000),{onConflict:"gid"});
  console.log("sl_sites",sl.length,"vt_stop_areas",va.length);
})();'
```

## Testförare

Token `9a9bf67c6e8885f44c831232afd314788d86067b7ddfcced` (Förare – Anna,
Taxi Tips Demo AB, status `trial`). Visualiseraren använder den för avsnitt 5.

## Stoppa

```bash
pkill -f "node src/index.js"; pkill -f "node server.js"
cd taxitips-api && supabase stop
colima stop
```
