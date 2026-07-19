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
  bindResilientCommentForms();
  bindFeedbackRealtime();
});

const PENDING_COMMENT_STORAGE_KEY = "make-it-pop-pending-comments-v1";
const PENDING_COMMENT_MAX_AGE = 7 * 24 * 60 * 60 * 1000;
const MAX_COMMENT_RETRIES = 3;
const commentRetryTimers = new Map();
const feedbackReconnectTimers = new WeakMap();

function newCommentRequestId() {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID();
  return `${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 14)}`;
}

function readPendingComments() {
  try {
    const stored = JSON.parse(localStorage.getItem(PENDING_COMMENT_STORAGE_KEY) || "{}");
    const fresh = {};
    Object.entries(stored).forEach(([endpoint, item]) => {
      if (item?.savedAt && Date.now() - item.savedAt < PENDING_COMMENT_MAX_AGE) fresh[endpoint] = item;
    });
    return fresh;
  } catch {
    return {};
  }
}

function writePendingComments(items) {
  try {
    localStorage.setItem(PENDING_COMMENT_STORAGE_KEY, JSON.stringify(items));
  } catch {}
}

function commentEndpoint(form) {
  return form?.getAttribute("hx-post") || "";
}

function commentFormFromElement(element) {
  return element?.matches?.("form[data-resilient-comment]")
    ? element
    : element?.closest?.("form[data-resilient-comment]");
}

function setCommentDeliveryStatus(form, message, state = "") {
  const status = form?.querySelector("[data-comment-delivery-status]");
  if (!status) return;
  status.textContent = message;
  status.dataset.state = state;
}

function ensureCommentRequestId(form) {
  const input = form.querySelector('input[name="client_request_id"]');
  if (input && !input.value) input.value = newCommentRequestId();
  return input?.value || "";
}

function serializeCommentForm(form) {
  return Object.fromEntries(new FormData(form).entries());
}

function persistCommentForm(form) {
  const endpoint = commentEndpoint(form);
  if (!endpoint) return;
  ensureCommentRequestId(form);
  const pending = readPendingComments();
  pending[endpoint] = {
    data: serializeCommentForm(form),
    attempts: pending[endpoint]?.attempts || 0,
    savedAt: Date.now(),
  };
  writePendingComments(pending);
  form.classList.add("is-comment-pending");
}

function clearPendingComment(form) {
  const endpoint = commentEndpoint(form);
  const pending = readPendingComments();
  delete pending[endpoint];
  writePendingComments(pending);
  window.clearTimeout(commentRetryTimers.get(endpoint));
  commentRetryTimers.delete(endpoint);
  form.classList.remove("is-comment-pending");
}

function restorePendingComment(form, item) {
  Object.entries(item.data || {}).forEach(([name, value]) => {
    const field = form.elements.namedItem(name);
    if (field && typeof value === "string") field.value = value;
  });
  form.classList.add("is-comment-pending");
  setCommentDeliveryStatus(
    form,
    navigator.onLine ? "Saved draft — retrying…" : "Saved on this device — will send when you’re back online.",
    "pending",
  );
}

function resetDeliveredCommentForm(form) {
  const nameField = form.elements.namedItem("name");
  const rememberedName = nameField?.value || "";
  form.reset();
  if (nameField) nameField.value = rememberedName;
  const requestId = form.elements.namedItem("client_request_id");
  if (requestId) requestId.value = newCommentRequestId();
  form.dispatchEvent(new CustomEvent("comment-delivered", { bubbles: true }));
  setCommentDeliveryStatus(form, "Sent", "sent");
  window.setTimeout(() => {
    if (form.querySelector("[data-comment-delivery-status]")?.dataset.state === "sent") {
      setCommentDeliveryStatus(form, "");
    }
  }, 2200);
}

function scheduleCommentRetry(form, immediate = false) {
  if (!navigator.onLine) return;
  const endpoint = commentEndpoint(form);
  const item = readPendingComments()[endpoint];
  if (!item || item.attempts >= MAX_COMMENT_RETRIES || commentRetryTimers.has(endpoint)) {
    if (item?.attempts >= MAX_COMMENT_RETRIES) {
      setCommentDeliveryStatus(form, "Still saved on this device. Tap send to retry.", "error");
    }
    return;
  }
  const delays = [1500, 4000, 10000];
  const timer = window.setTimeout(() => {
    commentRetryTimers.delete(endpoint);
    const pending = readPendingComments();
    if (!pending[endpoint] || !navigator.onLine) return;
    pending[endpoint].attempts += 1;
    pending[endpoint].savedAt = Date.now();
    writePendingComments(pending);
    setCommentDeliveryStatus(form, "Retrying saved feedback…", "pending");
    form.requestSubmit();
  }, immediate ? 100 : delays[item.attempts] || delays.at(-1));
  commentRetryTimers.set(endpoint, timer);
}

