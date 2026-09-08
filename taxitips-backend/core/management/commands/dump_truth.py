"""
Skriver databasens NUVARANDE sanning till läsbara filer i repot.

Varför detta finns
------------------
`get_smart_alerts` är omdefinierad sju gånger över 25 migrationsfiler, och
filnamnen sorterar inte i tidsordning:

    20260901000003_gate_get_smart_alerts.sql
    20260901000006_expose_kind_in_get_smart_alerts.sql
    20260902000002_get_smart_alerts_from_opportunities.sql
    20260902000003_filter_ignore_tier_from_get_smart_alerts.sql
    20260903000001_include_last_24h_in_get_smart_alerts.sql
    20260905000001_fix_worth_it_score_for_missing_coords.sql
    20260905000006_drop_reachability_from_score.sql

För att veta vad funktionen gör *just nu* måste man läsa alla sju och lista
ut vilken som är sist. Det är därför arbetet med den här kodbasen krävt
databasfrågor i stället för kodläsning -- ett läsbarhetsproblem, inte ett
databasproblem.

Det här kommandot löser det: en fil per aspekt, incheckad i git, som visar
vad som faktiskt gäller. Kör efter varje migration.

    python manage.py dump_truth
"""

from django.core.management.base import BaseCommand
from django.db import connection
from pathlib import Path
import subprocess
import sys


