# SEO och Search Console — Taxi Tips

Målgruppen är **taxibolag** (B2B), inte privatpersoner som söker ”taxi Stockholm”.
Sajten ska ranka på produkt- och behovsord: tips om störningar, app för förare, bolagsprov.

## MCP:er i Cursor

| MCP | Vad den gör |
|---|---|
| `seo` (`mcp-seo`) | On-page-audit: meta, headings, sitemap, robots, structured data, m.m. |
| `google-search-console` (`mcp-gsc`) | Live Search Console: sökfrågor, indexering, sitemap-submit |

Servicekonto (redan skapat): `taxitips-gsc@taxitips-se.iam.gserviceaccount.com`  
Nyckel: `~/.config/mcp-gsc/service-account.json` (git-ignoreras lokalt, inte i repot)

## Engångssetup i Google Search Console

1. Öppna [Search Console](https://search.google.com/search-console) inloggad som ägare.
2. Lägg till egendom **URL-prefix** `https://taxitips.se/` (enklast) eller domän `taxitips.se`.
3. Verifiera (HTML-fil eller DNS-TXT hos Hostinger).
4. Under **Inställningar → Användare och behörigheter**: lägg till  
   `taxitips-gsc@taxitips-se.iam.gserviceaccount.com` som **Ägare** eller **Fullständig**.
5. Starta om Cursor (så MCP:n laddas om).
6. Be agenten: *”lista GSC-egendomar”* och *”skicka in sitemap https://taxitips.se/sitemap.xml”*.

Search Console API är redan aktiverat i GCP-projektet `taxitips-se`.

## Vad som ligger i koden

- `public/robots.txt` — tillåter marknadssidor, blockerar portal/admin/förare/api
- `public/sitemap.xml` — `/`, `/demo`, `/registrera`
- JSON-LD på startsidan: Organization, WebSite, SoftwareApplication, FAQPage
- Produktionsservern (`server.mjs`) ger rätt MIME för `.txt`/`.xml` och faller **inte** tillbaka till HTML för dem

## Efter deploy

```bash
curl -sI https://taxitips.se/robots.txt   # text/plain
curl -sI https://taxitips.se/sitemap.xml  # application/xml
```

Sedan i GSC: skicka in sitemap + begär indexering av startsidan.
