// Runs before the page paints (plain script, not a module) so accessibility settings apply with no flash.
(function () {
  var s = {};
  try { s = JSON.parse(localStorage.getItem("lanl_a11y") || "{}"); } catch (e) { s = {}; }
  var root = document.documentElement;
  var scale = Number(s.textScale) || 1;
  root.style.setProperty("--text-scale", scale);
  root.style.setProperty("--cap-scale", Number(s.captionSize) || 1);
  var add = function (c, on) { if (on) root.classList.add(c); };
  add("a11y-contrast-light", s.contrast === "high-light");
  add("a11y-contrast-dark", s.contrast === "high-dark");
  add("a11y-cvd", s.colorVision === "cvd");
  add("a11y-font-readable", s.font === "readable");
  add("a11y-spacing", !!s.spacing);
  add("a11y-underline", !!s.underline);
  add("a11y-targets", !!s.targets);
  add("a11y-large-text", scale >= 1.5);
  var reduce = s.reduceMotion === undefined ? (window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches) : s.reduceMotion;
  add("a11y-reduce-motion", !!reduce);
  add("a11y-cap-contrast", s.captionStyle === "high-contrast");
  add("a11y-cap-off", s.captions === "off");
  if (s.font === "readable") {
    var l = document.createElement("link");
    l.rel = "stylesheet";
    l.href = "https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible:ital,wght@0,400;0,700;1,400&display=swap";
    document.head.appendChild(l);
  }
})();
