const test = require("node:test");
const assert = require("node:assert");
const { classifyMode } = require("../src/mode");

const m = (header, description = "", routes = []) =>
  classifyMode({ header, description, routes });

// Found by eye on the national map: Dalarna showed only `bus` in the region
// table, yet 7 of its alerts had classified as `train`. Every one was a bus.
// The cause was Dalatrafik's standard sign-off, appended to every message:
// "Har ni tider att passa, anslutande tåg eller bussar..." -- one stray word
// promoted 7 bus disruptions into the rail severity branch, where a delayed
// bus could reach line_paused and score 70.
test("boilerplate mentioning trains does not make a bus a train", () => {
  assert.equal(
    m("Buss linje 265 riskerar att bli försenad",
      "Buss linje 265 riskerar att bli försenad på grund av vägarbete. " +
      "Har ni tider att passa, anslutande tåg eller bussar, se Dalatrafiks app."),
    "bus"
  );
});

// A bus named as REPLACEMENT means the broken thing is rail. Getting this
// backwards would drop cancelled trains out of the branch that exists for
// stranded passengers.
test("a replacement bus still means a rail disruption", () => {
  assert.equal(m("Inställd - Buss ersätter", "Tåget är inställt. 2 bussar ersätter."), "train");
  assert.equal(m("Bussar ersätter spårvagnarna", "Från 17 augusti ersätter bussar spårvagnarna."), "train");
});

test("the header decides when header and body disagree", () => {
  assert.equal(m("Förseningar", "Förseningar för buss linje 173 från Skärholmen."), "bus");
  assert.equal(m("Stopp i tågtrafiken", "Det är stopp i tågtrafiken."), "train");
});

test("a stated modeHint always wins", () => {
  assert.equal(classifyMode({ header: "Förseningar", modeHint: "metro" }), "metro");
  assert.equal(classifyMode({ header: "Buss linje 1", modeHint: "tram" }), "tram");
});

test("no keyword at all stays unknown, never guessed", () => {
  assert.equal(m("Trafikinformation", "Se appen för mer information."), "unknown");
});
