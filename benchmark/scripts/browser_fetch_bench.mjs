import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright-core";

function arg(name, fallback) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : fallback;
}

const baseUrl = arg("--base-url", "http://127.0.0.1:8765");
const repeats = Number(arg("--repeats", "5"));
const environment = arg("--environment", "windows");
const output = arg("--output", "benchmark/results/extended/browser_fetch_windows.jsonl");
const executablePath = arg(
  "--executable",
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
);

const pages = [
  { id: "static", path: "/static", required: ["ORCHID-7429", "Agent Tool Evaluation"] },
  { id: "malformed", path: "/malformed", required: ["ORCHID-7429"] },
  { id: "unicode", path: "/unicode", required: ["兰花-7429", "ORCHID-7429"] },
  { id: "large", path: "/large", required: ["ORCHID-7429"] },
  { id: "redirect", path: "/redirect", required: ["ORCHID-7429"] },
  { id: "gzip", path: "/gzip", required: ["ORCHID-7429"] },
  { id: "dynamic", path: "/dynamic", required: ["COBALT-318"] },
];

const browser = await chromium.launch({
  executablePath,
  headless: true,
  args: ["--disable-gpu", "--no-first-run", "--no-default-browser-check"],
});
const rows = [];
try {
  for (let repeat = 0; repeat < repeats; repeat += 1) {
    for (const fixture of pages) {
      const page = await browser.newPage();
      const started = performance.now();
      let status = 0;
      let text = "";
      let error = null;
      try {
        const response = await page.goto(baseUrl + fixture.path, {
          waitUntil: "networkidle",
          timeout: 15000,
        });
        status = response?.status() ?? 0;
        text = await page.locator("body").innerText();
      } catch (exc) {
        error = String(exc);
      }
      const durationMs = performance.now() - started;
      const hits = fixture.required.filter((term) => text.includes(term)).length;
      rows.push({
        environment,
        page: fixture.id,
        client: "playwright_edge",
        extractor: "rendered_inner_text",
        repeat,
        status,
        fetch_ms: durationMs,
        extract_ms: 0,
        total_ms: durationMs,
        raw_bytes: 0,
        output_chars: text.length,
        required_hits: hits,
        required_total: fixture.required.length,
        recall: hits / fixture.required.length,
        error,
      });
      await page.close();
    }
  }
} finally {
  await browser.close();
}
fs.mkdirSync(path.dirname(output), { recursive: true });
fs.writeFileSync(output, rows.map((row) => JSON.stringify(row)).join("\n") + "\n");
console.log(JSON.stringify({ rows: rows.length, executablePath }, null, 2));
