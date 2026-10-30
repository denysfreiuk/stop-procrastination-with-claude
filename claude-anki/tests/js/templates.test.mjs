// Behaviour of the scripts inlined into the AC note type templates, run in jsdom the
// way Anki runs them: desktop replaces the page content between sides, AnkiDroid loads
// each side as a new page that shares sessionStorage.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { JSDOM } from "jsdom";

const NOTETYPES = new URL("../../plugins/ankiclaude/server/src/anki_claude/notetypes/", import.meta.url);
const read = (path) => readFileSync(new URL(path, NOTETYPES), "utf8");
const VOCAB = read("vendor/anki-persistence.js") + "\n" + read("js/vocab.js");
const CODE = read("js/code.js").replace("[[ac:highlight-file]]", "_ac_highlight.min.js");
const DISTINCTION = read("js/distinction.js");
const HLJS = read("vendor/highlight-11.11.1.min.js");

function side({ word, examples, mode, key, back = false }) {
  const block = examples.map((e) => `<div class="ac-ex">${e}</div>`).join("");
  return (
    (back ? '<div id="ac-back"></div>' : "") +
    `<div class="ac ac-vocab"><div class="ac-example" data-ac-example="${mode}" data-ac-key="${key}"></div>` +
    `<span class="ac-hidden" data-ac-word>${word}</span><div class="ac-examples">${block}</div></div>`
  );
}

function page(url = "https://anki.local/") {
  return new JSDOM("<!doctype html><html><body class='card'></body></html>", { url, runScripts: "outside-only" });
}

// Anki desktop: one document, #qa replaced by each side, scripts run after insertion.
function show(dom, html, script) {
  dom.window.document.body.innerHTML = html;
  dom.window.eval(script);
  return dom.window.document.querySelector("[data-ac-example]");
}

// The example as text, with every highlighted or blanked word replaced by ___.
function sentence(element) {
  const copy = element.cloneNode(true);
  copy.querySelectorAll(".ac-hl, .ac-blank").forEach((node) => node.replaceWith("___"));
  return copy.textContent.replace(/\s+/g, " ").trim();
}

const RELUCTANT = {
  word: "reluctant",
  examples: [
    "He was <b>reluctant</b> to admit it.",
    "Many people are <b>reluctant</b> to change.",
    "She gave a <b>reluctant</b> smile.",
  ],
};

const GIVE_UP = {
  word: "give up",
  examples: [
    "She <b>gave</b> it <b>up</b> after a week.",
    "Don't <b>give up</b> now.",
    "He has <b>given up</b> sugar.",
  ],
};

test("recognition highlights the word and the back repeats the front's example (desktop)", () => {
  for (let i = 0; i < 25; i++) {
    const dom = page();
    const front = show(dom, side({ ...RELUCTANT, mode: "highlight", key: "rec" }), VOCAB);
    const shown = sentence(front);
    assert.equal(front.querySelector(".ac-hl").textContent, "reluctant");
    const back = show(dom, side({ ...RELUCTANT, mode: "highlight", key: "rec", back: true }), VOCAB);
    assert.equal(sentence(back), shown);
  }
});

test("the example is chosen at random", () => {
  const seen = new Set();
  for (let i = 0; i < 40; i++) {
    seen.add(sentence(show(page(), side({ ...RELUCTANT, mode: "highlight", key: "rec" }), VOCAB)));
  }
  assert.equal(seen.size, 3);
});

test("AnkiDroid: separate pages that share sessionStorage keep the same example", () => {
  for (let i = 0; i < 25; i++) {
    const frontPage = page();
    const shown = sentence(show(frontPage, side({ ...RELUCTANT, mode: "highlight", key: "rec" }), VOCAB));
    const backPage = page();
    const storage = frontPage.window.sessionStorage;
    for (let k = 0; k < storage.length; k++) backPage.window.sessionStorage.setItem(storage.key(k), storage.getItem(storage.key(k)));
    assert.equal(sentence(show(backPage, side({ ...RELUCTANT, mode: "highlight", key: "rec", back: true }), VOCAB)), shown);
  }
});

test("without any storage both sides agree through the seeded fallback", () => {
  const dom = page("about:blank"); // opaque origin: sessionStorage throws, as in some clients
  const shown = sentence(show(dom, side({ ...RELUCTANT, mode: "highlight", key: "rec" }), VOCAB));
  const back = show(dom, side({ ...RELUCTANT, mode: "highlight", key: "rec", back: true }), VOCAB);
  assert.equal(sentence(back), shown);
});

test("production blanks the word and prefers examples in the dictionary form", () => {
  for (let i = 0; i < 20; i++) {
    const front = show(page(), side({ ...GIVE_UP, mode: "blank", key: "prod" }), VOCAB);
    assert.equal(sentence(front), "Don't ___ now.");
    assert.equal(front.querySelectorAll(".ac-blank").length, 1);
    assert.doesNotMatch(front.textContent, /give|gave/);
  }
});

