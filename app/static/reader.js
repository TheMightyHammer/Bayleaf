/* Bayleaf EPUB reader glue code.
   Expects epub.min.js to be loaded before this script.

   Required HTML elements (recommended IDs):
   - #viewer : container div for the EPUB rendition
   Optional controls:
   - [data-action="prev"] or #prev
   - [data-action="next"] or #next
   - #readingStatus (text status)

   The book URL is resolved in this order:
   1) <body data-book-url="...">
   2) window.BAYLEAF_BOOK_URL
   3) query params: ?book=... or ?file=... or ?path=...
*/

(() => {
  'use strict';

  const qs = (sel) => document.querySelector(sel);

  function getParam(name) {
    const u = new URL(window.location.href);
    return u.searchParams.get(name);
  }

  function setStatus(msg) {
    const el = qs('#readingStatus');
    if (el) el.textContent = msg;
  }

  function stableKey(input) {
    // Small stable hash for localStorage keys.
    // Not cryptographic. Just avoids huge keys.
    let h1 = 0x811c9dc5;
    for (let i = 0; i < input.length; i++) {
      h1 ^= input.charCodeAt(i);
      h1 = (h1 * 0x01000193) >>> 0;
    }
    return h1.toString(16).padStart(8, '0');
  }

  function resolveBookUrl() {
    const body = document.body;
    const fromAttr = body?.dataset?.bookUrl;
    if (fromAttr) return fromAttr;

    // Allow templates to inject a global.
    // Example: <script>window.BAYLEAF_BOOK_URL = "...";</script>
    // eslint-disable-next-line no-undef
    if (typeof window.BAYLEAF_BOOK_URL === 'string' && window.BAYLEAF_BOOK_URL) {
      return window.BAYLEAF_BOOK_URL;
    }

    // Fallback to query params
    return getParam('book') || getParam('file') || getParam('path') || '';
  }

  function ensureViewer() {
    const viewer = qs('#viewer');
    if (!viewer) {
      throw new Error('Missing #viewer element in read.html');
    }
    return viewer;
  }

  function bindControls(rendition) {
    const prevBtn = qs('[data-action="prev"]') || qs('#prev');
    const nextBtn = qs('[data-action="next"]') || qs('#next');

    if (prevBtn) {
      prevBtn.addEventListener('click', (e) => {
        e.preventDefault();
        rendition.prev();
      });
    }

    if (nextBtn) {
      nextBtn.addEventListener('click', (e) => {
        e.preventDefault();
        rendition.next();
      });
    }

    // Keyboard navigation
    window.addEventListener('keydown', (e) => {
      // Ignore when typing in inputs
      const tag = (document.activeElement?.tagName || '').toLowerCase();
      if (tag === 'input' || tag === 'textarea' || document.activeElement?.isContentEditable) return;

      if (e.key === 'ArrowLeft') {
        e.preventDefault();
        rendition.prev();
      } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        rendition.next();
      }
    });
  }

  async function start() {
    const viewer = ensureViewer();

    if (typeof window.ePub !== 'function') {
      setStatus('epub.js not loaded. Make sure /static/epub.min.js is included before reader.js');
      return;
    }

    const bookUrl = resolveBookUrl();
    if (!bookUrl) {
      setStatus('No book specified. Provide data-book-url on <body> or a ?book= URL parameter.');
      return;
    }

    const storageKey = `bayleaf:reader:loc:${stableKey(bookUrl)}`;
    const savedCfi = localStorage.getItem(storageKey) || '';

    setStatus('Loading book…');

    // Create book and rendition
    const book = window.ePub(bookUrl);

    // Use 100% height. Your CSS should set #viewer height (e.g. calc(100vh - header)).
    const rendition = book.renderTo(viewer, {
      width: '100%',
      height: '100%',
      spread: 'auto',
      flow: 'paginated',
    });

    // Persist location
    rendition.on('relocated', (location) => {
      try {
        const cfi = location?.start?.cfi;
        if (cfi) localStorage.setItem(storageKey, cfi);
      } catch {
        // ignore storage errors
      }
    });

    // Show a nicer title if the book metadata is available
    try {
      const metadata = await book.loaded.metadata;
      const title = metadata?.title;
      if (title) {
        const titleEl = qs('#bookTitle');
        if (titleEl) titleEl.textContent = title;
        document.title = `${title} · Bayleaf`;
      }
    } catch {
      // ignore
    }

    bindControls(rendition);

    try {
      if (savedCfi) {
        await rendition.display(savedCfi);
      } else {
        await rendition.display();
      }
      setStatus('');
    } catch (err) {
      console.error(err);
      setStatus('Could not open this EPUB. Check the URL and that the file is accessible from the container.');
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
