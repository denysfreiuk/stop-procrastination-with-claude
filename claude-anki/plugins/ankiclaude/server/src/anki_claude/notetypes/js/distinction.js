/* Anki&Claude distinction: on the back, fills the blank (3+ underscores) of the
   sentence with the highlighted answer. */
(function () {
  "use strict";
  var sentence = document.querySelector(".ac-distinction .ac-sentence");
  var answer = document.querySelector("[data-ac-answer]");
  if (!sentence || !answer || sentence.getAttribute("data-ac-done")) return;
  sentence.setAttribute("data-ac-done", "1");
  var filled = '<span class="ac-hl">' + answer.innerHTML + "</span>";
  sentence.innerHTML = sentence.innerHTML.replace(/_{3,}/, filled);
})();
