// Extras only: every page works without this file.

// The Appearance choice on the Settings page. theme.js applies it on every page.
function setUpTheme() {
  const section = document.querySelector("[data-theme-settings]");
  if (!section) return;
  const root = document.documentElement;
  section.hidden = false;
  section.querySelectorAll('input[name="theme"]').forEach((choice) => {
    choice.checked = choice.value === (root.dataset.theme || "system");
    choice.addEventListener("change", () => {
      try {
        if (choice.value === "system") {
          delete root.dataset.theme;
          localStorage.removeItem("akda-theme");
        } else {
          root.dataset.theme = choice.value;
          localStorage.setItem("akda-theme", choice.value);
        }
      } catch (error) {
        // Storage can be blocked. The theme still changes for this page.
      }
    });
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

// The magnifying glass opens the search bar under the menu. Without this it is
// just a link to the search page.
function setUpSearch() {
  const bar = document.getElementById("site-search");
  if (!bar) return;
  const toggles = [...document.querySelectorAll("[data-search-toggle]")];
  const setOpen = (open) => {
    bar.hidden = !open;
    toggles.forEach((toggle) => toggle.setAttribute("aria-expanded", open));
    if (open) bar.querySelector("input").focus();
  };
  toggles.forEach((toggle) => {
    toggle.setAttribute("role", "button");
    toggle.setAttribute("aria-expanded", "false");
    toggle.addEventListener("click", (event) => {
      event.preventDefault();
      setOpen(bar.hidden);
    });
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || bar.hidden) return;
    setOpen(false);
    // Back to whichever glass is showing on this screen size.
    const showing = toggles.find((toggle) => toggle.offsetParent !== null);
    if (showing) showing.focus();
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
    form.dataset.showing = name;
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

function showEditorError(form, message) {
  const box = form.querySelector("[data-editor-error]");
  box.textContent = message;
  box.hidden = !message;
}

function setUpPicture(form, body) {
  const button = form.querySelector("[data-picture-button]");
  const input = form.querySelector("[data-picture-input]");
  button.addEventListener("click", () => input.click());
  input.addEventListener("change", async () => {
    const file = input.files[0];
    if (!file) return;
    const data = new FormData();
    data.append("csrf_token", form.elements.csrf_token.value);
    data.append("picture", file);
    button.disabled = true;
    button.textContent = "Uploading...";
    try {
      const response = await fetch(form.dataset.pictureUrl, {
        method: "POST", body: data, headers: { Accept: "application/json" },
      });
      const answer = await response.json();
      if (response.ok) {
        insertAround(body, { before: "\n" + answer.markdown + "\n", after: "", sample: "" });
        showEditorError(form, "");
      } else {
        showEditorError(form, answer.error);
      }
    } catch (error) {
      showEditorError(form, "The picture could not be uploaded. Please try again.");
    }
    button.disabled = false;
    button.textContent = "Picture";
    input.value = "";
  });
}

// Saves a draft a few seconds after the typing stops. Live posts have no
// data-autosave-url, so half-finished sentences can never reach readers.
function setUpAutosave(form) {
  const url = form.dataset.autosaveUrl;
  if (!url) return;
  const status = form.querySelector("[data-save-status]");
  const revision = form.querySelector("[data-revision]");
  let timer;
  let saving = false;
  let stopped = false;
  const save = async () => {
    if (stopped) return;
    if (saving) {  // one save at a time: the next one needs the new revision number
      timer = setTimeout(save, 1000);
      return;
    }
    saving = true;
    status.textContent = "Saving...";
    const fields = new URLSearchParams();
    for (const name of ["csrf_token", "revision", "title", "summary", "tags", "body_md"]) {
      fields.append(name, form.elements[name].value);
    }
    try {
      const response = await fetch(url, { method: "POST", body: fields });
      const answer = await response.json();
      if (response.ok) {
        revision.value = answer.revision;
        status.textContent = "Saved " + answer.saved;
        form.dataset.dirty = "";
        showEditorError(form, "");
      } else {
        status.textContent = "Not saved";
        showEditorError(form, answer.error);
        if (response.status === 409) stopped = true;  // reloading is the only safe next step
      }
    } catch (error) {
      status.textContent = "Not saved. Check your connection, or log in again.";
    }
    saving = false;
  };
  form.addEventListener("input", (event) => {
    if (event.target.type === "file" || event.target.name === "publish_at") return;
    clearTimeout(timer);
    timer = setTimeout(save, 4000);
  });
}

function setUpLeaveWarning(form) {
  form.addEventListener("input", () => { form.dataset.dirty = "yes"; });
  form.addEventListener("submit", () => { form.dataset.dirty = ""; });
  addEventListener("beforeunload", (event) => {
    if (form.dataset.dirty) event.preventDefault();
  });
}

function setUpScheduleLabel(form) {
  const when = form.querySelector("[data-publish-at]");
  const button = form.querySelector("[data-publish-button]");
  if (!when || !button) return;
  const label = () => { button.textContent = when.value ? "Schedule" : "Publish"; };
  when.addEventListener("input", label);
  label();
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
  setUpPicture(form, body);
  setUpAutosave(form);
  setUpLeaveWarning(form);
  setUpScheduleLabel(form);
}

setUpTheme();
setUpMenu();
setUpSearch();
setUpConfirm();
setUpEditor();
