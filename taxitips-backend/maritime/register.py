"""
AIS-pilotens register (P1): vilka färjor som följs hela vägen in till vilken terminal.

Bara fartyg som faktiskt setts i AIS i terminalens ruta, med den destination de själva
sände. Ingen tidtabell och ingen rederiuppgift som inte gått att se i AIS: ett fartyg
läggs till här när det har setts, inte när det står på en hemsida. `source` säger var
och när.

Två terminaler i piloten, med avsikt. Resten av kusten täcks som tidigare av
run_ais_stream och hamnrutorna i maritime/ports.py.
"""

from __future__ import annotations

from dataclasses import dataclass

from maritime.ports import Port, by_key


@dataclass(frozen=True)
class PilotTerminal:
    port_key: str
    # UN/LOCODE och varianter som besättningar skriver i Destination.
    destination_codes: tuple[str, ...]
    # Inseglingsområdet som följs: ((syd, väst), (nord, öst)), latitud först som hos AISStream.
    approach_box: tuple[tuple[float, float], tuple[float, float]]
    # Farleden är längre än fågelvägen. Okalibrerat: skärgården in till Värtahamnen
    # slingrar, öppet hav till Visby gör det knappt.
    route_factor: float

    @property
    def port(self) -> Port:
        return by_key(self.port_key)


@dataclass(frozen=True)
class RouteVessel:
    mmsi: int
    name: str
    terminal: str
    source: str


TERMINALS: dict[str, PilotTerminal] = {
    # Gotlandsfärjorna. Rutan täcker överfarten från Nynäshamn och Oskarshamn.
    "visby": PilotTerminal(
        port_key="visby",
        destination_codes=("SEVBY", "SE VBY", "VISBY"),
        approach_box=((57.20, 16.40), (59.00, 18.90)),
        route_factor=1.05,
    ),
    # Tallink Silja. Rutan täcker Stockholms skärgård och Ålands hav ut till Mariehamn.
    "vartahamnen": PilotTerminal(
        port_key="vartahamnen",
        destination_codes=("SESTO", "SE STO", "STOCKHOLM"),
        approach_box=((59.20, 18.00), (60.30, 20.20)),
        route_factor=1.35,
    ),
}

REGISTER: tuple[RouteVessel, ...] = (
    RouteVessel(265871000, "DROTTEN", "visby", "AIS 2026-09-13: sedd i Visbys hamnruta, destination 'SE VBY'"),
    RouteVessel(266444000, "GOTLAND", "visby", "AIS 2026-09-13: sedd i Visbys hamnruta, destination 'SE NYN'"),
    RouteVessel(
        230184000, "SILJA SERENADE", "vartahamnen",
        "AIS 2026-09-13: sedd i Värtahamnens hamnruta, destination 'FIHEL<>FIMHQ<>SESTO'",
    ),
)

BY_MMSI: dict[int, RouteVessel] = {vessel.mmsi: vessel for vessel in REGISTER}
