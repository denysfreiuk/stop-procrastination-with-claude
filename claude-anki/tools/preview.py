"""Preview cards exactly as Anki renders them, in a browser.

    python tools/preview.py OUT_DIR [--query "tag:status::sample"] [--url http://127.0.0.1:8765]

Serve OUT_DIR over HTTP (python -m http.server) and open preview.html; for screenshots
add ?only=0,3&theme=dark&width=680&bare=1 to show chosen cards without the controls.

Fetches the cards' rendered HTML from AnkiConnect (API v1 cards.render, falling back
to cardsInfo), then writes OUT_DIR/preview.html: every card's front and back at phone
or desktop width, in light or night mode. Each back is shown the way Anki desktop
does it: the front is rendered and its scripts run, then the same page is replaced
by the back, so "same example on both sides" can be checked. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "plugins" / "ankiclaude" / "server" / "src" / "anki_claude" / "notetypes" / "vendor"
MATHJAX = "https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5/tex-chtml.js"


def call(url: str, payload: dict, path: str = "") -> dict:
    request = urllib.request.Request(url + path, json.dumps(payload).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def v6(url: str, action: str, **params):
    reply = call(url, {"action": action, "version": 6, "params": params})
    if reply.get("error"):
        raise SystemExit(f"AnkiConnect {action}: {reply['error']}")
    return reply["result"]


def render(url: str, card_id: int) -> dict:
    reply = call(url, {"jsonrpc": "2.0", "id": 1, "method": "cards.render", "params": {"id": str(card_id)}}, "/api/v1")
    if "result" in reply:
        return {"q": reply["result"]["questionHtml"], "a": reply["result"]["answerHtml"]}
    info = v6(url, "cardsInfo", cards=[card_id])[0]
    return {"q": info["question"], "a": info["answer"]}


PAGE = r"""<!doctype html>
<html lang="uk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Anki&amp;Claude — перегляд карток</title>
<style>
  :root { color-scheme: light dark; }
  body { font: 14px/1.4 system-ui, sans-serif; margin: 0; padding: 16px; background: #eaeef2; color: #1f2328; }
  body.dark { background: #010409; color: #e6edf3; }
  header { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin-bottom: 16px; }
  button { font: inherit; padding: 6px 12px; border-radius: 8px; border: 1px solid #8c959f; background: transparent; color: inherit; cursor: pointer; }
  button[aria-pressed="true"] { background: #0969da; color: #fff; border-color: #0969da; }
  .card-row { margin-bottom: 28px; }
  .card-row h2 { font-size: 13px; font-weight: 600; margin: 0 0 6px; opacity: .75; }
  .sides { display: flex; gap: 12px; flex-wrap: wrap; align-items: flex-start; }
  iframe { border: 1px solid #8c959f; border-radius: 14px; background: #fff; height: 560px; }
  .side-label { font-size: 11px; opacity: .6; margin: 0 0 4px; }
</style></head>
<body>
<header>
  <strong>Anki&amp;Claude — перегляд</strong>
  <span>Ширина:</span><button data-width="375" aria-pressed="true">Телефон</button><button data-width="680">Комп'ютер</button>
  <span>Тема:</span><button data-theme="light" aria-pressed="true">Світла</button><button data-theme="dark">Нічна</button>
</header>
<main id="cards"></main>
<script id="data" type="application/json">__DATA__</script>
<script>
const CARDS = JSON.parse(document.getElementById("data").textContent);
// URL parameters for screenshots: ?only=0,3&theme=dark&width=680&bare=1
const params = new URLSearchParams(location.search);
const state = { width: Number(params.get("width")) || 375, theme: params.get("theme") || "light" };
const ONLY = params.get("only") ? params.get("only").split(",").map(Number) : null;
const HEIGHT = Number(params.get("height")) || 560;
// fixed=1: the same "random" example in every frame, so a front and a back screenshot match.
const FIXED = params.get("fixed") ? "<script>Math.random = function () { return 0.34; };<\/script>" : "";
if (params.get("bare")) {
  document.head.insertAdjacentHTML("beforeend", "<style>header, .card-row h2 { display: none } body { padding: 10px 12px } .card-row { margin-bottom: 12px }</style>");
}
const MATHJAX = "__MATHJAX__";
const PLAY = '<a class="replay-button soundLink" href="#" onclick="return false"><svg class="playImage" viewBox="0 0 64 64" width="40" height="40"><circle cx="32" cy="32" r="29" fill="none" stroke="currentColor" stroke-width="3" opacity=".5"/><path d="M26 20 L46 32 L26 44 Z" fill="currentColor" opacity=".7"/></svg></a>';

function ankiSubstitute(html, side) {
  html = html.replace(/\[anki:play:[qa]:\d+\]/g, PLAY);
  if (side === "q") return html.replace(/\[\[type:[^\]]+\]\]/g, '<input id="typeans" type="text" value="">');
  // A typed answer with one mistake, in the shape Anki's comparison produces.
  return html.replace(/\[\[type:[^\]]+\]\]/g, function () {
    return '<code id="typeans"><span class="typeGood">relu</span><span class="typeBad">c</span><span class="typeGood">ant</span>' +
      '<br><span id="typearrow">&darr;</span><br><span class="typeGood">relu</span><span class="typeMissed">ct</span><span class="typeGood">ant</span></code>';
  });
}

function reviewer(card, side) {
  // Mirrors Anki desktop: one page, #qa replaced by each side, scripts executed after insertion.
  const night = state.theme === "dark" ? " nightMode night_mode" : "";
  const sides = side === "q" ? ["q"] : ["q", "a"];
  return `<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<script>window.MathJax = { tex: { inlineMath: [["\\\\(", "\\\\)"]], displayMath: [["\\\\[", "\\\\]"]] } };<\/script>
<script src="${MATHJAX}" async><\/script>
<style>body { margin: 0; } #qa { min-height: 100vh; }</style>${FIXED}</head>
<body class="card card${card.ord + 1}${night}"><div id="qa"></div>
<script>
  const SIDES = ${JSON.stringify(sides.map((s) => ankiSubstitute(card[s], s))).replace(/<\//g, "<\\/")};
  function setQA(html) {
    const qa = document.getElementById("qa");
    qa.innerHTML = html;
    qa.querySelectorAll("script").forEach(function (old) {
      const s = document.createElement("script");
      if (old.src) s.src = old.src; else s.textContent = old.textContent;
      old.replaceWith(s);
    });
    if (window.MathJax && MathJax.typesetPromise) MathJax.typesetPromise([qa]);
  }
  SIDES.forEach(setQA);
  window.addEventListener("load", function () { if (window.MathJax && MathJax.typesetPromise) MathJax.typesetPromise(); });
<\/script></body></html>`;
}

function draw() {
  document.body.classList.toggle("dark", state.theme === "dark");
  const root = document.getElementById("cards");
  root.innerHTML = "";
  CARDS.forEach(function (card, index) {
    if (ONLY && !ONLY.includes(index)) return;
    const row = document.createElement("section");
    row.className = "card-row";
    row.innerHTML = `<h2>${card.model} · ${card.template} · ${card.deck}</h2><div class="sides"></div>`;
    ["q", "a"].forEach(function (side) {
      const box = document.createElement("div");
      box.innerHTML = `<p class="side-label">${side === "q" ? "Лицьова" : "Зворот"}</p>`;
      const frame = document.createElement("iframe");
      frame.style.width = state.width + "px";
      frame.style.height = HEIGHT + "px";
      frame.setAttribute("data-card", card.id);
      frame.setAttribute("data-side", side);
      frame.srcdoc = reviewer(card, side);
      box.appendChild(frame);
      row.querySelector(".sides").appendChild(box);
    });
    root.appendChild(row);
  });
}

document.querySelectorAll("button[data-width], button[data-theme]").forEach(function (button) {
  button.addEventListener("click", function () {
    const key = button.dataset.width ? "width" : "theme";
    state[key] = button.dataset.width ? Number(button.dataset.width) : button.dataset.theme;
    document.querySelectorAll(`button[data-${key}]`).forEach((b) => b.setAttribute("aria-pressed", String(b === button)));
    draw();
  });
});
draw();
</script>
</body></html>
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--query", default="tag:status::sample")
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    args = parser.parse_args()

    card_ids = v6(args.url, "findCards", query=args.query)
    infos = v6(args.url, "cardsInfo", cards=card_ids)
    names = {}
    cards = []
    for info in sorted(infos, key=lambda c: (c["note"], c["ord"])):
        model = info["modelName"]
        if model not in names:
            names[model] = list(v6(args.url, "modelTemplates", modelName=model))
        templates = names[model]
        template = templates[info["ord"]] if info["ord"] < len(templates) else f"Cloze {info['ord'] + 1}"
        cards.append({"id": info["cardId"], "ord": info["ord"], "model": model, "template": template,
                      "deck": info["deckName"], **render(args.url, info["cardId"])})

    args.out_dir.mkdir(parents=True, exist_ok=True)
    for vendor_file in VENDOR.glob("highlight-*.min.js"):
        shutil.copy(vendor_file, args.out_dir / ("_ac_" + vendor_file.name))
    data = json.dumps(cards, ensure_ascii=False).replace("</", "<\\/")
    page = PAGE.replace("__DATA__", data).replace("__MATHJAX__", MATHJAX)
    (args.out_dir / "preview.html").write_text(page, encoding="utf-8")
    print(f"{len(cards)} карток → {args.out_dir / 'preview.html'}")


if __name__ == "__main__":
    main()
