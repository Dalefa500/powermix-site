/* Profix — панель руководителя. Данные берутся из МойСклад через /api. */

const PERIODS = [
  { label: "1 день", days: 1 },
  { label: "10 дней", days: 10 },
  { label: "20 дней", days: 20 },
  { label: "30 дней", days: 30 },
  ...Array.from({ length: 11 }, (_, i) => ({ label: `${i + 2} мес.`, days: (i + 2) * 30 })),
];

const TABS = { balance: "Баланс", report: "Отчёт", stock: "Остатки", team: "Команда" };

const state = {
  tab: "balance",
  reportDays: 30,
  teamDays: 30,
  detail: null, // {href, name} когда открыт человек из «Команды»
  stockQuery: "",
  from: 0, // направление последнего перехода между вкладками
  loadedAt: 0,
};

// Без слушателя касаний Safari на iPhone не применяет :active,
// и нажатия визуально не отзываются.
document.addEventListener("touchstart", () => {}, { passive: true });

const $ = (sel) => document.querySelector(sel);
const viewEl = (name) => document.querySelector(`.view[data-view="${name}"]`);

const nf = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });
const money = (n) => `${nf.format(Math.round(n || 0))} с.`;
// В плитках место узкое — единица валюты подразумевается, как в кассе.
const amount = (n) => nf.format(Math.round(n || 0));
// Знак суммы: минус красным, плюс зелёным, ноль обычным.
const sign = (n) => (n < 0 ? "neg" : n > 0 ? "pos" : "");
const qty = (n) => new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 3 }).format(n || 0);

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/* ── Сеть ─────────────────────────────────────────────── */

class AuthError extends Error {}

