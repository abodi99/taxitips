const test = require("node:test");
const assert = require("node:assert");
const { mapSourceEvent } = require("../src/poller");

// source_events.source is not bookkeeping: get_opportunity_detail returns it
// to the driver's explain panel ("which feed said this?"). It used to be a
// hardcoded road/transit ternary, which silently labels any third source
// "trafiklab" -- so a Stockholm tip would have claimed a Skåne feed produced
// it. Each fetcher now declares its own source.
test("a source's own declaration wins over the road/transit fallback", () => {
  const row = mapSourceEvent({
    id: "sl:93075231",
    source: "sl",
    region: "sl",
    header: "Indragna hållplatser",
    active_from: Date.now(),
  });
  assert.equal(row.source, "sl");
  assert.equal(row.external_id, "sl:93075231");
});

test("road alerts still map to trafikverket", () => {
  const row = mapSourceEvent({
    id: "tv:123:1",
    source: "trafikverket",
    sourceKind: "road",
    header: "Olycka",
    active_from: Date.now(),
  });
  assert.equal(row.source, "trafikverket");
});

// Regression guard for the fallback itself: alerts built before the `source`
// field existed (mock data, older fixtures) must keep their old labelling
// rather than becoming null or undefined.
test("fallback still labels an undeclared transit alert trafiklab", () => {
  const row = mapSourceEvent({ id: "skane:1", header: "Försening" });
  assert.equal(row.source, "trafiklab");
});

test("fallback still labels an undeclared road alert trafikverket", () => {
  const row = mapSourceEvent({ id: "tv:9:1", sourceKind: "road", header: "Olycka" });
  assert.equal(row.source, "trafikverket");
});
