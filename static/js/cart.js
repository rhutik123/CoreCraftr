function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop().split(';').shift();
  return null;
}

function getCsrfToken() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  if (meta && meta.content && meta.content !== 'NOTPROVIDED') {
    return meta.content;
  }
  return getCookie('csrftoken');
}

function showToastMessage(message, isError = false) {
  let stack = document.getElementById('cc-toast-stack');
  if (!stack) {
    stack = document.createElement('div');
    stack.id = 'cc-toast-stack';
    stack.className = 'cc-toast-stack';
    stack.setAttribute('aria-live', 'polite');
    document.body.appendChild(stack);
  }

  const toastEl = document.createElement('div');
  toastEl.className = 'cc-toast ' + (isError ? 'cc-alert-danger' : 'cc-alert-success');
  toastEl.setAttribute('role', 'status');

  const content = document.createElement('div');
  content.className = 'flex items-center gap-2.5';

  const icon = document.createElement('i');
  icon.setAttribute('data-lucide', isError ? 'octagon-alert' : 'circle-check');
  icon.className = 'w-4 h-4 shrink-0';

  const msgSpan = document.createElement('span');
  msgSpan.textContent = message;

  content.appendChild(icon);
  content.appendChild(msgSpan);

  const closeBtn = document.createElement('button');
  closeBtn.type = 'button';
  closeBtn.className = 'p-1 rounded-lg opacity-70 hover:opacity-100 transition-opacity cursor-pointer';
  closeBtn.setAttribute('aria-label', 'Dismiss notification');
  closeBtn.innerHTML = '<i data-lucide="x" class="w-4 h-4"></i>';
  closeBtn.addEventListener('click', () => toastEl.remove());

  toastEl.appendChild(content);
  toastEl.appendChild(closeBtn);
  stack.appendChild(toastEl);

  if (window.lucide && typeof window.lucide.createIcons === 'function') {
    window.lucide.createIcons();
  }

  setTimeout(() => {
    if (toastEl.parentElement) toastEl.remove();
  }, 3500);
}

async function updateCartItem(productId, action, shouldReload = false, quantity = null) {
  try {
    const payload = { product_id: productId, action: action };
    if (quantity !== null && quantity !== undefined && quantity !== '') {
      payload.quantity = quantity;
    }

    const response = await fetch('/update_item/', {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
        'X-CSRFToken': getCsrfToken(),
      },
      body: JSON.stringify(payload),
    });

    let data = {};
    try {
      data = await response.json();
    } catch (_) {
      data = {};
    }

    if (!response.ok || data.success === false || data.error) {
      showToastMessage(data.message || data.error || 'Could not update cart.', true);
      return;
    }

    const totalCount = data.cart_total_items ?? data.cart_total ?? 0;
    document.querySelectorAll('#cart-total').forEach((badge) => {
      badge.textContent = String(totalCount);
    });

    if (shouldReload) {
      window.location.reload();
    } else {
      showToastMessage(data.message || 'Cart updated.');
    }
  } catch (err) {
    showToastMessage('Network error updating cart.', true);
  }
}

document.addEventListener('click', (e) => {
  const btn = e.target.closest('.update-cart');
  if (!btn || btn.disabled || btn.getAttribute('aria-disabled') === 'true') {
    return;
  }
  if (btn.dataset.cartPending === 'true') {
    return;
  }
  e.preventDefault();
  const productId = btn.dataset.product;
  const action = btn.dataset.action || 'add';
  const shouldReload = btn.dataset.reload === 'true';
  const quantity = btn.dataset.quantity || null;
  if (!productId) {
    return;
  }
  btn.dataset.cartPending = 'true';
  updateCartItem(productId, action, shouldReload, quantity).finally(() => {
    delete btn.dataset.cartPending;
  });
});