test("a split phrasal verb gets one blank per part when no example uses the dictionary form", () => {
  const examples = ["She <b>gave</b> it <b>up</b>.", "They <b>gave</b> the plan <b>up</b>."];
  const front = show(page(), side({ word: "give up", examples, mode: "blank", key: "prod" }), VOCAB);
  assert.equal(front.querySelectorAll(".ac-blank").length, 2);
});

test("the production back reveals the word in the same sentence", () => {
  const dom = page();
  const front = show(dom, side({ ...RELUCTANT, mode: "blank", key: "prod" }), VOCAB);
  const asked = sentence(front);
  const back = show(dom, side({ ...RELUCTANT, mode: "reveal", key: "prod", back: true }), VOCAB);
  assert.equal(sentence(back), asked);
  assert.equal(back.querySelector(".ac-hl").textContent, "reluctant");
});

test("production: the hint is a closed spoiler and opening it gives focus back to the typed answer", async () => {
  const dom = page();
  const hint = '<details class="ac-hint"><summary>Підказка</summary><div class="ac-hint-text">r…</div></details>';
  show(dom, side({ ...RELUCTANT, mode: "blank", key: "prod" }) + hint + '<input id="typeans">', VOCAB);
  const doc = dom.window.document;
  const details = doc.querySelector("details.ac-hint");
  assert.equal(details.open, false);
  doc.querySelector("summary").focus();
  const toggled = new Promise((resolve) => details.addEventListener("toggle", resolve, { once: true }));
  doc.querySelector("summary").click();
  await Promise.race([toggled, new Promise((_, reject) => setTimeout(() => reject(new Error("no toggle")), 1000))]);
  assert.equal(details.open, true);
  assert.equal(doc.activeElement.id, "typeans");
});

test("the forms card prefers examples that show another form", () => {
  for (let i = 0; i < 20; i++) {
    const back = show(page(), side({ ...GIVE_UP, mode: "forms", key: "forms", back: true }), VOCAB);
    assert.notEqual(sentence(back), "Don't ___ now.");
  }
});

test("empty examples are skipped and no examples hides the block", () => {
  const examples = ["", "  ", "Only <b>this</b> one."];
  assert.equal(sentence(show(page(), side({ word: "this", examples, mode: "highlight", key: "rec" }), VOCAB)), "Only ___ one.");
  const none = show(page(), side({ word: "x", examples: ["", ""], mode: "highlight", key: "rec" }), VOCAB);
  assert.equal(none.style.display, "none");
});

test("code: editor line breaks and entities become plain text, then highlight.js colours it", () => {
  const dom = page();
  dom.window.eval(HLJS);
  dom.window.document.body.innerHTML =
    '<pre class="ac-code"><code data-lang="python">import torch<br><br>if x &lt; 3:<br>&nbsp; &nbsp; print(x)</code></pre>';
  dom.window.eval(CODE);
  const code = dom.window.document.querySelector("pre.ac-code code");
  assert.equal(code.textContent, "import torch\n\nif x < 3:\n    print(x)");
  assert.ok(code.querySelector(".hljs-keyword"), "keywords are highlighted");
  assert.match(code.className, /hljs/);
});

test("code: text from the Anki editor wrapped in divs keeps its lines", () => {
  const dom = page();
  dom.window.eval(HLJS);
  dom.window.document.body.innerHTML = '<pre class="ac-code"><code data-lang=""><div>x = 1</div><div>y = 2</div></code></pre>';
  dom.window.eval(CODE);
  assert.equal(dom.window.document.querySelector("pre.ac-code code").textContent, "x = 1\ny = 2");
});

test("code: highlight.js is loaded from the collection media when missing", () => {
  const dom = page();
  dom.window.document.body.innerHTML = '<pre class="ac-code"><code data-lang="python">x = 1</code></pre>';
  dom.window.eval(CODE);
  assert.equal(dom.window.document.head.querySelector("script").getAttribute("src"), "_ac_highlight.min.js");
});

test("distinction: the back fills the blank with the answer", () => {
  const dom = page();
  dom.window.document.body.innerHTML =
    '<div class="ac ac-distinction"><div class="ac-sentence">Everyone ___ mistakes. (make / do)</div></div>' +
    '<div class="ac-answer-main" data-ac-answer>makes</div>';
  dom.window.eval(DISTINCTION);
  const filled = dom.window.document.querySelector(".ac-sentence");
  assert.equal(filled.querySelector(".ac-hl").textContent, "makes");
  assert.equal(filled.textContent, "Everyone makes mistakes. (make / do)");
});
