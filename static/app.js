document.addEventListener("alpine:initialized", () => {
  document.documentElement.classList.add("alpine-ready");
  document.querySelectorAll(".modal-close").forEach((button) => {
    button.type = "button";
    if (!button.getAttribute("aria-label")) button.setAttribute("aria-label", "Close dialog");
  });
  if (window.innerWidth <= 1000) {
    document.querySelectorAll(".app-shell").forEach((shell) => {
      const state = window.Alpine.$data(shell);
      if (state && "sidebar" in state) state.sidebar = false;
    });
  }
  syncFeedbackThreads();
  bindReviewLinkCopy();
  bindThemeToggle();
});

function activeTheme() {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
  try {
    localStorage.setItem("assetflow-theme", theme);
  } catch {}
  const themeColor = document.querySelector('meta[name="theme-color"]');
  if (themeColor) themeColor.content = theme === "dark" ? "#111827" : "#f7f7fb";
  document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
    const dark = theme === "dark";
    button.setAttribute("aria-label", `Switch to ${dark ? "light" : "dark"} mode`);
    const label = button.querySelector(".theme-toggle-label");
    if (label) label.textContent = dark ? "Light" : "Dark";
    const icon = button.querySelector(".theme-toggle-icon");
    if (icon) icon.textContent = dark ? "☀" : "◐";
  });
}

function bindThemeToggle(root = document) {
  root.querySelectorAll("[data-theme-toggle]").forEach((button) => {
    if (button.dataset.themeBound === "true") return;
    button.dataset.themeBound = "true";
    button.addEventListener("click", () => {
      applyTheme(activeTheme() === "dark" ? "light" : "dark");
    });
  });
  applyTheme(activeTheme());
}

function placeWorkspaceThemeToggle() {
  const shell = document.querySelector(".app-shell");
  const globalToggle = document.querySelector("body > .global-theme-toggle");
  if (!shell || !globalToggle || document.querySelector(".header-theme-toggle")) return;
  const header = document.querySelector(".glass-header, .page-header, .asset-header");
  if (!header) return;
  globalToggle.classList.remove("global-theme-toggle");
  globalToggle.classList.add("header-theme-toggle");
  header.append(globalToggle);
}

document.addEventListener("DOMContentLoaded", () => {
  placeWorkspaceThemeToggle();
  bindThemeToggle();
});

function syncFeedbackThreads() {
  document.querySelectorAll(".feedback-thread").forEach((thread) => {
    const hasVisibleComment = Array.from(thread.querySelectorAll(".comment")).some(
      (comment) => window.getComputedStyle(comment).display !== "none",
    );
    thread.classList.toggle("has-visible-comments", hasVisibleComment);
  });
}

document.addEventListener("click", (event) => {
  if (event.target.closest(".feedback-filters button")) {
    window.requestAnimationFrame(syncFeedbackThreads);
  }
});

function assetFlowToast(message) {
  let region = document.getElementById("toast-region");
  if (!region) {
    region = document.createElement("div");
    region.id = "toast-region";
    region.setAttribute("role", "status");
    region.setAttribute("aria-live", "polite");
    document.body.appendChild(region);
  }
  const toast = document.createElement("div");
  toast.className = "app-toast";
  toast.textContent = message;
  region.appendChild(toast);
  window.setTimeout(() => toast.remove(), 4200);
}

function handleReviewLinkCopy(copyButton) {
  const input = document.getElementById(copyButton.dataset.copyReviewLink);
  if (!input) return;
  const label = copyButton.querySelector("span");
  window.clearTimeout(copyButton.copyNoticeTimer);
  copyButton.classList.add("copied");
  if (label) label.textContent = "Copied";
  copyButton.copyNoticeTimer = window.setTimeout(() => {
    copyButton.classList.remove("copied");
    if (label) label.textContent = "Copy";
  }, 2200);

  input.focus();
  input.select();
  input.setSelectionRange(0, input.value.length);
  let copied = false;
  try {
    copied = document.execCommand("copy");
  } catch {}
  if (!copied && navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(input.value).catch(() => {
      assetFlowToast("If the link was not copied, select it and copy manually.");
    });
  }
}

function bindReviewLinkCopy(root = document) {
  root.querySelectorAll("[data-copy-review-link]").forEach((copyButton) => {
    if (copyButton.dataset.copyBound === "true") return;
    copyButton.dataset.copyBound = "true";
    copyButton.addEventListener("click", () => handleReviewLinkCopy(copyButton));
  });
}

document.addEventListener("htmx:beforeRequest", (event) => {
  const trigger = event.detail.elt;
  trigger.classList.add("is-loading");
  trigger.setAttribute("aria-busy", "true");
});

document.addEventListener("htmx:afterRequest", (event) => {
  const trigger = event.detail.elt;
  trigger.classList.remove("is-loading");
  trigger.removeAttribute("aria-busy");
  if (!event.detail.successful) {
    assetFlowToast("That action could not be completed. Please try again.");
  }
});

document.addEventListener("htmx:afterSwap", (event) => {
  const emptyComments = document.getElementById("no-comments");
  if (emptyComments && document.querySelectorAll("#comments .comment").length) {
    emptyComments.remove();
  }
  syncFeedbackThreads();
  bindReviewLinkCopy(event.detail.target || document);
});