async function api(path) {
  const res = await fetch(path, { headers: { Accept: "application/json" } });
  if (res.status === 401) throw new AuthError("Нужно войти заново");
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Ошибка ${res.status}`);
  }
  return res.json();
}

/* ── Вход ─────────────────────────────────────────────── */

function showLogin() {
  $("#app").hidden = true;
  $("#login").hidden = false;
  $("#pin").value = "";
}

function showApp() {
  $("#login").hidden = true;
  $("#app").hidden = false;
  render();
}

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.target.querySelector("button");
  const error = $("#login-error");
  button.disabled = true;
  error.hidden = true;
  try {
    const res = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pin: $("#pin").value }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || "Не удалось войти");
    }
    showApp();
  } catch (err) {
    error.textContent = err.message;
    error.hidden = false;
  } finally {
    button.disabled = false;
  }
});

/* ── Навигация ────────────────────────────────────────── */

const TAB_ORDER = ["balance", "report", "stock", "team"];

const LEAVING = ["is-leaving", "to-right"];

function endLeaving(view) {
  view.classList.remove(...LEAVING);
  view.hidden = true;
}

function selectTab(name, from = 0) {
  if (name === state.tab && !state.detail) return;
  const leaving = viewEl(state.tab);

  state.tab = name;
  state.detail = null;
  state.from = from; // -1 пришли слева, 1 справа, 0 без направления
  document
    .querySelectorAll(".tab")
    .forEach((t) => t.classList.toggle("is-active", t.dataset.tab === name));

  // Предыдущий переход мог не доиграть — снимаем его следы
  document.querySelectorAll(".view.is-leaving").forEach(endLeaving);

  document.querySelectorAll(".view").forEach((v) => {
    if (v !== leaving) v.hidden = v.dataset.view !== name;
  });

  if (from && leaving) {
    // Уходящий экран остаётся на виду и отъезжает — как в iOS
    leaving.classList.add("is-leaving");
    if (from === -1) leaving.classList.add("to-right");
    leaving.addEventListener("animationend", () => endLeaving(leaving), { once: true });
  } else if (leaving) {
    leaving.hidden = true;
  }

  window.scrollTo(0, 0);
  render();
}

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => selectTab(tab.dataset.tab));
});

/* Свайп между вкладками. Не перехватываем жест там, где он уже занят:
   лента периодов прокручивается вбок, график показывает подсказку. */
const SWIPE_MIN = 55; // px по горизонтали
const SWIPE_RATIO = 1.6; // во столько раз горизонталь должна обгонять вертикаль

let swipe = null;

$("#views").addEventListener(
  "touchstart",
  (event) => {
    if (event.touches.length !== 1) {
      swipe = null;
      return;
    }
    const touch = event.touches[0];
    swipe = {
      x: touch.clientX,
      y: touch.clientY,
      busy: Boolean(event.target.closest(".chips, .chart, .search")),
    };
  },
  { passive: true },
);

function applySwipe(dx, dy) {
  if (Math.abs(dx) < SWIPE_MIN || Math.abs(dx) < Math.abs(dy) * SWIPE_RATIO) return false;

  // Внутри карточки человека свайп вправо возвращает к списку
  if (state.detail) {
    if (dx > 0) {
      state.detail = null;
      render();
    }
    return true;
  }
  const step = dx < 0 ? 1 : -1;
  const next = TAB_ORDER[TAB_ORDER.indexOf(state.tab) + step];
  if (next) selectTab(next, step);
  return true;
}

// Срабатываем прямо во время жеста, не дожидаясь отрыва пальца —
// так переход ощущается мгновенным.
$("#views").addEventListener(
  "touchmove",
  (event) => {
    if (!swipe || swipe.busy || event.touches.length !== 1) return;
    const touch = event.touches[0];
    if (applySwipe(touch.clientX - swipe.x, touch.clientY - swipe.y)) swipe = null;
  },
  { passive: true },
);

$("#views").addEventListener(
  "touchend",
  (event) => {
    if (!swipe || swipe.busy) return;
    const touch = event.changedTouches[0];
    applySwipe(touch.clientX - swipe.x, touch.clientY - swipe.y);
    swipe = null;
  },
  { passive: true },
);

$("#back").addEventListener("click", () => {
  state.detail = null;
  render();
});

$("#refresh").addEventListener("click", () => render());

document.addEventListener("visibilitychange", () => {
  if (!document.hidden && !$("#app").hidden && Date.now() - state.loadedAt > 120_000) render();
});

/* ── Отрисовка ────────────────────────────────────────── */

function setChrome() {
  $("#title").textContent = state.detail ? state.detail.name : TABS[state.tab];
  $("#back").hidden = !state.detail;
}

function skeleton(container, tall) {
  container.replaceChildren();
  const wrap = el("div", "skeleton");
  wrap.append(el("div", "skeleton__bar" + (tall ? " skeleton__bar--tall" : "")));
  wrap.append(el("div", "skeleton__bar"));
  container.append(wrap);
}

function showError(container, message) {
  container.replaceChildren(el("div", "error", message));
}

async function render() {
  setChrome();
  const container = viewEl(state.tab);
  const button = $("#refresh");
  button.classList.add("is-busy");
  // Заглушку показываем только на пустой вкладке. Если там уже есть
  // цифры — оставляем их на экране и подменяем, когда придут свежие:
  // переход не мигает и ощущается мгновенным.
  if (!container.firstChild || container.querySelector(".skeleton")) {
    skeleton(container, state.tab === "balance");
  }
  // Свежая анимация появления на каждую перерисовку; при свайпе
  // содержимое въезжает с той стороны, откуда пришли.
  const ENTERING = ["is-entering", "is-from-left", "is-from-right"];
  container.classList.remove(...ENTERING);
  void container.offsetWidth;
  container.classList.add("is-entering");
  if (state.from === 1) container.classList.add("is-from-right");
  else if (state.from === -1) container.classList.add("is-from-left");
  state.from = 0;
  // На время перехода вкладка непрозрачна и лежит слоем выше; после
  // снимаем — иначе она перекроет фактуру страницы.
  container.addEventListener(
    "animationend",
    () => container.classList.remove(...ENTERING),
    { once: true },
  );
  try {
    if (state.tab === "balance") await renderBalance(container);
    else if (state.tab === "report") await renderReport(container);
    else if (state.tab === "stock") await renderStock(container);
    else if (state.detail) await renderTeamDetail(container);
    else await renderTeam(container);
    state.loadedAt = Date.now();
  } catch (err) {
    if (err instanceof AuthError) {
      showLogin();
      return;
    }
    showError(container, err.message);
  } finally {
    button.classList.remove("is-busy");
  }
}

function chips(current, onPick) {
  const wrap = el("div", "chips");
  PERIODS.forEach((period) => {
    const chip = el("button", "chip" + (period.days === current ? " is-active" : ""), period.label);
    chip.type = "button";
    chip.addEventListener("click", () => onPick(period.days));
    wrap.append(chip);
  });
  // Выбранный период может быть далеко справа — подкручиваем к нему.
  requestAnimationFrame(() => {
    const active = wrap.querySelector(".is-active");
    if (active) wrap.scrollLeft = active.offsetLeft - wrap.clientWidth / 2 + active.offsetWidth / 2;
  });
  return wrap;
}

function tiles(items) {
  const wrap = el("div", "tiles" + (items.length === 2 ? " tiles--two" : ""));
  items.forEach(({ label, value, tone }) => {
    const tile = el("div", "tile");
    tile.append(el("div", "tile__label", label));
    tile.append(el("div", `tile__value${tone ? ` tile__value--${tone}` : ""}`, value));
    wrap.append(tile);
  });
  return wrap;
}

/* ── Баланс ───────────────────────────────────────────── */

async function renderBalance(container) {
  const data = await api("/api/summary");
  container.replaceChildren();

  const hero = el("div", "card hero");
  hero.append(el("div", "hero__label", "Остаток в кассе"));
  hero.append(
    el("div", `hero__value is-${sign(data.total_balance)}`, money(data.total_balance)),
  );
  if (data.balance_is_estimate) {
    hero.append(el("div", "hero__note", "Посчитано по всем кассовым ордерам"));
  }
  container.append(hero);

  container.append(
    tiles([
      { label: "Доход сегодня", value: amount(data.today.income), tone: "income" },
      { label: "Расход сегодня", value: amount(data.today.expense), tone: "expense" },
      { label: "Итог", value: amount(data.today.profit), tone: sign(data.today.profit) },
    ]),
  );

  if (data.accounts.length) {
    const card = el("div", "card");
    card.append(el("div", "card__title", "Счета и кассы"));
    const rows = el("div", "rows");
    data.accounts.forEach((account) => {
      const row = el("div", "row");
      row.append(el("div", "row__label", account.name));
      row.append(el("div", `row__value is-${sign(account.balance)}`, money(account.balance)));
      rows.append(row);
    });
    card.append(rows);
    container.append(card);
  }

  // Ключевое сырьё — последним блоком, под кассой
  if (data.materials.length) {
    const anyLow = data.materials.some((item) => item.low);
    const card = el("div", `card${anyLow ? " card--warn" : ""}`);
    card.append(el("div", "card__title", "Ключевое сырьё"));
    const rows = el("div", "rows");
    data.materials.forEach((item) => {
      const row = el("div", "row");
      if (item.low) row.append(el("span", "dot"));
      row.append(el("div", "row__label", item.name));
      const value = el(
        "div",
        `row__value${item.low ? " row__value--warn" : ""}`,
        qty(item.stock),
      );
      if (item.uom) value.append(el("span", "row__unit", ` ${item.uom}`));
      row.append(value);
      rows.append(row);
    });
    card.append(rows);
    container.append(card);
  }
}

/* ── Отчёт ────────────────────────────────────────────── */

async function renderReport(container) {
  const data = await api(`/api/report?days=${state.reportDays}`);
  container.replaceChildren();

  container.append(
    chips(state.reportDays, (days) => {
      state.reportDays = days;
      render();
    }),
  );

  container.append(
    tiles([
      { label: "Доход", value: amount(data.totals.income), tone: "income" },
      { label: "Расход", value: amount(data.totals.expense), tone: "expense" },
      { label: "Прибыль", value: amount(data.totals.profit), tone: sign(data.totals.profit) },
    ]),
  );

  const card = el("div", "card");
  card.append(
    el("div", "card__title", data.granularity === "day" ? "По дням" : "По месяцам"),
  );
  if (!data.rows.length) {
    card.append(el("div", "empty", "За этот период записей нет"));
  } else {
    card.append(
      legend([
        { label: "Доход", color: "var(--income)" },
        { label: "Расход", color: "var(--expense)" },
      ]),
    );
    card.append(
      lineChart(data.rows, [
        { key: "income", label: "Доход", color: "var(--income)" },
        { key: "expense", label: "Расход", color: "var(--expense)" },
      ]),
    );
    const rows = el("div", "rows");
    [...data.rows].reverse().forEach((row) => {
      const line = el("div", "row");
      line.append(el("div", "row__label", row.label));
      line.append(el("div", "row__value row__value--col row__value--income", money(row.income)));
      line.append(el("div", "row__value row__value--col row__value--expense", money(row.expense)));
      rows.append(line);
    });
    card.append(rows);
  }
  container.append(card);
}

/* ── Остатки ──────────────────────────────────────────── */

async function renderStock(container) {
  const data = await api("/api/stock");
  container.replaceChildren();

  const search = el("input", "search");
  search.type = "search";
  search.placeholder = "Поиск по товарам и сырью";
  search.value = state.stockQuery;
  container.append(search);

  const results = el("div", "view");
  container.append(results);

  const draw = () => {
    const needle = state.stockQuery.trim().toLowerCase();
    results.replaceChildren();

    // Что заканчивается — впереди списка, пока не начали искать
    if (!needle && data.low.length) {
      const card = el("div", "card card--warn");
      card.append(
        el("div", "card__title", `На исходе · меньше ${qty(data.low_threshold)} кг`),
      );
      const rows = el("div", "rows");
      data.low.forEach((item) => {
        const row = el("div", "row");
        row.append(el("span", "dot"));
        row.append(el("div", "row__label", item.name));
        const value = el("div", "row__value row__value--warn", qty(item.stock));
        value.append(el("span", "row__unit", ` ${item.uom}`));
        row.append(value);
        rows.append(row);
      });
      card.append(rows);
      results.append(card);
    }

    let shown = 0;
    data.folders.forEach((folder) => {
      const items = needle
        ? folder.items.filter((item) => item.name.toLowerCase().includes(needle))
        : folder.items;
      if (!items.length) return;
      shown += items.length;
      const card = el("div", "card");
      const lowHere = items.filter((item) => item.low).length;
      const title = el("div", "card__title", `${folder.name} · ${items.length}`);
      if (lowHere) title.append(el("span", "card__warn", ` · ${lowHere} на исходе`));
      card.append(title);
      const rows = el("div", "rows");
      items.forEach((item) => {
        const row = el("div", "row");
        if (item.low) row.append(el("span", "dot"));
        row.append(el("div", "row__label", item.name));
        const value = el(
          "div",
          `row__value${item.low ? " row__value--warn" : ""}`,
          qty(item.stock),
        );
        if (item.uom) value.append(el("span", "row__unit", ` ${item.uom}`));
        row.append(value);
        rows.append(row);
      });
      card.append(rows);
      results.append(card);
    });
    if (!shown) results.append(el("div", "empty", "Ничего не найдено"));
  };

  search.addEventListener("input", () => {
    state.stockQuery = search.value;
    draw();
  });
  draw();
}

/* ── Команда ──────────────────────────────────────────── */

async function renderTeam(container) {
  const data = await api(`/api/team?days=${state.teamDays}`);
  container.replaceChildren();

  container.append(
    chips(state.teamDays, (days) => {
      state.teamDays = days;
      render();
    }),
  );

  const card = el("div", "card");
  card.append(el("div", "card__title", "Расход за период"));
  if (!data.people.length) {
    card.append(el("div", "empty", "За этот период расходов нет"));
  } else {
    const rows = el("div", "rows");
    data.people.forEach((person) => {
      const row = el("button", "row row--tap person");
      row.type = "button";
      row.append(el("div", "person__name", person.name));
      row.append(el("div", "person__total", money(person.total)));
      const chev = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      chev.setAttribute("viewBox", "0 0 24 24");
      chev.setAttribute("class", "chev");
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", "M9 5l7 7-7 7");
      chev.append(path);
      row.append(chev);
      row.addEventListener("click", () => {
        state.detail = { href: person.href, name: person.name };
        window.scrollTo(0, 0);
        render();
      });
      rows.append(row);
    });
    card.append(rows);
  }
  container.append(card);
}

async function renderTeamDetail(container) {
  const data = await api(
    `/api/team/detail?days=${state.teamDays}&href=${encodeURIComponent(state.detail.href)}`,
  );
  container.replaceChildren();

  container.append(
    chips(state.teamDays, (days) => {
      state.teamDays = days;
      render();
    }),
  );

  container.append(
    tiles([
      { label: "Сегодня", value: amount(data.today), tone: "expense" },
      { label: "За период", value: amount(data.total), tone: "expense" },
    ]),
  );

  const card = el("div", "card");
  card.append(el("div", "card__title", data.granularity === "day" ? "По дням" : "По месяцам"));
  if (!data.rows.length) {
    card.append(el("div", "empty", "За этот период расходов нет"));
  } else {
    card.append(barChart(data.rows));
    const rows = el("div", "rows");
    [...data.rows].reverse().forEach((row) => {
      const line = el("div", "row");
      line.append(el("div", "row__label", row.label));
      line.append(el("div", "row__value row__value--expense", money(row.amount)));
      rows.append(line);
    });
    card.append(rows);
  }
  container.append(card);
}

/* ── Графики ──────────────────────────────────────────── */

const SVG_NS = "http://www.w3.org/2000/svg";
const svgEl = (tag, attrs) => {
  const node = document.createElementNS(SVG_NS, tag);
  Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
  return node;
};

function legend(items) {
  const wrap = el("div", "legend");
  items.forEach(({ label, color }) => {
    const item = el("div", "legend__item");
    const dot = el("span", "legend__dot");
    dot.style.background = color;
    item.append(dot, el("span", null, label));
    wrap.append(item);
  });
  return wrap;
}

/** Округлённый «красивый» верх шкалы, чтобы подписи сетки читались. */
function niceMax(value) {
  if (value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  return Math.ceil(value / (magnitude / 2)) * (magnitude / 2);
}

function chartFrame(rows, maxValue) {
  const host = el("div", "chart");
  const width = 320;
  const height = 152;
  const padTop = 8;
  const padBottom = 22;
  const padLeft = 42; // колонка под подписи шкалы, чтобы не лезли на данные
  const plotHeight = height - padTop - padBottom;
  const plotWidth = width - padLeft;
  const max = niceMax(maxValue);
  const svg = svgEl("svg", {
    viewBox: `0 0 ${width} ${height}`,
    preserveAspectRatio: "none",
    role: "img",
  });
  svg.style.height = `${height}px`;

  // Сетка — приглушённая, три линии: 0, середина, максимум.
  [0, 0.5, 1].forEach((fraction) => {
    const y = padTop + plotHeight * (1 - fraction);
    svg.append(
      svgEl("line", {
        x1: padLeft, y1: y, x2: width, y2: y,
        stroke: "var(--grid)", "stroke-width": 1,
        "vector-effect": "non-scaling-stroke",
      }),
    );
    const label = svgEl("text", {
      x: padLeft - 6, y: y + 3, fill: "var(--ink-3)", "font-size": 9,
      "text-anchor": "end", "font-family": "inherit",
    });
    label.textContent = nf.format(Math.round(max * fraction));
    svg.append(label);
  });

  const xAt = (index) =>
    rows.length === 1
      ? padLeft + plotWidth / 2
      : padLeft + (index / (rows.length - 1)) * plotWidth;
  const yAt = (value) => padTop + plotHeight * (1 - Math.min(value / max, 1));

  return { host, svg, width, height, padTop, padLeft, plotWidth, plotHeight, max, xAt, yAt };
}

function xAxisLabels(frame, rows) {
  const { svg, xAt, padLeft, width, height } = frame;
  const picks = rows.length <= 2 ? rows.map((_, i) => i) : [0, Math.floor((rows.length - 1) / 2), rows.length - 1];
  [...new Set(picks)].forEach((index) => {
    const anchor = index === 0 ? "start" : index === rows.length - 1 ? "end" : "middle";
    const label = svgEl("text", {
      x: Math.min(Math.max(xAt(index), padLeft), width - 1),
      y: height - 6,
      fill: "var(--ink-3)",
      "font-size": 9.5,
      "text-anchor": anchor,
      "font-family": "inherit",
    });
    label.textContent = rows[index].label;
    svg.append(label);
  });
}

function attachTooltip(frame, rows, describe) {
  const { host, svg, width, padLeft, plotWidth, padTop, plotHeight, xAt } = frame;
  const tooltip = $("#tooltip");
  const marker = svgEl("line", {
    y1: padTop, y2: padTop + plotHeight, x1: 0, x2: 0,
    stroke: "var(--ink-3)", "stroke-width": 1, "stroke-dasharray": "3 3",
    "vector-effect": "non-scaling-stroke", opacity: 0,
  });
  svg.append(marker);

  const hide = () => {
    tooltip.hidden = true;
    marker.setAttribute("opacity", 0);
  };

  const move = (event) => {
    const rect = svg.getBoundingClientRect();
    const plotLeft = rect.left + (padLeft / width) * rect.width;
    const ratio = (event.clientX - plotLeft) / ((plotWidth / width) * rect.width);
    const index = Math.max(0, Math.min(rows.length - 1, Math.round(ratio * (rows.length - 1))));
    const x = xAt(index);
    marker.setAttribute("x1", x);
    marker.setAttribute("x2", x);
    marker.setAttribute("opacity", 1);
    tooltip.innerHTML = describe(rows[index]);
    tooltip.hidden = false;
    const left = rect.left + (x / width) * rect.width;
    tooltip.style.left = `${Math.min(Math.max(left, 70), window.innerWidth - 70)}px`;
    tooltip.style.top = `${rect.top - 8}px`;
  };

  host.addEventListener("pointerdown", move);
  host.addEventListener("pointermove", (event) => {
    if (event.pointerType === "mouse" || event.pressure > 0 || event.buttons) move(event);
  });
  host.addEventListener("pointerup", hide);
  host.addEventListener("pointerleave", hide);
  host.addEventListener("pointercancel", hide);
}

function lineChart(rows, series) {
  const maxValue = Math.max(...rows.flatMap((row) => series.map((s) => row[s.key])), 0);
  const frame = chartFrame(rows, maxValue);
  const { svg, xAt, yAt } = frame;

  series.forEach((s) => {
    const points = rows.map((row, index) => `${xAt(index)},${yAt(row[s.key])}`);
    if (rows.length === 1) {
      const [x, y] = points[0].split(",");
      svg.append(svgEl("circle", { cx: x, cy: y, r: 4, fill: s.color }));
      return;
    }
    svg.append(
      svgEl("polyline", {
        points: points.join(" "),
        fill: "none",
        stroke: s.color,
        "stroke-width": 2,
        "stroke-linecap": "round",
        "stroke-linejoin": "round",
        "vector-effect": "non-scaling-stroke",
      }),
    );
  });

  xAxisLabels(frame, rows);
  frame.host.append(svg);
  attachTooltip(frame, rows, (row) =>
    `<b>${row.label}</b><br>Доход: ${money(row.income)}<br>Расход: ${money(row.expense)}`,
  );
  return frame.host;
}

function barChart(rows) {
  const maxValue = Math.max(...rows.map((row) => row.amount), 0);
  const frame = chartFrame(rows, maxValue);
  const { svg, width, padLeft, plotWidth, xAt, yAt, padTop, plotHeight } = frame;

  const slot = plotWidth / rows.length;
  const barWidth = Math.max(1.5, Math.min(slot - 2, 20));
  const radius = barWidth >= 6 ? 2 : 0;

  rows.forEach((row, index) => {
    const y = yAt(row.amount);
    const x = xAt(index) - barWidth / 2;
    svg.append(
      svgEl("rect", {
        x: Math.min(Math.max(x, padLeft), width - barWidth),
        y,
        width: barWidth,
        height: Math.max(padTop + plotHeight - y, 1),
        rx: radius,
        fill: "var(--expense)",
      }),
    );
  });

  xAxisLabels(frame, rows);
  frame.host.append(svg);
  attachTooltip(frame, rows, (row) => `<b>${row.label}</b><br>${money(row.amount)}`);
  return frame.host;
}

/* ── Старт ────────────────────────────────────────────── */

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js"));
}

api("/api/session")
  .then((data) => (data.authenticated ? showApp() : showLogin()))
  .catch(showLogin);
