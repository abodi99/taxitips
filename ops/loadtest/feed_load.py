"""
Lasttest för förarflödet /api/alerts med FAST TAKT: N anrop per sekund i T sekunder,
oavsett hur snabbt servern svarar. `ab` mäter maxgenomströmning vid fast samtidighet;
en fast takt visar i stället vad som händer när rusningen kommer och svaren blir
långsamma -- kön växer, och det är det p95/p99 fångar.

    cd taxitips-backend
    .venv/bin/gunicorn config.wsgi:application --bind 127.0.0.1:8010 --workers 2 --timeout 120
    .venv/bin/python ../ops/loadtest/feed_load.py --rate 50 --seconds 30 --profile gps
    .venv/bin/python ../ops/loadtest/feed_load.py --rate 100 --seconds 30 --profile counties --revalidate

Profiler: `gps` (position i header, tre städer), `counties` (körområde utan position).
`--revalidate` skickar tillbaka ETag i If-None-Match, som appen gör.

Förartoken hämtas ur den lokala databasen (en enhet i ett aktivt bolag) och skrivs
aldrig ut. Kör aldrig mot produktion utan beslut.
"""

from __future__ import annotations

import argparse
import http.client
import os
import random
import statistics
import subprocess
import sys
import threading
import time
import urllib.parse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "taxitips-backend"

PROFILES = {
    "gps": lambda: ({"X-TT-Position": random.choice(["55.60,13.00", "59.33,18.07", "57.71,11.97"])}, ""),
    "counties": lambda: ({}, "counties=" + random.choice(["01", "12", "14", "01,03"])),
}


def device_token() -> str:
    sys.path.insert(0, str(BACKEND))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from billing.models import Company, Device

    active = Company.objects.filter(status__in=("trial", "active")).values_list("id", flat=True)
    device = Device.objects.filter(company_id__in=list(active)).exclude(token="").first()
    if device is None:
        raise SystemExit("ingen enhet i ett aktivt bolag i den lokala databasen")
    return device.token


def sample_cpu(stop: threading.Event, samples: list[float]) -> None:
    """Summerad CPU% för gunicorns processer, en gång per sekund."""
    while not stop.is_set():
        pids = subprocess.run(["pgrep", "-f", "gunicorn config.wsgi"], capture_output=True, text=True).stdout.split()
        if pids:
            out = subprocess.run(["ps", "-o", "%cpu=", "-p", ",".join(pids)], capture_output=True, text=True).stdout
            samples.append(sum(float(x) for x in out.split() if x.strip()))
        stop.wait(1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8010")
    parser.add_argument("--rate", type=int, default=50)
    parser.add_argument("--seconds", type=int, default=30)
    parser.add_argument("--profile", choices=sorted(PROFILES), default="gps")
    parser.add_argument("--revalidate", action="store_true")
    args = parser.parse_args()

    token = device_token()
    target = urllib.parse.urlparse(args.url)
    results: list[tuple[float, int, int]] = []
    etags: dict[tuple, str] = {}
    lock = threading.Lock()

    def one() -> None:
        extra, query = PROFILES[args.profile]()
        key = (tuple(sorted(extra.items())), query)
        headers = {"X-Device-Token": token, **extra}
        if args.revalidate and key in etags:
            headers["If-None-Match"] = etags[key]
        connection = http.client.HTTPConnection(target.hostname, target.port, timeout=30)
        started = time.perf_counter()
        try:
            connection.request("GET", "/api/alerts" + (f"?{query}" if query else ""), headers=headers)
            response = connection.getresponse()
            body = response.read()
            status, etag = response.status, response.getheader("ETag")
        except Exception:
            status, body, etag = 0, b"", None
        finally:
            connection.close()
        elapsed_ms = (time.perf_counter() - started) * 1000
        with lock:
            results.append((elapsed_ms, status, len(body)))
            if etag:
                etags[key] = etag

    cpu: list[float] = []
    stop = threading.Event()
    sampler = threading.Thread(target=sample_cpu, args=(stop, cpu), daemon=True)
    sampler.start()

    total = args.rate * args.seconds
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=min(500, args.rate * 5)) as pool:
        for i in range(total):
            delay = started + i / args.rate - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            pool.submit(one)
    wall = time.perf_counter() - started
    stop.set()

    latencies = sorted(ms for ms, _, _ in results)
    statuses = Counter(status for _, status, _ in results)

    def pct(p: float) -> float:
        return latencies[min(len(latencies) - 1, int(round(p / 100 * (len(latencies) - 1))))]

    ok = statuses.get(200, 0) + statuses.get(304, 0)
    print(
        f"profil={args.profile} revalidera={args.revalidate} takt={args.rate}/s i {args.seconds} s "
        f"-> {len(results)} svar på {wall:.1f} s"
    )
    print(
        f"  p50 {pct(50):.0f} ms  p95 {pct(95):.0f} ms  p99 {pct(99):.0f} ms  max {latencies[-1]:.0f} ms  "
        f"medel {statistics.mean(latencies):.0f} ms"
    )
    print(
        f"  status {dict(sorted(statuses.items()))}  fel {100 * (len(results) - ok) / len(results):.1f} %  "
        f"304-andel {100 * statuses.get(304, 0) / len(results):.0f} %  "
        f"medelstorlek {statistics.mean(b for _, _, b in results) / 1024:.0f} kB"
    )
    if cpu:
        print(f"  gunicorn CPU medel {statistics.mean(cpu):.0f} %  max {max(cpu):.0f} %  (summa över processer)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
