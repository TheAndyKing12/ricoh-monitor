(function () {
  function setHtml(id, html) {
    const el = document.getElementById(id);
    if (el) el.innerHTML = html;
  }

  window.checkApiHealth = async function checkApiHealth() {
    setHtml("configApiStatus", '<span style="color:#fbbf24">Verificando...</span>');
    try {
      const started = performance.now();
      const response = await fetch("/health", { method: "GET" });
      const elapsed = Math.round(performance.now() - started);
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Error HTTP " + response.status);
      const color = data.status === "ok" ? "#22c55e" : "#fbbf24";
      setHtml("configApiStatus", `<span style="color:${color}"><i class="bi bi-check-circle-fill"></i> ${data.status.toUpperCase()} - ${elapsed}ms - DB: ${data.database.ok ? "OK" : "Error"} - Jobs: ${data.scheduler.jobs}</span>`);
    } catch (error) {
      setHtml("configApiStatus", '<span style="color:#ef4444"><i class="bi bi-x-circle-fill"></i> No se pudo conectar al API</span>');
      console.error("checkApiHealth error:", error);
    }
  };

  window.loadSchedulerStatus = async function loadSchedulerStatus() {
    const box = document.getElementById("schedulerStatusBox");
    if (!box) return;
    box.innerHTML = '<span style="color:#fbbf24">Cargando scheduler...</span>';
    try {
      const response = await fetch("/scheduler/status");
      const data = await response.json();
      const rows = (data.jobs || []).map((job) => {
        const stats = job.stats || {};
        const last = stats.last_finished || stats.last_started || "-";
        const ok = stats.last_success ? "OK" : (stats.last_error ? "Error" : "Pendiente");
        const color = stats.last_success ? "#22c55e" : (stats.last_error ? "#ef4444" : "#94a3b8");
        return `<tr><td>${job.id}</td><td>${job.next_run || "-"}</td><td style="color:${color}">${ok}</td><td>${last}</td><td>${stats.last_duration_seconds ?? "-"}</td></tr>`;
      }).join("");
      box.innerHTML = `<div style="font-size:13px;color:#cbd5e1;margin-bottom:10px">Estado: <strong>${data.running ? "Activo" : "Detenido"}</strong> - Cache impresoras: ${data.cache_stats?.printer_status_count ?? 0}</div><div class="table-wrapper" style="max-height:260px"><table><thead><tr><th>Job</th><th>Proxima</th><th>Ultimo estado</th><th>Ultima ejecucion</th><th>Seg.</th></tr></thead><tbody>${rows || '<tr><td colspan="5">Sin jobs.</td></tr>'}</tbody></table></div>`;
    } catch (error) {
      box.innerHTML = '<span style="color:#ef4444">No se pudo cargar el scheduler.</span>';
      console.error("loadSchedulerStatus error:", error);
    }
  };

  window.exportActivityLogs = function exportActivityLogs() {
    const category = document.getElementById("logCategoryFilter")?.value || "";
    const params = new URLSearchParams();
    if (category) params.set("category", category);
    window.open("/logs/export" + (params.toString() ? "?" + params.toString() : ""), "_blank");
  };

  window.sendTestNotification = async function sendTestNotification() {
    try {
      const response = await fetch("/notifications/test", { method: "POST" });
      if (!response.ok) throw new Error("HTTP " + response.status);
      if (window.showToast) window.showToast("Notificacion de prueba enviada", "success");
    } catch (error) {
      if (window.showToast) window.showToast("No se pudo enviar la notificacion", "error");
      console.error("sendTestNotification error:", error);
    }
  };

  const originalLoadConfig = window.loadConfig;
  window.loadConfig = function wrappedLoadConfig() {
    if (typeof originalLoadConfig === "function") originalLoadConfig();
    window.loadSchedulerStatus();
  };
})();
