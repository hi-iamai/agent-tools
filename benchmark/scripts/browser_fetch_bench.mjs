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
  { id: "static", path: "/static", required: ["ORCHID-7429", "Agent Tool Evaluation"], expected: "Agent Tool Evaluation The canonical answer is ORCHID-7429 Structured tools reduce ambiguity while preserving evidence Metrics metric value recall 0.93 grep query ORCHID-7429" },
  { id: "malformed", path: "/malformed", required: ["ORCHID-7429"], expected: "Agent Tool Evaluation The canonical answer is ORCHID-7429 Structured tools reduce ambiguity while preserving evidence Metrics metric value recall 0.93 grep query ORCHID-7429" },
  { id: "unicode", path: "/unicode", required: ["兰花-7429", "ORCHID-7429"], expected: "工具评测 关键答案 兰花-7429 Agent Tool Evaluation The canonical answer is ORCHID-7429 Structured tools reduce ambiguity while preserving evidence Metrics metric value recall 0.93 grep query ORCHID-7429" },
  { id: "large", path: "/large", required: ["ORCHID-7429"], expected: "Agent Tool Evaluation The canonical answer is ORCHID-7429 Structured tools reduce ambiguity while preserving evidence Metrics metric value recall 0.93 grep query ORCHID-7429" },
  { id: "redirect", path: "/redirect", required: ["ORCHID-7429"], expected: "Agent Tool Evaluation The canonical answer is ORCHID-7429 Structured tools reduce ambiguity while preserving evidence Metrics metric value recall 0.93 grep query ORCHID-7429" },
  { id: "gzip", path: "/gzip", required: ["ORCHID-7429"], expected: "Agent Tool Evaluation The canonical answer is ORCHID-7429 Structured tools reduce ambiguity while preserving evidence Metrics metric value recall 0.93 grep query ORCHID-7429" },
  { id: "dynamic", path: "/dynamic", required: ["COBALT-318"], expected: "Dynamic The dynamic answer is COBALT-318" },
];

function tokenMetrics(expected, output) {
  const tokenize = (value) => value.toLowerCase().match(/[\p{L}\p{N}_.-]+/gu) ?? [];
  const counts = (tokens) => {
    const result = new Map();
    for (const token of tokens) result.set(token, (result.get(token) ?? 0) + 1);
    return result;
  };
  const expectedCounts = counts(tokenize(expected));
  const outputCounts = counts(tokenize(output));
  let overlap = 0;
  for (const [token, count] of expectedCounts) overlap += Math.min(count, outputCounts.get(token) ?? 0);
  const expectedTotal = [...expectedCounts.values()].reduce((a, b) => a + b, 0);
  const outputTotal = [...outputCounts.values()].reduce((a, b) => a + b, 0);
  const precision = outputTotal ? overlap / outputTotal : 0;
  const recall = expectedTotal ? overlap / expectedTotal : 1;
  const f1 = precision + recall ? (2 * precision * recall) / (precision + recall) : 0;
  return { content_precision: precision, content_recall: recall, content_f1: f1 };
}

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
      const metrics = tokenMetrics(fixture.expected, text);
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
        ...metrics,
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
