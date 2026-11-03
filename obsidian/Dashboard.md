# Dashboard

Для підрахунків потрібен плагін Dataview з увімкненою опцією **Enable JavaScript Queries**. Звички по днях — на сторінці [[Звички]].

```dataviewjs
const LEARNED_SECTION = "Що вивчив";
const byDay = new Map(dv.pages('"Journal/Daily"').array().map((page) => [page.file.name, page]));
const today = dv.date("today");
const dayKey = (offset) => today.minus({ days: offset }).toFormat("yyyy-LL-dd");
const number = (value) => Number(value) || 0;
const isFilled = (value) => value !== null && value !== undefined && value !== "";

const studied = (page) =>
  number(page.focus_minutes) > 0 ||
  page.file.lists.array().some((item) => item.section?.subpath === LEARNED_SECTION);
const tiktokFree = (page) => page.tiktok_relapse !== true;

// Today is still going: an empty today keeps the streak, a day without a note breaks it.
function streak(isGood) {
  const todayPage = byDay.get(dayKey(0));
  let days = todayPage && isGood(todayPage) ? 1 : 0;
  for (let offset = 1; ; offset++) {
    const page = byDay.get(dayKey(offset));
    if (!page || !isGood(page)) return days;
    days++;
  }
}

function lastDays(count) {
  const pages = [];
  for (let offset = 0; offset < count; offset++) {
    const page = byDay.get(dayKey(offset));
    if (page) pages.push(page);
  }
  return pages;
}

const sum = (pages, field) => pages.reduce((total, page) => total + number(page[field]), 0);
const countDays = (pages, test) => pages.filter(test).length;
function average(pages, field) {
  const values = pages.map((page) => page[field]).filter(isFilled).map(number);
  return values.length ? (values.reduce((a, b) => a + b, 0) / values.length).toFixed(1) : "—";
}

const week = lastDays(7);
const month = lastDays(30);
const both = (compute) => [compute(week), compute(month)];
const relapsedToday = byDay.get(dayKey(0))?.tiktok_relapse === true;

dv.paragraph(
  `🔥 Стрік навчання: **${streak(studied)}** · 📵 Без тіктока поспіль: **${relapsedToday ? 0 : streak(tiktokFree)}**`
);

dv.table(["Показник", "7 днів", "30 днів"], [
  ["Фокус, хв", ...both((pages) => sum(pages, "focus_minutes"))],
  ["Блоків фокусу", ...both((pages) => sum(pages, "focus_blocks"))],
  ["Днів з навчанням", ...both((pages) => countDays(pages, studied))],
  ["Днів без тіктока", ...both((pages) => countDays(pages, tiktokFree))],
  ["Нових слів", ...both((pages) => sum(pages, "new_words"))],
  ["Днів у залі", ...both((pages) => countDays(pages, (page) => page.gym === true))],
  ["Сон, год (середнє)", ...both((pages) => average(pages, "sleep_hours"))],
  ["Ккал, оцінка (середнє)", ...both((pages) => average(pages, "kcal"))],
  ["Білок, г, оцінка (середнє)", ...both((pages) => average(pages, "protein_g"))],
]);

dv.header(2, "Останні 14 днів");
const shown = (value) => (isFilled(value) ? value : "—");
dv.table(
  ["День", "Фокус", "Тікток", "Сон", "Зал", "Слова"],
  lastDays(14).map((page) => [
    page.file.link,
    number(page.focus_minutes),
    page.tiktok_relapse === true ? "зрив" : "—",
    shown(page.sleep_hours),
    page.gym === true ? number(page.gym_minutes) : "—",
    number(page.new_words),
  ])
);
```
