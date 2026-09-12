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

// После свайпа содержимое уже на экране — перерисовка не должна
// проигрывать появление заново.
let quietEntry = false;

// Без слушателя касаний Safari на iPhone не применяет :active,
// и нажатия визуально не отзываются.
document.addEventListener("touchstart", () => {}, { passive: true });

/* При запуске установленного на экран приложения iOS отдаёт странице
   высоту экрана без выреза: снизу остаётся незанятая полоса. Поворот
   экрана её убирает — значит система умеет посчитать правильно, просто
   при старте этого не делает. Просим явно: в мета-теге viewport Safari
   понимает высоту, ставим её равной высоте экрана. Трогаем только
   установленное приложение и только когда разрыв размером с вырез
   действительно есть, — в обычном браузере ничего не меняется. */
function fixViewportHeight() {
  const standalone =
    window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone;
  const full = window.screen && window.screen.height;
  if (!standalone || !full) return;
  const gap = full - window.innerHeight;
  if (gap <= 0 || gap > 120) return; // не похоже на вырез — не вмешиваемся

  const meta = document.querySelector('meta[name="viewport"]');
  if (!meta) return;
  meta.setAttribute(
    "content",
    `width=device-width, initial-scale=1, viewport-fit=cover, height=${full}`,
  );
}
window.addEventListener("load", () => setTimeout(fixViewportHeight, 150));

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

// Соседняя вкладка в заданную сторону; null на краях.
function neighbour(step) {
  return TAB_ORDER[TAB_ORDER.indexOf(state.tab) + step] || null;
}

function markTab(name) {
  document
    .querySelectorAll(".tab")
    .forEach((t) => t.classList.toggle("is-active", t.dataset.tab === name));
}

function selectTab(name, from = 0) {
  if (name === state.tab && !state.detail) return;
  const leaving = viewEl(state.tab);

  state.tab = name;
  state.detail = null;
  state.from = from; // -1 пришли слева, 1 справа, 0 без направления
  markTab(name);

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

  views.scrollTop = 0;
  render();
}

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => selectTab(tab.dataset.tab));
});

/* ── Свайп между вкладками ──────────────────────────────
   Экран идёт за пальцем: соседний подтягивается из-за края, текущий
   отстаёт втрое и притухает. Пока палец на экране, ничего не
   переключается — решение принимается при отрыве, по пройденному
   пути или по скорости броска. Так жест ощущается как в iOS. */

const LOCK_MIN = 5; // px — столько нужно пройти, чтобы понять: жест горизонтальный
const LOCK_RATIO = 1.1; // во столько раз горизонталь должна обгонять вертикаль
const DONE_PART = 0.24; // доля ширины экрана, после которой переход состоится
const DONE_SPEED = 0.25; // px/мс — быстрый бросок переводит и на коротком пути
const FRESH_MS = 140; // если перед отрывом палец замер, скорость не учитываем

const views = $("#views");

let gesture = null; // текущее касание
let drag = null; // начатое перетаскивание экранов

// Свайп уступает только тому, что само прокручивается вбок
// (лента периодов) и графику с подсказкой. Поле поиска не в счёт —
// из-за него свайп во «Команде» раньше через раз не срабатывал.
function busyUnder(target) {
  if (target.closest(".chart")) return true;
  for (let node = target; node && node !== views; node = node.parentElement) {
    if (node.scrollWidth > node.clientWidth + 2) {
      const overflow = getComputedStyle(node).overflowX;
      if (overflow === "auto" || overflow === "scroll") return true;
    }
  }
  return false;
}

function startDrag(step) {
  const outgoing = viewEl(state.tab);
  const next = neighbour(step);
  const incoming = next ? viewEl(next) : null;
  const width = views.clientWidth || window.innerWidth;

  document.querySelectorAll(".view.is-leaving").forEach(endLeaving);
  outgoing.classList.add("is-dragging-out");

  if (incoming) {
    incoming.classList.remove("is-entering", "is-from-left", "is-from-right");
    if (!incoming.firstChild) skeleton(incoming, next === "balance");
    incoming.hidden = false;
    incoming.classList.add("is-dragging-in");
    incoming.style.transform = `translate3d(${step * width}px, 0, 0)`;
  }
  drag = { step, next, incoming, outgoing, width, dx: 0 };
}

