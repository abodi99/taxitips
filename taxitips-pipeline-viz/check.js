const fs = require('fs');
const acorn = require('acorn');
const html = fs.readFileSync('service.html', 'utf8');
const scriptMatch = html.match(/<script>([\s\S]*?)<\/script>/);
if (scriptMatch) {
  try {
    acorn.parse(scriptMatch[1], { ecmaVersion: 2022 });
    console.log("Syntax is OK");
  } catch(e) {
    console.error("Syntax Error: " + e);
  }
}
