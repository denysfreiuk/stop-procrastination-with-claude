// The habit tracker of the vault (obsidian/Звички.md): its DataviewJS block run in jsdom
// with a fake Dataview and a fake Obsidian app that keeps the notes as text.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { JSDOM } from "jsdom";

const PAGE = readFileSync(new URL("../../../obsidian/Звички.md", import.meta.url), "utf8");
const SCRIPT = PAGE.match(/```dataviewjs\r?\n([\s\S]*?)```/)[1];
const AsyncFunction = (async () => {}).constructor;
const TODAY = "2026-11-03";
const [TIKTOK, FOCUS, LEARNED, WORDS, GYM, SLEEP, SUMMARY] = [0, 1, 2, 3, 4, 5, 6];

const ALL_DONE = { focus_minutes: 50, new_words: 2, gym: true, sleep_hours: 7, tiktok_relapse: false };

function noteText({ summary }) {
  return ["---", "focus_minutes: 0", "tiktok_relapse: false", "gym: false", "---",
    "## Що вивчив", "## Підсумок", ...(summary ? ["Добрий день."] : []), "## Лог", ""].join("\n");
}

// Headings, the frontmatter and every other non-empty line, the way Obsidian's metadata cache reports them.
function metadata(text) {
  const lines = text.split(/\r?\n/);
  const end = lines.indexOf("---", 1);
  const at = (line) => ({ position: { start: { line } } });
  const headings = [];
  const sections = [{ type: "yaml", ...at(0) }];
  lines.forEach((line, index) => {
    if (index <= end || !line) return;
    const heading = /^(#+) (.*)$/.exec(line);
    if (heading) headings.push({ heading: heading[2], level: heading[1].length, ...at(index) });
    sections.push({ type: heading ? "heading" : "paragraph", ...at(index) });
  });
  return { headings, sections };
}

async function render(days, today = TODAY) {
  const dom = new JSDOM("<!doctype html><body></body>");
  const container = dom.window.document.body;
  const texts = new Map();
  const pages = days.map(({ name, props = {}, learned = false, summary = false, text }) => {
    const path = `Journal/Daily/${name}.md`;
    texts.set(path, text ?? noteText({ summary }));
    const lists = learned ? [{ section: { subpath: "Що вивчив" } }] : [];
    return { ...props, file: { name, path, lists: { array: () => lists } } };
  });
  const dv = {
    container,
    pages: (source) => {
      assert.equal(source, '"Journal/Daily"');
      return { array: () => pages };
    },
    date: () => ({ toFormat: () => today }),
    fileLink: (path, embed, display) => ({ path, display }),
    el: (tag, link, { container: parent }) => {
      const element = parent.appendChild(parent.ownerDocument.createElement(tag));
      element.textContent = link.display;
      element.dataset.href = link.path;
      return element;
    },
  };
  const app = {
    vault: {
      getAbstractFileByPath: (path) => (texts.has(path) ? { path } : null),
      process: async (file, change) => {
        texts.set(file.path, change(texts.get(file.path)));
        return texts.get(file.path);
      },
    },
    metadataCache: { getFileCache: (file) => metadata(texts.get(file.path)) },
  };
  await new AsyncFunction("dv", "app", SCRIPT)(dv, app);
  return { container, texts };
}

function rows(container, month = 0) {
  const table = container.querySelectorAll("table.habits")[month];
  return [...table.tBodies[0].rows].map((row) => ({
    day: row.cells[0].textContent,
    link: row.cells[0].querySelector("[data-href]")?.dataset.href,
    boxes: [...row.cells].slice(1).map((cell) => cell.querySelector("input")),
  }));
}

const ticks = (row) => row.boxes.map((box) => box?.checked);
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

test("each habit is ticked from the note's own data", async () => {
  const { container } = await render([
    { name: "2026-11-01", props: ALL_DONE, learned: true, summary: true },
    { name: "2026-11-02", props: { focus_minutes: 49, new_words: 0, gym: false, sleep_hours: 6.5, tiktok_relapse: true } },
    { name: "2026-11-03", props: { sleep_hours: null } },
  ]);
  const [first, second, today] = rows(container);
  assert.deepEqual(ticks(first), [true, true, true, true, true, true, true]);
  assert.deepEqual(ticks(second), [false, false, false, false, false, false, false]);
  assert.equal(today.boxes[SLEEP].checked, false, "an empty sleep is not a goal reached");
  assert.equal(today.boxes[TIKTOK].checked, true, "no relapse written means a day without tiktok");
});

test("days are listed from the first note to today, a day without a note has nothing to tick", async () => {
  const { container } = await render([
    { name: "2026-10-30", props: ALL_DONE },
    { name: "2026-11-02", props: ALL_DONE },
  ]);
  const months = [...container.querySelectorAll("h2")].map((heading) => heading.textContent);
  assert.deepEqual(months, ["Листопад 2026", "Жовтень 2026"]);
  assert.deepEqual(rows(container, 1).map((row) => row.day), ["30 Пт", "31 Сб"]);
  const november = rows(container, 0);
  assert.deepEqual(november.map((row) => row.day), ["1 Нд", "2 Пн", "3 Вт"]);
  assert.equal(november[1].link, "Journal/Daily/2026-11-02.md");
  assert.equal(november[0].link, undefined);
  assert.deepEqual(november[0].boxes, [null, null, null, null, null, null, null]);
});

test("only the last three months are shown", async () => {
  const { container } = await render([{ name: "2026-06-15", props: ALL_DONE }]);
  const months = [...container.querySelectorAll("h2")].map((heading) => heading.textContent);
  assert.deepEqual(months, ["Листопад 2026", "Жовтень 2026", "Вересень 2026"]);
  assert.equal(rows(container, 2).length, 30);
});

test("streaks: today not done yet keeps the chain, a missing day breaks it, a relapse today ends it", async () => {
  const { container } = await render([
    { name: "2026-10-29", props: ALL_DONE, learned: true },
    { name: "2026-10-31", props: ALL_DONE, learned: true },
    { name: "2026-11-01", props: ALL_DONE, learned: true },
    { name: "2026-11-02", props: ALL_DONE, learned: true },
    { name: "2026-11-03", props: { focus_minutes: 0, tiktok_relapse: true }, learned: true },
  ]);
  const line = [...container.querySelectorAll("p")].find((p) => p.textContent.startsWith("Поспіль зараз"));
  const streaks = Object.fromEntries([...line.textContent.matchAll(/(\S+) (\d+)/g)].map(([, icon, days]) => [icon, Number(days)]));
  assert.equal(streaks["🎯"], 3);
  assert.equal(streaks["📚"], 4);
  assert.equal(streaks["📵"], 0);
});

test("a month ends with how many days each habit was done", async () => {
  const { container } = await render([
    { name: "2026-11-01", props: ALL_DONE },
    { name: "2026-11-02", props: { ...ALL_DONE, gym: false } },
  ]);
  const totals = [...container.querySelector("table.habits tfoot tr").cells].map((cell) => cell.textContent);
  assert.equal(totals[0], "Разом");
  assert.equal(totals[1 + GYM], "1/3");
  assert.equal(totals[1 + TIKTOK], "2/3");
});

test("a click on 🏋️ or 📵 rewrites only that property's line", async () => {
  const { container, texts } = await render([{ name: "2026-11-02", props: { gym: false, tiktok_relapse: false } }]);
  const path = "Journal/Daily/2026-11-02.md";
  const before = texts.get(path);
  const [day] = rows(container);

  day.boxes[GYM].click();
  await settle();
  assert.equal(texts.get(path), before.replace("gym: false", "gym: true"));

  day.boxes[TIKTOK].click();
  await settle();
  assert.equal(texts.get(path), before.replace("gym: false", "gym: true").replace("tiktok_relapse: false", "tiktok_relapse: true"));
});

test("habits that come from the bot's records cannot be clicked", async () => {
  const { container, texts } = await render([{ name: "2026-11-02", props: { focus_minutes: 0 } }]);
  const before = texts.get("Journal/Daily/2026-11-02.md");
  const [day] = rows(container);
  for (const habit of [FOCUS, LEARNED, WORDS, SLEEP, SUMMARY]) {
    day.boxes[habit].click();
    assert.equal(day.boxes[habit].checked, false);
  }
  await settle();
  assert.equal(texts.get("Journal/Daily/2026-11-02.md"), before);
});

test("a missing property is added inside the frontmatter and CRLF line endings stay", async () => {
  const text = "---\r\ndate: 2026-11-02\r\n---\r\n## Лог\r\n";
  const { container, texts } = await render([{ name: "2026-11-02", props: {}, text }]);
  rows(container)[0].boxes[GYM].click();
  await settle();
  assert.equal(texts.get("Journal/Daily/2026-11-02.md"), "---\r\ndate: 2026-11-02\r\ngym: true\r\n---\r\n## Лог\r\n");
});
