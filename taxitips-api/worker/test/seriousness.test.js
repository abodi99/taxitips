const test = require("node:test");
const assert = require("node:assert");
const { enrichAlert } = require("../src/taxiRelevance");

const alert = (header, description = "") => enrichAlert({
  id: "skane:test", header, description,
  active_from: Date.now(), active_to: Date.now() + 3600000,
});

// "inställt" -- the neuter form, and the one Swedish actually uses for a
// train ("tåget är inställt") -- was missing from SERIOUS_RE, which listed
// only inställd/inställda. Found via Västtrafik, where every cancelled
// Öresundståg reads "Öresundståg NNNN ... är inställt" and was therefore
// scored `ignore`: a cancelled train, the most valuable tip type there is,
// silently dropped.
//
// The same regex also used ASCII \b, which never matches before å/ä/ö --
// the trap already fixed twice elsewhere (skane.js, trafikverket.js).
test("a cancelled train in the neuter form is serious", () => {
  const a = alert("Öresundståg 20189 klockan 23:55 är inställt från Göteborg Central.");
  assert.notEqual(a.taxi.level, "ignore", "inställt must be recognised as serious");
});

test("the older forms still work", () => {
  assert.notEqual(alert("Tåget är inställd").taxi.level, "ignore");
  assert.notEqual(alert("Inställda avgångar").taxi.level, "ignore");
});

// Guard against the widened pattern swallowing unrelated words: "installerat"
// contains "installera", not "inställ", but a sloppy boundary could match.
test("does not fire on unrelated words", () => {
  assert.equal(alert("Hiss ur funktion").taxi.level, "ignore");
  assert.equal(alert("Vi har installerat nya skyltar").taxi.level, "ignore");
});
