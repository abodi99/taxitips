const test = require("node:test");
const assert = require("node:assert");
const { normalizeDeparture, parsePoint, minutesLate } = require("../src/trafikverketRail");
const { isRoadAlert } = require("../src/taxiRelevance");
const { classifyMode } = require("../src/mode");

const station = { name: "Motala C", lat: 58.5371, lon: 15.0364 };
const dep = (o = {}) => ({
  AdvertisedTrainIdent: "8780",
  LocationSignature: "Mot",
  AdvertisedTimeAtLocation: "2026-09-06T00:04:00.000+02:00",
  Canceled: true,
  ToLocation: [{ LocationName: "Linköping" }],
  ...o,
});

// This source exists because Trafiklab publishes realtime per regional
// authority, and every long-distance train operator (SJ, Öresundståg,
// Mälartåg, Norrtåg, MTR, VR) returns 404 there. Trains were therefore
// visible only in the three regions running their own -- Skåne, Stockholm,
// Göteborg -- and a cancelled train in Motala or Halmstad reached nobody.
test("a cancelled departure becomes a located, rail-mode alert", () => {
  const a = normalizeDeparture(dep(), station, 0);
  assert.equal(a.source, "trafikverket_rail");
  assert.equal(a.region, "rail");
  assert.equal(a.modeHint, "train");
  assert.equal(a.lat, 58.5371);
  assert.match(a.header, /inställt från Motala C/);
});

// The id prefix is "tvr:", and isRoadAlert matches ids starting "tv:" --
// a rail alert misread as road would be scored by the road path and capped
// low, which is the opposite of what a stranded platform deserves.
test("rail is not mistaken for a road situation", () => {
  const a = normalizeDeparture(dep(), station, 0);
  assert.equal(isRoadAlert(a), false);
  assert.equal(classifyMode(a), "train");
  assert.equal(isRoadAlert({ id: "tv:1:2", sourceKind: "road" }), true);
});

test("the id is stable across polls so re-polling updates one row", () => {
  assert.equal(normalizeDeparture(dep(), station, 0).id, normalizeDeparture(dep(), station, 0).id);
  assert.notEqual(
    normalizeDeparture(dep(), station, 0).id,
    normalizeDeparture(dep({ AdvertisedTrainIdent: "999" }), station, 0).id
  );
});

// Trafikverket states no end time. Without one these would sit at the top of
// the list all day, long after the platform had cleared.
//
// The window is measured from the DEPARTURE, not from active_from: the
// search now looks 8 hours ahead (so sparse northern lines are covered at
// all), and a tip found early stays dormant until ~90 min before its train.
test("a stranded platform is given a bounded lifetime", () => {
  const when = Date.parse(dep().AdvertisedTimeAtLocation);
  const a = normalizeDeparture(dep(), station, 0);
  assert.equal(a.active_to, when + 60 * 60 * 1000);
  assert.ok(a.active_from <= when, "must become visible no later than departure");
});

// A cancellation found six hours out is real but not yet actionable -- nobody
// is on the platform. Without this the 8h window would fill the list with
// tips for trains that have not begun boarding.
test("a far-future cancellation waits before it becomes visible", () => {
  const soon = new Date(Date.now() + 6 * 3600 * 1000).toISOString();
  const a = normalizeDeparture(dep({ AdvertisedTimeAtLocation: soon }), station, 0);
  assert.ok(a.active_from > Date.now() + 3 * 3600 * 1000, "should stay dormant");
});

test("an imminent cancellation is visible immediately, not backdated", () => {
  const nowish = new Date(Date.now() + 5 * 60 * 1000).toISOString();
  const a = normalizeDeparture(dep({ AdvertisedTimeAtLocation: nowish }), station, 0);
  assert.ok(a.active_from <= Date.now() + 1000, "should already be live");
  assert.ok(a.active_from >= Date.now() - 1000, "and not appear in the past");
});

test("an unknown station yields null coords, never a guess", () => {
  const a = normalizeDeparture(dep(), undefined, 0);
  assert.equal(a.lat, null);
  assert.equal(a.lon, null);
});

// WKT is lon-first; reading it lat-first puts Motala in the Indian Ocean.
test("WKT points are parsed lon-first", () => {
  assert.deepEqual(parsePoint("POINT (12.532185 57.926905)"), {
    lat: 57.926905,
    lon: 12.532185,
  });
  assert.equal(parsePoint("nonsense"), null);
});

test("delay is measured against the advertised time", () => {
  assert.equal(
    minutesLate({
      AdvertisedTimeAtLocation: "2026-09-06T00:00:00.000+02:00",
      EstimatedTimeAtLocation: "2026-09-06T00:35:00.000+02:00",
    }),
    35
  );
  assert.equal(minutesLate({}), 0);
});
