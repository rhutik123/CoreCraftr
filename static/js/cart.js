function getCookie(name) {
  let cookieValue = null;
  if (document.cookie && document.cookie !== '') {
    const cookies = document.cookie.split(';');
    for (let i = 0; i < cookies.length; i++) {
      const cookie = cookies[i].trim();
      if (cookie.substring(0, name.length + 1) === (name + '=')) {
        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
        break;
      }
    }
  }
  return cookieValue;
}

function getCsrfToken() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  if (meta && meta.content && meta.content !== 'NOTPROVIDED') {
    return meta.content;
  }
  return getCookie('csrftoken');
}

function showToastMessage(message, isSuccess = true) {
  let container = document.getElementById('hh-toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'hh-toast-container';
    container.className = 'toast-container position-fixed bottom-0 end-0 p-3';
    container.style.zIndex = '1080';
    document.body.appendChild(container);
  }
  const toastEl = document.createElement('div');
  toastEl.className = `toast align-items-center text-bg-${isSuccess ? 'success' : 'danger'} border-0 show`;
  toastEl.setAttribute('role', 'alert');
  toastEl.innerHTML = `
    <div class="d-flex">
      <div class="toast-body">${message}</div>
      <button type="button" class="btn-close btn-close-white me-2 m-auto" aria-label="Close"></button>
    </div>`;
  toastEl.querySelector('button').addEventListener('click', () => toastEl.remove());
  container.appendChild(toastEl);
  setTimeout(() => toastEl.remove(), 3500);
}

async function updateCartItem(productId, action, reloadAfter = false) {
  try {
    const response = await fetch('/update_item/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken(),
      },
      body: JSON.stringify({ productID: productId, action: action }),
    });
    const data = await response.json();
    if (!response.ok || !data.success) {
      showToastMessage(data.message || 'Could not update cart.', false);
      return;
    }

    const badge = document.getElementById('cart-total');
    if (badge && typeof data.cart_total_items !== 'undefined') {
      badge.textContent = data.cart_total_items;
    }
    showToastMessage(data.message || 'Cart updated.', true);
    if (reloadAfter) {
      window.location.reload();
    }
  } catch (err) {
    showToastMessage('Network error updating cart.', false);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.update-cart').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const productId = btn.dataset.product;
      const action = btn.dataset.action || 'add';
      const reload = btn.dataset.reload === 'true';
      if (productId) {
        updateCartItem(productId, action, reload);
      }
    });
  });
});
