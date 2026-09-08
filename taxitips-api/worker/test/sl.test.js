const test = require("node:test");
const assert = require("node:assert");
const {
  isActionable,
  pickVariant,
  modeHintFrom,
  normalizeDeviation,
  buildSiteIndex,
} = require("../src/sl");

const NOW = Date.parse("2026-09-05T18:00:00Z");
const hours = (n) => n * 60 * 60 * 1000;

function deviation(overrides = {}) {
  return {
    deviation_case_id: 12524985,
    publish: {
      from: new Date(NOW - hours(1)).toISOString(),
      upto: new Date(NOW + hours(4)).toISOString(),
    },
    priority: { importance_level: 7 },
    message_variants: [
      { header: "Flera inställda avgångar", details: "Vagnbrist.", language: "sv" },
    ],
    scope: { stop_areas: [], lines: [{ designation: "7", transport_mode: "TRAM" }] },
    ...overrides,
  };
}

// The single most important rule in this adapter. SL's `publish` window is
// how long the MESSAGE is published, not how long the disruption lasts --
// measured on live data, 102 of 158 deviations have windows longer than 30
// days and 34 were first published over 90 days ago. One real example is a
// roadworks notice published 2024-01-03 running to 2026-12-31. Showing that
// to a driver as a live opportunity two years on is exactly the false tip
// that destroys trust in the product.
test("rejects a long-running notice published years ago", () => {
  assert.equal(
    isActionable(
      deviation({
        publish: { from: "2024-01-03T07:45:54.647+01:00", upto: "2026-12-31T23:30:00+01:00" },
      }),
      NOW
    ),
    false
  );
});

test("rejects a recent but open-ended notice", () => {
  // Published minutes ago, but runs for a month -- a planned change, not an
  // opportunity: nobody is stranded by it right now.
  assert.equal(
    isActionable(
      deviation({
        publish: {
          from: new Date(NOW - hours(1)).toISOString(),
          upto: new Date(NOW + hours(24 * 30)).toISOString(),
        },
      }),
      NOW
    ),
    false
  );
});

test("rejects a short notice that is already over", () => {
  assert.equal(
    isActionable(
      deviation({
        publish: {
          from: new Date(NOW - hours(5)).toISOString(),
          upto: new Date(NOW - hours(1)).toISOString(),
        },
      }),
      NOW
    ),
    false
  );
});

test("accepts a recent, bounded, still-running disruption", () => {
  assert.equal(isActionable(deviation(), NOW), true);
});

test("a missing upto is treated as open-ended, not as short", () => {
  assert.equal(
    isActionable(
      deviation({ publish: { from: new Date(NOW - hours(1)).toISOString() } }),
      NOW
    ),
    false
  );
});

test("picks the Swedish variant", () => {
  const v = pickVariant([
    { header: "Delays", language: "en" },
    { header: "Förseningar", language: "sv" },
  ]);
  assert.equal(v.header, "Förseningar");
});

test("falls back to the first variant when no Swedish one exists", () => {
  assert.equal(pickVariant([{ header: "Delays", language: "en" }]).header, "Delays");
  assert.equal(pickVariant([]), null);
});

// SL's transport_mode is structural data; mode.js otherwise guesses from
// Swedish prose. METRO and TRAM are reported distinctly here and folded into
// the train tiering branch by scoring.js -- a stopped metro strands people
// exactly like a stopped train.
test("maps transport_mode, preferring the most stranding mode", () => {
  assert.equal(modeHintFrom([{ transport_mode: "BUS" }]), "bus");
  assert.equal(modeHintFrom([{ transport_mode: "METRO" }]), "metro");
  assert.equal(modeHintFrom([{ transport_mode: "TRAM" }]), "tram");
  assert.equal(
    modeHintFrom([{ transport_mode: "BUS" }, { transport_mode: "METRO" }]),
    "metro"
  );
  assert.equal(modeHintFrom([]), null);
});

test("normalizes into the shared alert shape with an sl: prefix", () => {
  const a = normalizeDeviation(deviation(), new Map());
  assert.equal(a.id, "sl:12524985");
  assert.equal(a.source, "sl");
  assert.equal(a.region, "sl");
  assert.equal(a.modeHint, "tram");
  assert.deepEqual(a.routes, ["7"]);
  assert.equal(a.sl.importanceLevel, 7);
});

test("resolves coordinates via the stop_area index", () => {
  const index = buildSiteIndex([
    { stop_area_id: "80351", site_id: "1", name: "Södergården", lat: 59.2, lon: 18.1 },
  ]);
  const a = normalizeDeviation(
    deviation({
      scope: { stop_areas: [{ id: 80351, name: "Södergården" }], lines: [] },
    }),
    index
  );
  assert.equal(a.lat, 59.2);
  assert.equal(a.lon, 18.1);
  assert.deepEqual(a.areas, ["Södergården"]);
});

// A line-level disruption has no single location. Inventing one (e.g. the
// line's first stop) would send drivers to a specific wrong corner of
// Stockholm with false precision -- worse than admitting we don't know.
test("leaves coordinates null rather than guessing a location", () => {
  const a = normalizeDeviation(deviation(), new Map());
  assert.equal(a.lat, null);
  assert.equal(a.lon, null);
});

test("an unknown stop_area id yields null, not a wrong coordinate", () => {
  const index = buildSiteIndex([
    { stop_area_id: "999", site_id: "9", name: "Annat", lat: 59.9, lon: 18.9 },
  ]);
  const a = normalizeDeviation(
    deviation({ scope: { stop_areas: [{ id: 80351, name: "Södergården" }], lines: [] } }),
    index
  );
  assert.equal(a.lat, null);
});
