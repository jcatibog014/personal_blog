// Extras only: every page works without this file.

function setUpTheme() {
  const button = document.querySelector("[data-theme-toggle]");
  if (!button) return;
  const root = document.documentElement;
  const isDark = () => root.dataset.theme
    ? root.dataset.theme === "dark"
    : matchMedia("(prefers-color-scheme: dark)").matches;
  const label = () => { button.textContent = isDark() ? "Light mode" : "Dark mode"; };
  button.hidden = false;
  label();
  button.addEventListener("click", () => {
    root.dataset.theme = isDark() ? "light" : "dark";
    try {
      localStorage.setItem("akda-theme", root.dataset.theme);
    } catch (error) {
      // Storage can be blocked. The theme still changes for this page.
    }
    label();
  });
}

function setUpMenu() {
  const button = document.querySelector("[data-menu-button]");
  const menu = document.getElementById(button && button.getAttribute("aria-controls"));
  if (!button || !menu) return;
  button.hidden = false;
  const setOpen = (open) => {
    button.setAttribute("aria-expanded", open);
    menu.classList.toggle("is-open", open);
  };
  button.addEventListener("click", () => setOpen(button.getAttribute("aria-expanded") !== "true"));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") setOpen(false);
  });
}

function setUpConfirm() {
  document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (!confirm(form.dataset.confirm)) event.preventDefault();
    });
  });
}

// ---------- The editor ----------

const INSERTS = {
  bold: { before: "**", after: "**", sample: "bold text" },
  italic: { before: "*", after: "*", sample: "italic text" },
  heading: { before: "\n## ", after: "\n", sample: "Heading" },
  quote: { before: "\n> ", after: "\n", sample: "A quote" },
  list: { before: "\n- ", after: "\n", sample: "List item" },
  link: { before: "[", after: "](https://)", sample: "link text" },
};

function insertAround(body, { before, after, sample }) {
  const { selectionStart: start, selectionEnd: end, value } = body;
  const middle = value.slice(start, end) || sample;
  body.setRangeText(before + middle + after, start, end, "end");
  body.setSelectionRange(start + before.length, start + before.length + middle.length);
  body.focus();
  body.dispatchEvent(new Event("input", { bubbles: true }));
}

function setUpPreview(form, body) {
  const preview = form.querySelector("[data-preview]");
  const csrf = form.elements.csrf_token.value;
  let timer;
  let latest = 0;
  const refresh = async () => {
    const asked = ++latest;
    try {
      const response = await fetch(form.dataset.previewUrl, {
        method: "POST",
        body: new URLSearchParams({ csrf_token: csrf, body_md: body.value }),
      });
      // Only the newest answer counts: a slow old one must not overwrite it.
      if (response.ok && asked === latest) preview.innerHTML = await response.text();
    } catch (error) {
      // Offline for a moment. The next keystroke tries again.
    }
  };
  body.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(refresh, 500);
  });
}

function setUpPaneTabs(form) {
  const tabs = form.querySelector("[data-pane-tabs]");
  tabs.hidden = false;
  const panes = form.querySelector("[data-panes]");
  const show = (name) => {
    panes.dataset.showing = name;
    tabs.querySelectorAll("[data-pane-tab]").forEach((tab) => {
      tab.setAttribute("aria-pressed", tab.dataset.paneTab === name);
    });
  };
  tabs.addEventListener("click", (event) => {
    const tab = event.target.closest("[data-pane-tab]");
    if (tab) show(tab.dataset.paneTab);
  });
  show("write");
}

function setUpEditor() {
  const form = document.querySelector("[data-editor]");
  if (!form) return;
  const body = form.querySelector("[data-body]");
  const toolbar = form.querySelector("[data-toolbar]");
  toolbar.hidden = false;
  toolbar.addEventListener("click", (event) => {
    const button = event.target.closest("[data-insert]");
    if (button) insertAround(body, INSERTS[button.dataset.insert]);
  });
  setUpPreview(form, body);
  setUpPaneTabs(form);
}

setUpTheme();
setUpMenu();
setUpConfirm();
setUpEditor();
