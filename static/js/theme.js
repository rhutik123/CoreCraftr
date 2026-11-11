(function () {
  var STORAGE_KEY = 'corecraftr-theme';
  var mediaQuery = window.matchMedia ? window.matchMedia('(prefers-color-scheme: light)') : null;

  function getSavedPreference() {
    try {
      var val = localStorage.getItem(STORAGE_KEY);
      if (val === 'light' || val === 'dark' || val === 'system') {
        return val;
      }
    } catch (e) {
      // ignore storage errors
    }
    return 'dark';
  }

  function resolveTheme(mode) {
    if (mode === 'system') {
      return mediaQuery && mediaQuery.matches ? 'light' : 'dark';
    }
    return mode === 'light' ? 'light' : 'dark';
  }

  function applyTheme(mode) {
    var pref = mode || getSavedPreference();
    var effective = resolveTheme(pref);
    var root = document.documentElement;

    root.classList.remove('dark', 'light');
    root.classList.add(effective);
    root.dataset.themePreference = pref;
    root.dataset.theme = effective;

    syncThemeButtons(pref);
    updateThemeBadge(pref, effective);
  }

  function syncThemeButtons(pref) {
    document.querySelectorAll('[data-theme-choice]').forEach(function (btn) {
      var choice = btn.getAttribute('data-theme-choice');
      var active = choice === pref;
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
      if (active) {
        btn.classList.add('is-active', 'bg-accent', 'text-on-accent');
        btn.classList.remove('text-muted', 'hover:text-ink');
      } else {
        btn.classList.remove('is-active', 'bg-accent', 'text-on-accent');
        btn.classList.add('text-muted', 'hover:text-ink');
      }
    });
  }

  function updateThemeBadge(pref, effective) {
    var iconMap = { dark: 'moon', light: 'sun', system: 'laptop' };
    var labelMap = { dark: 'Dark', light: 'Light', system: 'System (' + (effective === 'light' ? 'Light' : 'Dark') + ')' };
    document.querySelectorAll('[data-theme-label]').forEach(function (el) {
      el.textContent = labelMap[pref] || 'Dark';
    });
    document.querySelectorAll('[data-theme-active-icon]').forEach(function (el) {
      el.setAttribute('data-lucide', iconMap[pref] || 'moon');
    });
    refreshIcons();
  }

  function setTheme(mode) {
    if (mode !== 'dark' && mode !== 'light' && mode !== 'system') {
      return;
    }
    try {
      localStorage.setItem(STORAGE_KEY, mode);
    } catch (e) {
      // ignore storage errors
    }
    applyTheme(mode);
  }

  function refreshIcons() {
    if (window.lucide && typeof window.lucide.createIcons === 'function') {
      window.lucide.createIcons();
    }
  }

  window.CoreCraftrTheme = {
    get: getSavedPreference,
    set: setTheme,
    apply: applyTheme,
    refreshIcons: refreshIcons,
  };

  if (mediaQuery && mediaQuery.addEventListener) {
    mediaQuery.addEventListener('change', function () {
      if (getSavedPreference() === 'system') {
        applyTheme('system');
      }
    });
  }

  // Accessible Dropdown, Drawer, Modal, and Alert Interactive Primitives
  function closeAllMenus(exceptId) {
    document.querySelectorAll('[data-dropdown-panel]').forEach(function (panel) {
      if (exceptId && panel.id === exceptId) return;
      panel.classList.add('hidden');
      var trigger = document.querySelector('[data-dropdown-toggle="' + panel.id + '"]');
      if (trigger) trigger.setAttribute('aria-expanded', 'false');
    });
  }

  function openModal(modal) {
    if (!modal) return;
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    modal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('overflow-hidden');
    var focusTarget = modal.querySelector('input:not([type="hidden"]), button, select, textarea');
    if (focusTarget) focusTarget.focus();
  }

  function closeModal(modal) {
    if (!modal) return;
    modal.classList.add('hidden');
    modal.classList.remove('flex');
    modal.setAttribute('aria-hidden', 'true');
    if (!document.querySelector('[data-modal].flex') && !document.querySelector('[data-drawer].is-open')) {
      document.body.classList.remove('overflow-hidden');
    }
  }

  function openDrawer(drawer) {
    if (!drawer) return;
    drawer.classList.remove('hidden');
    drawer.classList.add('is-open');
    drawer.setAttribute('aria-hidden', 'false');
    document.body.classList.add('overflow-hidden');
  }

  function closeDrawer(drawer) {
    if (!drawer) return;
    drawer.classList.add('hidden');
    drawer.classList.remove('is-open');
    drawer.setAttribute('aria-hidden', 'true');
    if (!document.querySelector('[data-modal].flex') && !document.querySelector('[data-drawer].is-open')) {
      document.body.classList.remove('overflow-hidden');
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    applyTheme(getSavedPreference());
    refreshIcons();

    // Theme choice buttons
    document.addEventListener('click', function (e) {
      var themeBtn = e.target.closest('[data-theme-choice]');
      if (themeBtn) {
        setTheme(themeBtn.getAttribute('data-theme-choice'));
        return;
      }

      // Dropdown toggle
      var ddBtn = e.target.closest('[data-dropdown-toggle]');
      if (ddBtn) {
        e.preventDefault();
        e.stopPropagation();
        var targetId = ddBtn.getAttribute('data-dropdown-toggle');
        var panel = document.getElementById(targetId);
        if (!panel) return;
        var isHidden = panel.classList.contains('hidden');
        closeAllMenus(targetId);
        if (isHidden) {
          panel.classList.remove('hidden');
          ddBtn.setAttribute('aria-expanded', 'true');
        } else {
          panel.classList.add('hidden');
          ddBtn.setAttribute('aria-expanded', 'false');
        }
        return;
      }

      // Accordion / Collapse toggle
      var collapseBtn = e.target.closest('[data-collapse-toggle]');
      if (collapseBtn) {
        var cId = collapseBtn.getAttribute('data-collapse-toggle');
        var cEl = document.getElementById(cId);
        if (cEl) {
          var opening = cEl.classList.contains('hidden');
          cEl.classList.toggle('hidden');
          collapseBtn.setAttribute('aria-expanded', opening ? 'true' : 'false');
          var chev = collapseBtn.querySelector('[data-collapse-chevron]');
          if (chev) {
            chev.classList.toggle('rotate-180', opening);
          }
        }
        return;
      }

      // Modal open/close
      var modalOpen = e.target.closest('[data-modal-open]');
      if (modalOpen) {
        e.preventDefault();
        openModal(document.getElementById(modalOpen.getAttribute('data-modal-open')));
        return;
      }
      var modalClose = e.target.closest('[data-modal-close]');
      if (modalClose) {
        e.preventDefault();
        var mId = modalClose.getAttribute('data-modal-close');
        closeModal(mId ? document.getElementById(mId) : modalClose.closest('[data-modal]'));
        return;
      }
      if (e.target.hasAttribute && e.target.hasAttribute('data-modal')) {
        closeModal(e.target);
        return;
      }

      // Drawer open/close
      var drawerOpen = e.target.closest('[data-drawer-open]');
      if (drawerOpen) {
        e.preventDefault();
        openDrawer(document.getElementById(drawerOpen.getAttribute('data-drawer-open')));
        return;
      }
      var drawerClose = e.target.closest('[data-drawer-close]');
      if (drawerClose) {
        e.preventDefault();
        var dId = drawerClose.getAttribute('data-drawer-close');
        closeDrawer(dId ? document.getElementById(dId) : drawerClose.closest('[data-drawer]'));
        return;
      }
      if (e.target.hasAttribute && e.target.hasAttribute('data-drawer-backdrop')) {
        closeDrawer(e.target.closest('[data-drawer]'));
        return;
      }

      // Dismiss flash alert
      var dismissBtn = e.target.closest('[data-dismiss-alert]');
      if (dismissBtn) {
        var alertEl = dismissBtn.closest('[role="alert"]');
        if (alertEl) alertEl.remove();
        return;
      }

      // Outside click closes open dropdowns
      if (!e.target.closest('[data-dropdown-panel]')) {
        closeAllMenus(null);
      }
    });

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        closeAllMenus(null);
        document.querySelectorAll('[data-modal].flex').forEach(closeModal);
        document.querySelectorAll('[data-drawer].is-open').forEach(closeDrawer);
      }
    });
  });
})();
