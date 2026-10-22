"use strict";
// Apply an explicit preference before CSS and the first paint; OS preference is ignored.
try { document.documentElement.dataset.theme = localStorage.getItem('hemlock-theme') === 'light' ? 'light' : 'dark'; }
catch { document.documentElement.dataset.theme = 'dark'; }
