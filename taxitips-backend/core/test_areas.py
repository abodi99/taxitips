"""
Körområden: vilket län en koordinat ligger i, och vilka grannlän den räknas till.

Kartan är förenklad (Natural Earth, ungefär en kilometer), så testerna tar
kuststäder och färjelägen med avsikt -- det är där en förenklad kustlinje
annars tappar punkter.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from core import areas

CITY_CENTRES = {
    "Stockholm": (59.3326, 18.0649, "01"),
    "Uppsala": (59.8586, 17.6389, "03"),
    "Nyköping": (58.7530, 17.0086, "04"),
    "Linköping": (58.4108, 15.6214, "05"),
    "Jönköping": (57.7826, 14.1618, "06"),
    "Växjö": (56.8777, 14.8091, "07"),
    "Kalmar": (56.6634, 16.3568, "08"),
    "Visby": (57.6348, 18.2948, "09"),
    "Karlskrona": (56.1612, 15.5869, "10"),
    "Malmö": (55.6050, 13.0038, "12"),
    "Halmstad": (56.6745, 12.8578, "13"),
    "Göteborg": (57.7089, 11.9746, "14"),
    "Karlstad": (59.3793, 13.5036, "17"),
    "Örebro": (59.2753, 15.2134, "18"),
    "Västerås": (59.6099, 16.5448, "19"),
    "Falun": (60.6065, 15.6355, "20"),
    "Gävle": (60.6749, 17.1413, "21"),
    "Sundsvall": (62.3908, 17.3069, "22"),
    "Östersund": (63.1792, 14.6357, "23"),
    "Umeå": (63.8258, 20.2630, "24"),
    "Luleå": (65.5848, 22.1547, "25"),
}


class CountyTests(SimpleTestCase):
    def test_every_county_seat_lands_in_its_county(self):
        for city, (lat, lon, code) in CITY_CENTRES.items():
            with self.subTest(city):
                self.assertEqual(areas.area_for(lat, lon)[0], code)

    def test_ferry_terminals_on_the_coast_are_placed(self):
        self.assertEqual(areas.area_for(59.3526, 18.0995)[0], "01")  # Värtahamnen
        self.assertEqual(areas.area_for(55.3700, 13.1500)[0], "12")  # Trelleborg

    def test_abroad_is_not_placed(self):
        self.assertEqual(areas.area_for(59.9139, 10.7522), (None, []))  # Oslo
        self.assertEqual(areas.area_for(60.1699, 24.9384), (None, []))  # Helsingfors

    def test_a_tip_near_the_border_belongs_to_the_neighbour_too(self):
        county, area = areas.area_for(59.6519, 17.9186)  # Arlanda
        self.assertEqual(county, "01")
        self.assertIn("03", area)
        county, area = areas.area_for(57.4875, 12.0762)  # Kungsbacka
        self.assertEqual(county, "13")
        self.assertIn("14", area)

    def test_a_tip_far_from_any_border_belongs_to_its_county_only(self):
        county, area = areas.area_for(67.8558, 20.2253)  # Kiruna
        self.assertEqual((county, [code for code in area if len(code) == 2]), ("25", ["25"]))

    def test_without_coordinates_the_market_decides(self):
        self.assertEqual(areas.area_for(None, None, "vt"), ("14", ["14"]))
        self.assertEqual(areas.area_for(None, None, "rail"), (None, []))
        self.assertEqual(areas.area_for(None, None, None), (None, []))


class DeviceCountyTests(SimpleTestCase):
    def test_saved_counties_win_and_unknown_codes_are_dropped(self):
        self.assertEqual(areas.device_counties({"counties": ["12", "99"], "regions": ["sl"]}), ["12"])

    def test_old_market_choices_are_translated(self):
        self.assertEqual(areas.device_counties({"regions": ["skane", "rail", "okänd"]}), ["12"])

    def test_no_choice_is_no_area(self):
        self.assertEqual(areas.device_counties({}), [])
        self.assertEqual(areas.device_counties({"regions": ["rail"]}), [])
        self.assertEqual(areas.device_counties(None), [])

    def test_catalog_has_all_21_counties(self):
        self.assertEqual(len(areas.county_catalog()), 21)


class MunicipalityTests(SimpleTestCase):
    def test_city_centres_land_in_their_municipality(self):
        cases = {
            "Stockholm": (59.3326, 18.0649, "0180"), "Göteborg": (57.7089, 11.9746, "1480"),
            "Malmö": (55.6050, 13.0038, "1280"), "Kiruna": (67.8558, 20.2253, "2584"),
            "Visby": (57.6348, 18.2948, "0980"), "Arlanda": (59.6519, 17.9186, "0191"),
        }
        for place, (lat, lon, code) in cases.items():
            with self.subTest(place):
                county, municipality, area = areas.place_for(lat, lon)
                self.assertEqual(municipality, code)
                self.assertEqual(county, code[:2])
                self.assertIn(code, area)

    def test_a_tip_near_the_municipal_border_belongs_to_the_neighbour_too(self):
        _county, municipality, area = areas.place_for(59.3600, 18.0000)  # Solna, vid Stockholmsgränsen
        self.assertEqual(municipality, "0184")
        self.assertIn("0180", area)

    def test_a_chosen_municipality_replaces_its_county(self):
        self.assertEqual(areas.device_area_codes({"counties": ["01"], "municipalities": ["0180"]}), ["0180"])
        self.assertEqual(areas.device_area_codes({"counties": ["01", "03"], "municipalities": ["0180"]}), ["0180", "03"])

    def test_unknown_municipalities_are_dropped(self):
        self.assertEqual(areas.device_municipalities({"municipalities": ["0180", "9999", "x"]}), ["0180"])

    def test_the_catalog_lists_all_290_municipalities_under_their_county(self):
        catalog = areas.municipality_catalog()
        self.assertEqual(sum(len(rows) for rows in catalog.values()), 290)
        self.assertIn("Kiruna", [row["name"] for row in catalog["25"]])