/* Оба экрана едут за пальцем один в один: вкладки лежат встык, как
   одно полотно, и жест тянет это полотно целиком. Ничего не наезжает
   друг на друга и не притухает. */
function paintDrag(dx) {
  const { incoming, outgoing, step, width } = drag;
  if (!incoming) {
    // У края списка вкладок полотно только пружинит
    outgoing.style.transform = `translate3d(${dx / 3}px, 0, 0)`;
    return;
  }
  // Только пиксели: проценты внутри calc() браузер пересчитывает
  // от размеров элемента на каждом кадре.
  incoming.style.transform = `translate3d(${step * width + dx}px, 0, 0)`;
  outgoing.style.transform = `translate3d(${dx}px, 0, 0)`;
}

/* Палец шлёт события чаще, чем экран успевает обновляться. Рисуем
   строго раз в кадр — иначе часть работы уходит впустую и движение
   начинает спотыкаться. */
let paintPending = false;
let paintDx = 0;

function queuePaint(dx) {
  paintDx = dx;
  if (paintPending) return;
  paintPending = true;
  requestAnimationFrame(() => {
    paintPending = false;
    if (drag) paintDrag(paintDx);
  });
}

// Доводим экраны до конца или возвращаем на место. Время берём по
// остатку пути: короткий доводится быстро, длинный — привычной кривой.
function settleDrag(commit) {
  const { incoming, outgoing, step, next, width, dx } = drag;
  const left = commit ? width - Math.abs(dx) : Math.abs(dx);
  const secs = Math.max(0.12, Math.min(0.34, (left / width) * 0.38));

  const finish = () => {
    if (!drag) return;
    drag = null;
    [outgoing, incoming].forEach((v) => {
      if (!v) return;
      v.classList.remove("is-dragging-in", "is-dragging-out", "is-settling");
      v.style.transform = "";
      v.style.opacity = "";
      v.style.transitionDuration = "";
    });
    if (commit && next) {
      outgoing.hidden = true;
      state.tab = next;
      state.from = 0;
      markTab(next);
      views.scrollTop = 0;
      quietEntry = true; // содержимое уже на экране — не проигрываем появление
      render();
    } else if (incoming) {
      incoming.hidden = true;
    }
  };

  const mover = incoming || outgoing;
  const timer = setTimeout(finish, secs * 1000 + 90);
  mover.addEventListener(
    "transitionend",
    (event) => {
      if (event.target !== mover || event.propertyName !== "transform") return;
      clearTimeout(timer);
      finish();
    },
    { once: true },
  );

  requestAnimationFrame(() => {
    [outgoing, incoming].forEach((v) => {
      if (!v) return;
      v.classList.add("is-settling");
      v.style.transitionDuration = `${secs}s`;
    });
    if (commit) {
      if (incoming) incoming.style.transform = "translate3d(0, 0, 0)";
      outgoing.style.transform = `translate3d(${-step * width}px, 0, 0)`;
    } else {
      if (incoming) incoming.style.transform = `translate3d(${step * width}px, 0, 0)`;
      outgoing.style.transform = "translate3d(0, 0, 0)";
    }
  });
}

views.addEventListener(
  "touchstart",
  (event) => {
    if (drag || event.touches.length !== 1) return;
    const touch = event.touches[0];
    gesture = {
      x: touch.clientX,
      y: touch.clientY,
      px: touch.clientX,
      pt: event.timeStamp,
      vx: 0,
      busy: busyUnder(event.target),
      locked: false,
      dead: false,
    };
  },
  { passive: true },
);