class Command(BaseCommand):
    help = "Dumpar databasens nuvarande schema, funktioner och regler till schema/"

    def add_arguments(self, parser):
        parser.add_argument(
            "--out",
            default="schema",
            help="Katalog att skriva till (standard: schema/)",
        )

    def handle(self, *args, **options):
        out = Path(options["out"])
        out.mkdir(parents=True, exist_ok=True)

        self._dump_tables(out / "tables.md")
        self._dump_functions(out / "functions.sql")
        self._dump_models(out / "models_reflected.py")
        self._dump_scattered_constants(out / "constants.md")
        self.stdout.write(self.style.SUCCESS(f"\nSkrev sanningen till {out}/"))

    # -- utspridda konstanter ---------------------------------------------
    # Filerna som söks igenom. Node och Dart är på väg bort (Django tar över
    # databearbetningen), men tills dess är detta det enda stället där man
    # ser att samma tröskel finns på fyra ställen i tre språk.
    CONSTANT_SOURCES = [
        ("Node-worker", "taxitips-api/worker/src", (".js",)),
        ("Flutter-app", "taxitips-app/lib", (".dart",)),
        ("Pipeline-viz", "taxitips-pipeline-viz", (".js",)),
    ]

    # Mönster som fångar tal vilka påverkar en poäng eller en gräns.
    CONSTANT_PATTERNS = [
        (r"NOTIFY_SCORE_FLOOR\s*=\s*(\d+)", "pushgräns"),
        (r"_highScoreFloor\s*=\s*(\d+)", "hög-prio-gräns (app)"),
        (r"WEATHER_BONUS\s*=\s*(\d+)", "väderbonus"),
        (r"SERIOUS_DELAY_MIN\s*=\s*(\d+)", "allvarlig försening (min)"),
        (r"WINDOW_HOURS\s*=\s*(\d+)", "sökfönster tåg (h)"),
        (r"Math\.(?:min|max)\(taxi\.score,\s*(\d+)\)", "poängtak/golv"),
        (r"worth_it_score'\]\s*>\s*(\d+)", "nivågräns (app)"),
        (r"demand_score\s*\|\|\s*0\)\s*>=\s*(\d+)", "pushvärd (viz)"),
    ]

    def _dump_scattered_constants(self, path: Path) -> None:
        """
        Letar upp poängkonstanter i Node, Dart och viz.

        Det här är diagnostik, inte en källa att läsa från. Poängen är att
        göra dubbleringen synlig: talet 50 finns i fcmPush.js, i
        severity_labels.dart, i api_client.dart och i viz/server.js -- fyra
        oberoende kopior i tre språk, utan något som håller ihop dem. När
        Fas 2 flyttar reglerna till ScoringRule-tabellen ska den här listan
        krympa; gör den inte det har flytten inte blivit av på riktigt.
        """
        import re

        # parents[4] är repo-roten (backend/core/management/commands/fil.py).
        base = Path(__file__).resolve().parents[4]
        rows = []
        for label, rel, suffixes in self.CONSTANT_SOURCES:
            root = (base / rel).resolve()
            if not root.exists():
                continue
            for f in sorted(root.rglob("*")):
                if f.suffix not in suffixes or "node_modules" in f.parts:
                    continue
                try:
                    text = f.read_text()
                except (UnicodeDecodeError, OSError):
                    continue
                for pattern, meaning in self.CONSTANT_PATTERNS:
                    for m in re.finditer(pattern, text):
                        line = text[: m.start()].count("\n") + 1
                        rows.append(
                            (meaning, m.group(1), label, f"{f.name}:{line}")
                        )

        by_value = {}
        for meaning, value, label, where in rows:
            by_value.setdefault(value, []).append((meaning, label, where))

        lines = [
            "# Poängkonstanter, var de faktiskt bor",
            "",
            "Genererad av `manage.py dump_truth`. Redigera inte för hand.",
            "",
            "Diagnostik, inte en källa. Visar samma tal duplicerat över språk.",
            "Listan ska krympa när reglerna flyttas till `ScoringRule`.",
            "",
        ]
        for value in sorted(by_value, key=lambda v: (-len(by_value[v]), int(v))):
            entries = by_value[value]
            flag = "  ⚠️ duplicerat" if len(entries) > 1 else ""
            lines.append(f"## {value}{flag}")
            lines.append("")
            lines.append("| betydelse | var | fil |")
            lines.append("|---|---|---|")
            for meaning, label, where in sorted(entries):
                lines.append(f"| {meaning} | {label} | `{where}` |")
            lines.append("")

        path.write_text("\n".join(lines))
        dupes = sum(1 for v in by_value.values() if len(v) > 1)
        self.stdout.write(
            f"  constants.md         {len(rows)} konstanter, {dupes} värden duplicerade"
        )

    # -- tabeller ---------------------------------------------------------
    def _dump_tables(self, path: Path) -> None:
        """
        Kolumner och radantal per tabell. Radantalet är med avsikt: det
        skiljer en tabell som används från en som bara finns.
        """
        with connection.cursor() as cur:
            cur.execute(
                """
                select table_name
                from information_schema.tables
                where table_schema = 'public' and table_type = 'BASE TABLE'
                order by table_name
                """
            )
            tables = [r[0] for r in cur.fetchall()]

            lines = [
                "# Tabeller i public",
                "",
                "Genererad av `manage.py dump_truth`. Redigera inte för hand.",
                "",
            ]
            for t in tables:
                cur.execute(
                    """
                    select column_name, data_type, is_nullable, column_default
                    from information_schema.columns
                    where table_schema = 'public' and table_name = %s
                    order by ordinal_position
                    """,
                    [t],
                )
                cols = cur.fetchall()
                # Tabellnamn kommer från information_schema, inte från
                # användarindata -- men parametrisera ändå där det går.
                cur.execute(f'select count(*) from public."{t}"')
                count = cur.fetchone()[0]

                lines.append(f"## {t}  ({count} rader)")
                lines.append("")
                lines.append("| kolumn | typ | null | default |")
                lines.append("|---|---|---|---|")
                for name, dtype, nullable, default in cols:
                    d = (default or "")[:40]
                    lines.append(f"| {name} | {dtype} | {nullable} | {d} |")
                lines.append("")

        path.write_text("\n".join(lines))
        self.stdout.write(f"  tables.md            {len(tables)} tabeller")

    # -- funktioner -------------------------------------------------------
    def _dump_functions(self, path: Path) -> None:
        """
        Den viktigaste filen. Hämtar funktionernas faktiska definition från
        pg_get_functiondef -- alltså den version som gäller, inte de sju
        historiska varianterna utspridda i migrationsmappen.
        """
        with connection.cursor() as cur:
            cur.execute(
                """
                select p.proname, pg_get_functiondef(p.oid)
                from pg_proc p
                join pg_namespace n on n.oid = p.pronamespace
                where n.nspname = 'public'
                  and p.prokind = 'f'
                  -- Utelämna det som ett tillägg äger. timescaledb
                  -- installerar 75 funktioner i public, och filen vars hela
                  -- syfte är "vilken version av get_smart_alerts gäller?"
                  -- blir oläsbar om time_bucket-varianterna trycker undan
                  -- projektets åtta.
                  and not exists (
                      select 1 from pg_depend d
                      where d.objid = p.oid
                        and d.deptype = 'e'
                  )
                order by p.proname
                """
            )
            rows = cur.fetchall()

        header = [
            "-- SQL-funktioner som de faktiskt ser ut i databasen just nu.",
            "-- Genererad av `manage.py dump_truth`. Redigera inte för hand.",
            "--",
            "-- Poängen med filen: migrationsmappen innehåller sju versioner av",
            "-- get_smart_alerts. Här finns en -- den som gäller.",
            "",
        ]
        body = []
        for name, definition in rows:
            body.append(f"-- ─── {name} " + "─" * max(0, 60 - len(name)))
            body.append(definition.rstrip() + ";")
            body.append("")

        path.write_text("\n".join(header + body))
        names = ", ".join(n for n, _ in rows) or "(inga)"
        self.stdout.write(f"  functions.sql        {len(rows)} funktioner: {names}")

    # -- modeller ---------------------------------------------------------
    def _dump_models(self, path: Path) -> None:
        """
        `inspectdb` som fil. Detta är en spegling av databasen för läsning,
        inte appens egna modeller -- därför suffixet _reflected.
        """
        # cwd sätts explicit: subprocessen ärver inte manage.py:s katalog,
        # och utan den läser inspectdb fel settings (alltså fel databas).
        result = subprocess.run(
            [sys.executable, "manage.py", "inspectdb"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[3],
        )
        if result.returncode != 0:
            self.stderr.write(f"  inspectdb misslyckades: {result.stderr[:200]}")
            return
        note = (
            "# Spegling av databasen som den ser ut nu, via `manage.py inspectdb`.\n"
            "# Genererad av `manage.py dump_truth`. Redigera inte för hand.\n"
            "# Appens egna modeller finns i core/models.py.\n\n"
        )
        path.write_text(note + result.stdout)
        # Räkna modeller, inte "class " -- varje modell har även en
        # inre class Meta, vilket dubblade siffran.
        classes = sum(
            1 for line in result.stdout.splitlines()
            if line.startswith("class ")
        )
        self.stdout.write(f"  models_reflected.py  {classes} modeller")
