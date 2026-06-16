// =========================================================================
// app.js — Entry point
// =========================================================================
//
// Buzzing Focus — a multi-source news aggregator with AI summaries
// and vim-style keyboard navigation.
//
// Architecture
// ┌──────────┐    ┌──────────┐    ┌──────────┐
// │ core.js  │◄───│  api.js  │◄───│  ui.js   │
// │ state    │    │ network  │    │ DOM      │
// │ utils    │    │ streams  │    │ render   │
// │ config   │    │ summary  │    │ keyboard │
// └──────────┘    └──────────┘    └──────────┘
//                                      ▲
//                   ┌──────────────────┘
//                   │  app.js (entry)
//                   └──────────────────┘
// =========================================================================

import { init } from './ui.js';

// Boot the application once the DOM is ready.
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