function bindResilientCommentForms(root = document) {
  root.querySelectorAll("form[data-resilient-comment]").forEach((form) => {
    if (form.dataset.resilientBound === "true") return;
    form.dataset.resilientBound = "true";
    ensureCommentRequestId(form);
    const pending = readPendingComments()[commentEndpoint(form)];
    if (pending) {
      restorePendingComment(form, pending);
      scheduleCommentRetry(form, true);
    }
  });
}

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
  bindResilientCommentForms();
  bindFeedbackRealtime();
});

function feedbackSocketPath(root) {
  if (root.dataset.feedbackChannel === "review") return `/ws${window.location.pathname}`;
  return `/ws/assets/${root.dataset.assetId}`;
}

function setFeedbackLiveState(root, state, label) {
  root.dataset.liveConnection = state;
  root.querySelectorAll("[data-live-state]").forEach((badge) => {
    const text = badge.querySelector("b");
    if (text) text.textContent = label;
  });
}

function replaceFeedbackStatus(root, html) {
  if (!html) return;
  root.querySelectorAll("#status-wrap, #review-status").forEach((target) => {
    target.innerHTML = html;
  });
}

function initializeLiveMarkup(container) {
  if (!container || !window.Alpine?.initTree) return;
  Array.from(container.children).forEach((child) => {
    if (!child._x_marker) window.Alpine.initTree(child);
  });
}

function applyFeedbackEvent(root, event) {
  const thread = root.querySelector("#comments");
  if (!thread || !event?.type) return;
  if (event.type === "feedback.snapshot") {
    thread.innerHTML = event.comments_html || `<p id="no-comments" class="text-sm text-black/40 py-8 text-center">No feedback yet.</p>`;
    replaceFeedbackStatus(root, event.status_html);
    initializeLiveMarkup(thread);
  } else if (event.type === "comment.created") {
    if (!document.getElementById(`comment-${event.comment_id}`)) {
      thread.querySelector("#no-comments")?.remove();
      thread.insertAdjacentHTML("beforeend", event.comment_html);
      initializeLiveMarkup(thread);
      if (event.comment_html.includes("comment-client") && root.dataset.feedbackChannel === "asset") {
        assetFlowToast("New client feedback received.");
      }
    }
    replaceFeedbackStatus(root, event.status_html);
  } else if (event.type === "status.updated") {
    replaceFeedbackStatus(root, event.status_html);
  }
  syncFeedbackThreads();
}

function connectFeedbackRealtime(root) {
  if (!navigator.onLine || root.dataset.liveClosing === "true") return;
  window.clearTimeout(feedbackReconnectTimers.get(root));
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${scheme}://${window.location.host}${feedbackSocketPath(root)}`);
  root.feedbackSocket = socket;
  setFeedbackLiveState(root, "connecting", "Connecting");
  let heartbeat;

  socket.addEventListener("open", () => {
    root.dataset.liveAttempts = "0";
    setFeedbackLiveState(root, "connected", "Live");
    heartbeat = window.setInterval(() => {
      if (socket.readyState === WebSocket.OPEN) socket.send("ping");
    }, 25000);
  });
  socket.addEventListener("message", (message) => {
    try {
      applyFeedbackEvent(root, JSON.parse(message.data));
    } catch {}
  });
  socket.addEventListener("close", (event) => {
    window.clearInterval(heartbeat);
    if (root.dataset.liveClosing === "true" || [4401, 4403, 4404].includes(event.code)) {
      setFeedbackLiveState(root, "offline", "Offline");
      return;
    }
    setFeedbackLiveState(root, "reconnecting", "Reconnecting");
    const attempts = Number(root.dataset.liveAttempts || "0") + 1;
    root.dataset.liveAttempts = String(attempts);
    const timer = window.setTimeout(
      () => connectFeedbackRealtime(root),
      Math.min(1000 * (2 ** Math.min(attempts, 5)), 30000),
    );
    feedbackReconnectTimers.set(root, timer);
  });
  socket.addEventListener("error", () => socket.close());
}

