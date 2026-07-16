(function () {
  let savedTheme = null;
  try {
    savedTheme = localStorage.getItem("assetflow-theme");
  } catch {}
  const systemDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const theme = savedTheme === "dark" || savedTheme === "light"
    ? savedTheme
    : systemDark ? "dark" : "light";
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
  const themeColor = document.querySelector('meta[name="theme-color"]');
  if (themeColor) themeColor.content = theme === "dark" ? "#111827" : "#f7f7fb";
})();
