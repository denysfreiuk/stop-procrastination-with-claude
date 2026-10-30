/* Anki&Claude code: turns the Code field back into plain text (the Anki editor
   stores line breaks as <br> or <div>) and highlights it with highlight.js, which
   ensure_note_types puts into the collection's media. Without it the code stays plain. */
(function () {
  "use strict";
  var LIBRARY = "[[ac:highlight-file]]";

  function plain(element) {
    var html = element.innerHTML
      .replace(/<br\s*\/?>/gi, "\n")
      .replace(/<\/(div|p)>\s*<(div|p)[^>]*>/gi, "\n")
      .replace(/<[^>]+>/g, "");
    var decoder = document.createElement("textarea");
    decoder.innerHTML = html;
    return decoder.value.replace(/ /g, " ").replace(/^\n+|\s+$/g, "");
  }

  function highlight() {
    var blocks = document.querySelectorAll("pre.ac-code code");
    for (var i = 0; i < blocks.length; i++) {
      var element = blocks[i];
      if (element.getAttribute("data-ac-done")) continue;
      element.setAttribute("data-ac-done", "1");
      var text = plain(element);
      element.textContent = text;
      var hljs = window.hljs;
      if (!hljs) continue;
      var language = (element.getAttribute("data-lang") || "").replace(/^\s+|\s+$/g, "").toLowerCase();
      try {
        element.innerHTML = language && hljs.getLanguage(language)
          ? hljs.highlight(text, { language: language, ignoreIllegals: true }).value
          : hljs.highlightAuto(text).value;
        element.className += " hljs";
      } catch (e) {}
    }
  }

  if (window.hljs) {
    highlight();
  } else {
    var script = document.createElement("script");
    script.src = LIBRARY;
    script.onload = highlight;
    script.onerror = highlight;
    document.head.appendChild(script);
  }
})();
