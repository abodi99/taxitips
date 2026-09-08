const test = require("node:test");
const assert = require("node:assert");
const {
  isActionable, modeHintFrom, normalizeSituation,
  normalizeSeverity, buildStopAreaIndex,
} = require("../src/vasttrafik");

const NOW = Date.parse("2026-09-05T20:00:00Z");
const h = (n) => n * 3600000;

function situation(o = {}) {
  return {
    situationNumber: "RT3029517",
    title: "Linje 1 och 5 är indragna",
    description: "Ersättningsbuss 1E kör. Orsaken är spårarbete.",
    severity: "slight",
    startTime: new Date(NOW - h(1)).toISOString(),
    endTime: new Date(NOW + h(3)).toISOString(),
    affectedLines: [{ designation: "1", defaultTransportModeCode: "tram" }],
    affectedStopPoints: [
      { gid: "9022014001760001", stopAreaGid: "9021014001760000",
        name: "Brunnsparken", stopAreaName: "Brunnsparken", municipalityName: "Göteborg" },
    ],
    ...o,
  };
}

// The bug this file exists for. Västtrafik publishes planned night-time track
// work weeks ahead: measured 17 of 87 situations, and 10 of the 19 that passed
// an age+duration test alone, had not started yet. A tram line going down next
// Saturday is not a taxi opportunity tonight.
test("rejects a disruption that has not started yet", () => {
  assert.equal(
    isActionable(situation({
      startTime: new Date(NOW + h(24 * 3)).toISOString(),
      endTime: new Date(NOW + h(24 * 3 + 6)).toISOString(),
    }), NOW),
    false
  );
});

test("accepts a disruption that is running right now", () => {
  assert.equal(isActionable(situation(), NOW), true);
});

test("rejects a month-long planned closure", () => {
  assert.equal(
    isActionable(situation({ endTime: new Date(NOW + h(24 * 30)).toISOString() }), NOW),
    false
  );
});

test("rejects one that already ended", () => {
  assert.equal(
    isActionable(situation({
      startTime: new Date(NOW - h(5)).toISOString(),
      endTime: new Date(NOW - h(1)).toISOString(),
    }), NOW),
    false
  );
});

test("uses defaultTransportModeCode, not prose", () => {
  assert.equal(modeHintFrom([{ defaultTransportModeCode: "tram" }]), "tram");
  assert.equal(modeHintFrom([{ defaultTransportModeCode: "bus" }]), "bus");
  assert.equal(modeHintFrom([]), null);
});

test("carries severity as evidence, never as score", () => {
  assert.equal(normalizeSeverity("slight"), "slight");
  assert.equal(normalizeSeverity("veryHigh"), "veryHigh");
  assert.equal(normalizeSeverity("nonsense"), null);
});

// Coordinates arrive as SWEREF99TM metres, not degrees. Unprojected,
// Brunnsparken's (319346, 6400119) would place a Göteborg tip in the ocean
// off Africa. The index is built from already-projected rows.
test("resolves coordinates through stopAreaGid", () => {
  const index = buildStopAreaIndex([
    { gid: "9021014001760000", name: "Brunnsparken", lat: 57.707373, lon: 11.967851 },
  ]);
  const a = normalizeSituation(situation(), index);
  assert.equal(a.id, "vt:RT3029517");
  assert.equal(a.source, "vt");
  assert.equal(a.region, "vt");
  assert.equal(a.modeHint, "tram");
  assert.ok(Math.abs(a.lat - 57.707) < 0.01, `lat ${a.lat} not in Göteborg`);
  assert.ok(Math.abs(a.lon - 11.968) < 0.01, `lon ${a.lon} not in Göteborg`);
});

test("an unknown stop area yields null, not a wrong coordinate", () => {
  const a = normalizeSituation(situation(), buildStopAreaIndex([]));
  assert.equal(a.lat, null);
  assert.equal(a.lon, null);
});
