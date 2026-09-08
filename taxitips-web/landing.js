// Sticky jump feedback for stressed scanners
const jumps = document.querySelectorAll(".jump");
const sections = ["forare", "kontor", "pris"]
  .map((id) => document.getElementById(id))
  .filter(Boolean);

if (jumps.length && sections.length && "IntersectionObserver" in window) {
  const map = new Map([
    ["forare", jumps[0]],
    ["kontor", jumps[1]],
    ["pris", jumps[2]],
  ]);
  const io = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        jumps.forEach((j) => j.classList.remove("on"));
        map.get(entry.target.id)?.classList.add("on");
      }
    },
    { rootMargin: "-35% 0px -50% 0px", threshold: 0.01 }
  );
  sections.forEach((s) => io.observe(s));
}
