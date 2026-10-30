/* Anki&Claude vocab: picks one non-empty example and shows the marked word
   highlighted, as a blank, or revealed. The back side shows the example the front
   picked: the choice is kept with Anki-Persistence (desktop, AnkiDroid, AnkiMobile);
   where that is unavailable both sides fall back to the same seeded choice.
   Words are marked in the examples with <b>…</b>; ES5 only, for old Android WebViews. */
(function () {
  "use strict";

  function norm(text) {
    return (text || "").replace(/\s+/g, " ").replace(/^\s+|\s+$/g, "").toLowerCase();
  }

  function examples() {
    var out = [];
    var nodes = document.querySelectorAll(".ac-examples .ac-ex");
    for (var i = 0; i < nodes.length; i++) {
      if (nodes[i].textContent.replace(/\s+/g, "")) out.push(nodes[i]);
    }
    return out;
  }

  function marks(node) {
    return node.querySelectorAll("b, strong");
  }

  function inBaseForm(node, word) {
    var found = marks(node);
    var parts = [];
    for (var i = 0; i < found.length; i++) parts.push(found[i].textContent);
    return found.length > 0 && norm(parts.join(" ")) === norm(word);
  }

  function filter(list, test) {
    var out = [];
    for (var i = 0; i < list.length; i++) if (test(list[i])) out.push(list[i]);
    return out.length ? out : list;
  }

  function seeded(text, size) {
    var h = 2166136261;
    for (var i = 0; i < text.length; i++) {
      h ^= text.charCodeAt(i);
      h = (h * 16777619) >>> 0;
    }
    return h % size;
  }

  function store() {
    try {
      return window.Persistence && window.Persistence.isAvailable() ? window.Persistence : null;
    } catch (e) {
      return null;
    }
  }

  function choose(pool, key, word) {
    var back = !!document.getElementById("ac-back");
    var persistence = store();
    var index = null;
    if (back && persistence) {
      try {
        index = persistence.getItem(key);
      } catch (e) {
        index = null;
      }
    }
    if (typeof index !== "number" || index < 0 || index >= pool.length) {
      index = !back && persistence
        ? Math.floor(Math.random() * pool.length)
        : seeded(norm(word) + "|" + new Date().toDateString(), pool.length);
    }
    if (!back && persistence) {
      try {
        persistence.setItem(key, index);
      } catch (e) {}
    }
    return pool[index];
  }

  function render(target, source, mode) {
    var copy = source.cloneNode(true);
    var found = marks(copy);
    for (var i = found.length - 1; i >= 0; i--) {
      var span = document.createElement("span");
      if (mode === "blank") {
        span.className = "ac-blank";
      } else {
        span.className = "ac-hl";
        span.innerHTML = found[i].innerHTML;
      }
      found[i].parentNode.replaceChild(span, found[i]);
    }
    target.innerHTML = copy.innerHTML;
  }

  var wordNode = document.querySelector("[data-ac-word]");
  var word = wordNode ? wordNode.textContent : "";
  var targets = document.querySelectorAll("[data-ac-example]");
  for (var t = 0; t < targets.length; t++) {
    var target = targets[t];
    if (target.getAttribute("data-ac-done")) continue;
    target.setAttribute("data-ac-done", "1");
    var mode = target.getAttribute("data-ac-example");
    var pool = examples();
    if (!pool.length) {
      target.style.display = "none";
      continue;
    }
    if (mode === "blank" || mode === "reveal") {
      // Production asks for the dictionary form, so prefer examples that use it.
      pool = filter(pool, function (node) { return inBaseForm(node, word); });
    } else if (mode === "forms") {
      pool = filter(pool, function (node) { return !inBaseForm(node, word); });
    }
    var picked = choose(pool, "ac-vocab:" + target.getAttribute("data-ac-key"), word);
    render(target, picked, mode === "blank" ? "blank" : "highlight");
  }

  // Opening the hint spoiler must not take focus from the typed answer: Enter checks it.
  var hint = document.querySelector("details.ac-hint");
  var typed = document.getElementById("typeans");
  if (hint && typed && !hint.getAttribute("data-ac-done")) {
    hint.setAttribute("data-ac-done", "1");
    hint.addEventListener("toggle", function () {
      typed.focus();
    });
  }
})();
