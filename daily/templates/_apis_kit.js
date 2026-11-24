/* APIS dashboard kit (included inside <script> of every emailed dashboard): rich hover tooltips for any element with a
   title (HTML or SVG), light / dark theme with a remembered choice, sticky filter bar under the header, and small helpers. */
(function () {
  "use strict";
  var K = window.APIS = window.APIS || {};
  // ---- rich tooltip: replaces the browser's slow plain title box everywhere (charts, cells, chips)
  var tip = document.createElement("div");
  tip.className = "tipx"; tip.setAttribute("role", "tooltip");
  document.addEventListener("DOMContentLoaded", function () { document.body.appendChild(tip); });
  if (document.body) document.body.appendChild(tip);
  function textOf(el) {
    if (!el || el === document) return null;
    if (el.dataset && el.dataset.tip) return el.dataset.tip;
    if (el.getAttribute && el.getAttribute("title")) { el.dataset.tip = el.getAttribute("title"); el.removeAttribute("title"); return el.dataset.tip; }
    if (el.namespaceURI === "http://www.w3.org/2000/svg") {
      var t = el.querySelector && el.querySelector(":scope > title");
      if (t) { el.dataset.tip = t.textContent; t.remove(); return el.dataset.tip; }
    }
    return null;
  }
  function find(el) { for (var n = el, i = 0; n && i < 6; n = n.parentNode, i++) { var t = textOf(n); if (t) return t; } return null; }
  function esc(s) { return String(s).replace(/[&<>]/g, function (c) { return {"&": "&amp;", "<": "&lt;", ">": "&gt;"}[c]; }); }
  document.addEventListener("mouseover", function (e) {
    var t = find(e.target);
    if (!t) { tip.classList.remove("on"); return; }
    // "Label: value" first line in bold
    var s = esc(t), i = s.indexOf(":");
    tip.innerHTML = i > 0 && i < 60 ? "<b>" + s.slice(0, i) + "</b>" + s.slice(i) : s;
    tip.classList.add("on");
  });
  document.addEventListener("mousemove", function (e) {
    if (!tip.classList.contains("on")) return;
    var w = tip.offsetWidth, h = tip.offsetHeight, x = e.clientX + 14, y = e.clientY + 16;
    if (x + w > window.innerWidth - 8) x = e.clientX - w - 14;
    if (y + h > window.innerHeight - 8) y = e.clientY - h - 12;
    tip.style.left = x + "px"; tip.style.top = y + "px";
  });
  document.addEventListener("mouseout", function (e) { if (!e.relatedTarget || !find(e.relatedTarget)) tip.classList.remove("on"); });
  document.addEventListener("scroll", function () { tip.classList.remove("on"); }, true);

  // ---- theme: remembered per browser; follows the computer when never chosen
  K.theme = function (key) {
    var root = document.documentElement;
    try { var s = localStorage.getItem(key); if (s) root.dataset.theme = s; } catch (e) { /* private mode */ }
    return function () {
      var dark = root.dataset.theme ? root.dataset.theme === "dark" : window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches;
      root.dataset.theme = dark ? "light" : "dark";
      try { localStorage.setItem(key, root.dataset.theme); } catch (e) { /* private mode */ }
    };
  };
  // ---- the filter bar sits right under the (sticky) header, whatever its height
  K.stickUnder = function (hdr) {
    function set() { document.documentElement.style.setProperty("--hdr", (hdr.offsetHeight || 96) + "px"); }
    set(); window.addEventListener("resize", set);
  };
  // ---- tiny inline sparkline (array of numbers / nulls)
  K.spark = function (vals, color, w, h) {
    w = w || 120; h = h || 28;
    var v = vals.filter(function (x) { return x !== null && x !== undefined; });
    if (v.length < 2) return "";
    var lo = Math.min.apply(null, v), hi = Math.max.apply(null, v), n = vals.length, d = "", pen = false;
    vals.forEach(function (x, i) {
      if (x === null || x === undefined) { pen = false; return; }
      var px = (i * (w - 4) / (n - 1) + 2).toFixed(1), py = (h - 3 - (x - lo) * (h - 6) / ((hi - lo) || 1)).toFixed(1);
      d += (pen ? "L" : "M") + px + " " + py; pen = true;
    });
    return '<svg class="spark" width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + " " + h + '"><path d="' + d + '" fill="none" stroke="' + (color || "#5e3c0f") + '" stroke-width="1.8" stroke-linecap="round"/></svg>';
  };
})();
