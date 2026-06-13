// Theme toggle: neutral (default) <-> dogma, persisted in localStorage.
(function () {
  const KEY = "fleet-theme";
  const root = document.documentElement;
  const saved = localStorage.getItem(KEY) || "neutral";
  root.setAttribute("data-theme", saved);
  window.fleetToggleTheme = function () {
    const next = root.getAttribute("data-theme") === "dogma" ? "neutral" : "dogma";
    root.setAttribute("data-theme", next);
    localStorage.setItem(KEY, next);
  };
})();
