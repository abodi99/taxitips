const test = require("node:test");
const assert = require("node:assert");
const { alertInSkane, placeLooksSkane } = require("../src/skane");

// The /gtfs-rt-sweden/{operator}/ feed ignores the operator path segment and
// serves national data (verified: TripUpdates from the "skane" path returned
// 100% Östergötland stops). alertInSkane's fallback used to assume
// "arrived on the skane endpoint => is Skåne", which let ~3 of 8 top-tier
// signals per 24h be Kalmar/Nybro -- 200 km outside the market, competing
// for the limited high-prio slots a driver actually sees.
test("rejects other regions that arrive on the skane endpoint", () => {
  assert.equal(
    alertInSkane({
      id: "skane:1",
      header: "Stopp i tågtrafiken",
      description: "Det är stopp i tågtrafiken mellan Kalmar C och Nybro sedan klockan 20:00.",
    }),
    false
  );
  assert.equal(
    alertInSkane({ id: "skane:2", header: "Stopp", description: "Stopp vid Göteborg C." }),
    false
  );
});

test("keeps alerts that touch Skåne even when another region is named", () => {
  // An Öresundståg running Kalmar-Malmö still strands people on the Skåne side.
  assert.equal(
    alertInSkane({
      id: "skane:3",
      header: "Försening",
      description: "Öresundståg mellan Kalmar och Malmö är försenat.",
    }),
    true
  );
});

test("keeps Skåne alerts", () => {
  assert.equal(
    alertInSkane({
      id: "skane:4",
      header: "Inställd",
      description: "Bussen är inställd Lund C - Lund Värpinge by.",
    }),
    true
  );
});

test("keeps placeless alerts rather than guessing them away", () => {
  // No city named at all -- we have no evidence it's elsewhere, so it stays.
  assert.equal(
    alertInSkane({
      id: "skane:5",
      header: "Försening",
      description: "Tåget är försenat. Orsaken är växelfel.",
    }),
    true
  );
});

// JS's \b is ASCII-only: /\böresundståg\b/ never matches, because there is no
// word/non-word transition before a non-ASCII letter at a string or space
// start. Every Skåne term beginning with å/ä/ö was silently dead in the
// geofence's text check until the lookaround rewrite.
test("matches terms starting with a, a, o (the ASCII \\b trap)", () => {
  assert.equal(
    alertInSkane({
      id: "skane:6",
      header: "Inställd",
      description: "Tåget är inställt Helsingborg C - Ängelholm.",
    }),
    true
  );
  assert.equal(
    alertInSkane({ id: "skane:7", header: "Stopp", description: "Stopp vid Örebro C." }),
    false
  );
});

test("placeLooksSkane still matches station variants", () => {
  assert.equal(placeLooksSkane("Malmö C"), true);
  assert.equal(placeLooksSkane("Lund"), true);
  assert.equal(placeLooksSkane("Kalmar"), false);
});