views.addEventListener(
  "touchmove",
  (event) => {
    const g = gesture;
    if (!g || g.dead || event.touches.length !== 1) return;
    const touch = event.touches[0];

    if (!g.locked) {
      const dx = touch.clientX - g.x;
      const dy = touch.clientY - g.y;
      // Сначала решаем, вдоль какой оси идёт палец, и больше не меняем
      if (Math.abs(dy) > LOCK_MIN && Math.abs(dy) >= Math.abs(dx)) {
        g.dead = true;
        return;
      }
      if (Math.abs(dx) < LOCK_MIN || Math.abs(dx) < Math.abs(dy) * LOCK_RATIO) return;
      if (g.busy) {
        g.dead = true;
        return;
      }
      g.locked = true;
      g.x = touch.clientX; // считаем путь от точки захвата — экран не прыгает
      if (!state.detail) startDrag(dx < 0 ? 1 : -1);
    }

    const move = touch.clientX - g.x;
    if (event.timeStamp > g.pt) {
      g.vx = (touch.clientX - g.px) / (event.timeStamp - g.pt);
      g.px = touch.clientX;
      g.pt = event.timeStamp;
    }
    if (drag) {
      // Тянуть можно только в ту сторону, куда начали
      const forward = drag.step === 1 ? Math.min(0, move) : Math.max(0, move);
      drag.dx = forward;
      queuePaint(forward);
    }
    event.preventDefault(); // жест наш — страница вертикально не едет
  },
  { passive: false },
);

function endGesture(event) {
  const g = gesture;
  gesture = null;
  if (!g || !g.locked) {
    if (drag) settleDrag(false);
    return;
  }
  const touch = event.changedTouches[0];
  const move = touch.clientX - g.x;
  const fresh = event.timeStamp - g.pt < FRESH_MS;
  const flick = fresh && Math.abs(g.vx) >= DONE_SPEED && Math.sign(g.vx) === Math.sign(move);

  // Внутри карточки человека свайп вправо возвращает к списку
  if (state.detail) {
    const enough = move > 0 && (move > views.clientWidth * DONE_PART || flick);
    if (enough) {
      state.detail = null;
      state.from = -1;
      render();
    }
    return;
  }
  if (!drag) return;
  const path = Math.abs(drag.dx);
  settleDrag(Boolean(drag.incoming) && (path > drag.width * DONE_PART || (flick && path > 18)));
}

views.addEventListener("touchend", endGesture, { passive: true });
views.addEventListener(
  "touchcancel",
  () => {
    gesture = null;
    if (drag) settleDrag(false);
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
  // Свежая анимация появления на каждую перерисовку; при переходе по
  // кнопке содержимое въезжает с той стороны, откуда пришли.
  const ENTERING = ["is-entering", "is-from-left", "is-from-right"];
  container.classList.remove(...ENTERING);
  if (quietEntry) {
    quietEntry = false;
    state.from = 0;
  } else {
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
  }
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

/* Полоса периодов не пересобирается при смене периода: она остаётся
   в DOM, у неё лишь переезжает отметка, а всё, что было под ней,
   заменяется. Раньше при каждом нажатии плашки создавались заново и
   вся лента вздрагивала, теряя прокрутку. */
function resetWithChips(container, current, onPick) {
  const strip = container.querySelector(".chips");
  if (!strip) {
    container.replaceChildren(chips(current, onPick));
    return;
  }
  while (strip.nextSibling) strip.nextSibling.remove();
  while (strip.previousSibling) strip.previousSibling.remove();
  strip.querySelectorAll(".chip").forEach((chip, i) => {
    chip.classList.toggle("is-active", PERIODS[i].days === current);
  });
}

function chips(current, onPick) {
  const wrap = el("div", "chips");
  PERIODS.forEach((period) => {
    const chip = el("button", "chip" + (period.days === current ? " is-active" : ""), period.label);
    chip.type = "button";
    // Без этого браузер ставит нажатую плашку в фокус и подтягивает её
    // к центру — лента дёргается прямо под пальцем.
    chip.addEventListener("mousedown", (event) => event.preventDefault());
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
  resetWithChips(container, state.reportDays, (days) => {
    state.reportDays = days;
    quietEntry = true; // меняется только период — вкладке незачем появляться заново
    render();
  });

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
  resetWithChips(container, state.teamDays, (days) => {
    state.teamDays = days;
    quietEntry = true;
    render();
  });

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
        views.scrollTop = 0;
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
  resetWithChips(container, state.teamDays, (days) => {
    state.teamDays = days;
    quietEntry = true;
    render();
  });

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