function bindFeedbackRealtime(root = document) {
  root.querySelectorAll("[data-feedback-live]").forEach((liveRoot) => {
    if (liveRoot.dataset.liveBound === "true") return;
    liveRoot.dataset.liveBound = "true";
    connectFeedbackRealtime(liveRoot);
  });
}

window.addEventListener("online", () => {
  document.querySelectorAll("[data-feedback-live]").forEach((root) => {
    if (!root.feedbackSocket || root.feedbackSocket.readyState === WebSocket.CLOSED) {
      connectFeedbackRealtime(root);
    }
  });
});

window.addEventListener("beforeunload", () => {
  document.querySelectorAll("[data-feedback-live]").forEach((root) => {
    root.dataset.liveClosing = "true";
    root.feedbackSocket?.close(1000, "page closing");
  });
});

document.addEventListener(
  "submit",
  (event) => {
    const form = commentFormFromElement(event.target);
    if (!form) return;
    persistCommentForm(form);
    if (event.isTrusted) {
      const pending = readPendingComments();
      const endpoint = commentEndpoint(form);
      if (pending[endpoint]) pending[endpoint].attempts = 0;
      writePendingComments(pending);
    }
    if (!navigator.onLine) {
      event.preventDefault();
      event.stopImmediatePropagation();
      setCommentDeliveryStatus(form, "Saved on this device — will send when you’re back online.", "pending");
    }
  },
  true,
);

window.addEventListener("online", () => {
  const pending = readPendingComments();
  Object.values(pending).forEach((item) => { item.attempts = 0; });
  writePendingComments(pending);
  document.querySelectorAll("form[data-resilient-comment]").forEach((form) => {
    const endpoint = commentEndpoint(form);
    if (!pending[endpoint]) return;
    restorePendingComment(form, pending[endpoint]);
    scheduleCommentRetry(form, true);
  });
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
  const commentForm = commentFormFromElement(trigger);
  if (commentForm) {
    persistCommentForm(commentForm);
    setCommentDeliveryStatus(commentForm, "Sending…", "pending");
  }
  trigger.classList.add("is-loading");
  trigger.setAttribute("aria-busy", "true");
});

document.addEventListener("htmx:afterRequest", (event) => {
  const trigger = event.detail.elt;
  trigger.classList.remove("is-loading");
  trigger.removeAttribute("aria-busy");
  const commentForm = commentFormFromElement(trigger);
  if (commentForm && event.detail.successful) {
    clearPendingComment(commentForm);
    resetDeliveredCommentForm(commentForm);
    return;
  }
  if (commentForm) {
    const status = event.detail.xhr?.status || 0;
    if (status === 0 || status >= 500) {
      setCommentDeliveryStatus(commentForm, "Saved on this device — retrying shortly.", "pending");
      scheduleCommentRetry(commentForm);
    } else {
      const pending = readPendingComments();
      const endpoint = commentEndpoint(commentForm);
      if (pending[endpoint]) pending[endpoint].attempts = MAX_COMMENT_RETRIES;
      writePendingComments(pending);
      setCommentDeliveryStatus(commentForm, "Not sent. Your text is saved so you can correct it and retry.", "error");
    }
    return;
  }
  if (!event.detail.successful) {
    assetFlowToast("That action could not be completed. Please try again.");
  }
});

document.addEventListener("htmx:sendError", (event) => {
  const commentForm = commentFormFromElement(event.detail.elt);
  if (!commentForm) return;
  persistCommentForm(commentForm);
  setCommentDeliveryStatus(commentForm, "Saved on this device — will retry when the connection returns.", "pending");
  scheduleCommentRetry(commentForm);
});

document.addEventListener("htmx:beforeSwap", (event) => {
  if (event.detail.target?.id !== "comments" || !event.detail.serverResponse) return;
  const parsed = new DOMParser().parseFromString(event.detail.serverResponse, "text/html");
  const incoming = parsed.querySelector(".comment[id]");
  if (incoming?.id && document.getElementById(incoming.id)) event.detail.shouldSwap = false;
});

document.addEventListener("htmx:afterSwap", (event) => {
  const emptyComments = document.getElementById("no-comments");
  if (emptyComments && document.querySelectorAll("#comments .comment").length) {
    emptyComments.remove();
  }
  syncFeedbackThreads();
  bindReviewLinkCopy(event.detail.target || document);
  bindResilientCommentForms(event.detail.target || document);
});
