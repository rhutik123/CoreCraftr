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

async function updateCartItem(productId, action, shouldReload = false) {
  try {
    const response = await fetch('/update_item/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken(),
      },
      body: JSON.stringify({ productId: productId, action: action }),
    });
    const data = await response.json();
    if (!response.ok || data.error) {
      showToastMessage(data.error || 'Could not update cart.', true);
      return;
    }

    document.querySelectorAll('#cart-total').forEach((badge) => {
      badge.textContent = data.cart_total ?? '0';
    });

    if (shouldReload) {
      window.location.reload();
    } else {
      showToastMessage('Cart updated.');
    }
  } catch (err) {
    showToastMessage('Network error updating cart.', true);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.update-cart').forEach((btn) => {
    btn.addEventListener('click', function (e) {
      e.preventDefault();
      const productId = this.dataset.product;
      const action = this.dataset.action || 'add';
      const shouldReload = this.dataset.reload === 'true';
      if (!productId) return;
      updateCartItem(productId, action, shouldReload);
    });
  });
});
