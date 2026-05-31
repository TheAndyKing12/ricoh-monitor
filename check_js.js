const fs = require("fs");

const inlineScriptFiles = [
  "frontend/dashboard.html",
  "frontend/login.html",
];

const standaloneScriptFiles = [
  "frontend/sw.js",
  "frontend/js/config-tools.js",
  "frontend/js/visual-polish.js",
];

let hasError = false;

function checkScript(source, label) {
  try {
    new Function(source);
    console.log(`${label}: ok`);
  } catch (error) {
    hasError = true;
    console.error(`${label}: ${error.name}: ${error.message}`);
  }
}

for (const file of inlineScriptFiles) {
  const html = fs.readFileSync(file, "utf8");
  const scripts = [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)];

  if (!scripts.length) {
    console.log(`${file}: no inline scripts`);
    continue;
  }

  scripts.forEach((match, index) => {
    checkScript(match[1], `${file} script ${index + 1}`);
  });
}

for (const file of standaloneScriptFiles) {
  checkScript(fs.readFileSync(file, "utf8"), file);
}

if (hasError) {
  process.exit(1);
}
