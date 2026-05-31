(function () {
  "use strict";

  const TAB_LABELS = {
    dashboard: "Dashboard",
    printers: "Impresoras",
    addressBook: "Libreta de direcciones",
    counters: "Contadores",
    inventory: "Inventario",
    tonerControl: "Control de toner",
    config: "Configuracion",
    printerAssets: "Inv. Impresoras",
  };

  const ACTION_ICONS = [
    { match: /(editar|edit)/i, icon: "bi-pencil-square", label: "Editar" },
    { match: /(eliminar|delete|borrar)/i, icon: "bi-trash3", label: "Eliminar" },
    { match: /(libreta|address)/i, icon: "bi-journal-text", label: "Libreta" },
    { match: /(ver|detalle|detail)/i, icon: "bi-eye", label: "Ver" },
    { match: /(actualizar|refrescar|refresh)/i, icon: "bi-arrow-clockwise", label: "Refrescar" },
    { match: /(csv|export)/i, icon: "bi-filetype-csv", label: "Exportar" },
  ];

  function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = value == null ? "" : String(value);
    return div.innerHTML;
  }

  function ensureTopbar() {
    const content = document.querySelector(".content");
    if (!content || document.getElementById("appContextBar")) return;
    const bar = document.createElement("div");
    bar.id = "appContextBar";
    bar.className = "app-context-bar";
    bar.innerHTML = [
      '<div class="app-breadcrumb"><span>Ricoh Monitor</span><i class="bi bi-chevron-right"></i><strong id="appContextTitle">Dashboard</strong></div>',
      '<div class="app-context-meta"><span id="appContextTime">Listo</span></div>',
    ].join("");
    content.insertBefore(bar, content.firstChild);
  }

  function updateContext(tabName) {
    ensureTopbar();
    const title = document.getElementById("appContextTitle");
    const time = document.getElementById("appContextTime");
    if (title) title.textContent = TAB_LABELS[tabName] || tabName || "Dashboard";
    if (time) time.textContent = "Actualizado " + new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function enhanceActionButtons(root) {
    (root || document).querySelectorAll("td:last-child .action-button").forEach((btn) => {
      btn.classList.add("row-action-button");
      if (btn.dataset.dsActionEnhanced === "true") return;
      const rawText = (btn.textContent || "").trim();
      const iconConfig = ACTION_ICONS.find((item) => item.match.test(rawText));
      if (!iconConfig) return;
      btn.title = btn.title || iconConfig.label;
      btn.setAttribute("aria-label", btn.getAttribute("aria-label") || iconConfig.label);
      if (!btn.querySelector("i")) {
        btn.innerHTML = '<i class="bi ' + iconConfig.icon + '"></i><span>' + escapeHtml(rawText || iconConfig.label) + "</span>";
      }
      btn.dataset.dsActionEnhanced = "true";
    });
  }

  function enhanceSummaryCards(root) {
    (root || document).querySelectorAll(".summary-card").forEach((card) => {
      if (card.querySelector(".summary-meta")) return;
      const title = (card.querySelector("h3")?.textContent || "").trim().toLowerCase();
      let meta = "Monitoreo activo";
      if (title.includes("online") || title.includes("activo")) meta = "Estado saludable";
      else if (title.includes("offline") || title.includes("crit") || title.includes("bajo")) meta = "Requiere atencion";
      else if (title.includes("toner")) meta = "Inventario controlado";
      const node = document.createElement("div");
      node.className = "summary-meta";
      node.textContent = meta;
      const value = card.querySelector(".value");
      if (value) value.insertAdjacentElement("afterend", node);
    });
  }

  function enhanceEmptyStates(root) {
    (root || document).querySelectorAll("td").forEach((td) => {
      const text = (td.textContent || "").trim();
      if (!text || td.querySelector(".empty-state")) return;
      if (/^(no hay|sin resultados|no se encontraron|no data|no assets|no printers)/i.test(text)) {
        td.innerHTML = '<div class="empty-state ds-empty"><i class="bi bi-inbox"></i><div class="empty-title">' + text + '</div><div class="empty-subtitle">Ajusta los filtros o agrega un nuevo registro.</div></div>';
      }
    });
  }

  function enhanceStatusBadges(root) {
    (root || document).querySelectorAll(".status-badge, .badge").forEach((el) => {
      const text = (el.textContent || "").toLowerCase();
      if (text.includes("online") || text.includes("activo") || text.includes("active")) el.classList.add("badge-success");
      else if (text.includes("offline") || text.includes("inactivo") || text.includes("inactive")) el.classList.add("badge-danger");
      else if (text.includes("bajo") || text.includes("low") || text.includes("warning")) el.classList.add("badge-warning");
      else if (text.includes("error") || text.includes("crit")) el.classList.add("badge-danger");
    });
  }

  function enhanceRequiredLabels() {
    document.querySelectorAll("label").forEach((label) => {
      if (!(label.textContent || "").includes("*")) return;
      label.classList.add("required-label");
      const forId = label.getAttribute("for");
      const field = forId ? document.getElementById(forId) : label.parentElement?.querySelector("input, select, textarea");
      if (field) field.setAttribute("aria-required", "true");
    });
  }

  function decorateConfirm(title, message) {
    const modal = document.getElementById("appConfirmModal");
    const msg = document.getElementById("appConfirmMessage");
    if (!modal || !msg) return;
    const raw = ((title || "") + " " + (message || "")).toLowerCase();
    const tone = /(eliminar|borrar|delete|remove)/i.test(raw) ? "danger" : /(aplicar|importar|cambiar|guardar)/i.test(raw) ? "warning" : "info";
    modal.classList.remove("confirm-danger", "confirm-warning", "confirm-info");
    modal.classList.add("confirm-modal", "confirm-" + tone);
    const icon = tone === "danger" ? "bi-exclamation-triangle" : tone === "warning" ? "bi-info-circle" : "bi-question-circle";
    msg.innerHTML = [
      '<div class="confirm-copy">',
      '<span class="confirm-icon confirm-icon-' + tone + '"><i class="bi ' + icon + '"></i></span>',
      '<span>' + escapeHtml(message || "Esta accion necesita confirmacion.") + "</span>",
      "</div>",
    ].join("");
  }

  function wrapConfirm() {
    const original = window.appConfirm;
    if (typeof original !== "function" || original.__dsConfirmWrapped) return;
    const wrapped = function (title, message) {
      const result = original.apply(this, arguments);
      requestAnimationFrame(() => decorateConfirm(title, message));
      return result;
    };
    wrapped.__dsConfirmWrapped = true;
    window.appConfirm = wrapped;
  }

  function enhance(root) {
    enhanceActionButtons(root);
    enhanceSummaryCards(root);
    enhanceEmptyStates(root);
    enhanceStatusBadges(root);
    enhanceRequiredLabels();
  }

  function setBusy(button, busyText) {
    if (!button) return () => {};
    const prev = button.innerHTML;
    button.disabled = true;
    button.classList.add("is-busy");
    button.innerHTML = '<span class="button-spinner"></span><span>' + (busyText || "Guardando...") + "</span>";
    return () => {
      button.disabled = false;
      button.classList.remove("is-busy");
      button.innerHTML = prev;
    };
  }

  function wrapAsync(name, buttonSelector, busyText) {
    const original = window[name];
    if (typeof original !== "function" || original.__dsWrapped) return;
    const wrapped = async function (...args) {
      const restore = setBusy(document.querySelector(buttonSelector), busyText);
      try {
        return await original.apply(this, args);
      } finally {
        restore();
        setTimeout(() => enhance(document), 80);
      }
    };
    wrapped.__dsWrapped = true;
    window[name] = wrapped;
  }

  function install() {
    ensureTopbar();
    enhance(document);

    if (typeof window.showTab === "function" && !window.showTab.__dsContextWrapped) {
      const originalShowTab = window.showTab;
      window.showTab = function (tabName) {
        const result = originalShowTab.apply(this, arguments);
        updateContext(tabName);
        setTimeout(() => enhance(document), 80);
        return result;
      };
      window.showTab.__dsContextWrapped = true;
    }

    wrapAsync("savePrinter", "#drawerPanel .drawer-footer .action-button:last-child", "Guardando...");
    wrapAsync("addInventoryItem", "#inventoryFormModal .modal-actions .action-button:last-child", "Guardando...");
    wrapAsync("savePrinterAsset", "#printerAssetFormModal .modal-actions .action-button:last-child", "Guardando...");
    wrapAsync("confirmAddressBookAuthModal", "#addressBookAuthModal .modal-actions .action-button:last-child", "Conectando...");
    wrapAsync("saveTonerControl", "#tonerControlModal .modal-actions .action-button:last-child", "Guardando...");
    wrapConfirm();

    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        mutation.addedNodes.forEach((node) => {
          if (node.nodeType === 1) enhance(node);
        });
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });
    updateContext(document.querySelector(".tab.active")?.id || "dashboard");
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", install);
  else install();
})();
