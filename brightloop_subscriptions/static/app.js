/**
 * Brightloop Software - Client-Side Interactivity, Modals, Dynamic Actions, and Charts.
 */

// Helper: Show modal
function openModal(modalId) {
  const modal = document.getElementById(modalId);
  if (modal) {
    modal.classList.add("active");
  }
}

// Helper: Close modal
function closeModal(modalId) {
  const modal = document.getElementById(modalId);
  if (modal) {
    modal.classList.remove("active");
  }
}

// Helper: Alert notification
function showToast(message, type = "success") {
  let toastContainer = document.getElementById("toast-container");
  if (!toastContainer) {
    toastContainer = document.createElement("div");
    toastContainer.id = "toast-container";
    toastContainer.style.position = "fixed";
    toastContainer.style.bottom = "20px";
    toastContainer.style.right = "20px";
    toastContainer.style.zIndex = "9999";
    toastContainer.style.display = "flex";
    toastContainer.style.flexDirection = "column";
    toastContainer.style.gap = "10px";
    document.body.appendChild(toastContainer);
  }

  const toast = document.createElement("div");
  const bg = type === "success" ? "#10b981" : (type === "warning" ? "#f59e0b" : "#ef4444");
  toast.style.background = bg;
  toast.style.color = "#ffffff";
  toast.style.padding = "12px 20px";
  toast.style.borderRadius = "8px";
  toast.style.boxShadow = "0 4px 12px rgba(0,0,0,0.15)";
  toast.style.fontWeight = "600";
  toast.style.fontSize = "0.9rem";
  toast.style.transition = "all 0.3s ease";
  toast.innerText = message;

  toastContainer.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateY(10px)";
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// Quick Switch Demo Account
async function switchDemoAccount(email, password) {
  try {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password })
    });
    const data = await res.json();
    if (res.ok) {
      if (data.user.role === "customer") {
        window.location.href = "/portal";
      } else {
        window.location.href = "/dashboard";
      }
    } else {
      showToast(data.message || "Failed to switch account", "error");
    }
  } catch (err) {
    showToast("Error switching account: " + err.message, "error");
  }
}

// Handle Logout
async function handleLogout() {
  await fetch("/api/auth/logout", { method: "POST" });
  window.location.href = "/login";
}

// Password Validator helper for Signup / Reset forms
function setupPasswordValidator(inputId) {
  const input = document.getElementById(inputId);
  if (!input) return;

  const lenCheck = document.getElementById("rule-len");
  const upperCheck = document.getElementById("rule-upper");
  const lowerCheck = document.getElementById("rule-lower");
  const specCheck = document.getElementById("rule-spec");

  input.addEventListener("input", () => {
    const val = input.value;
    const hasLen = val.length > 8;
    const hasUpper = /[A-Z]/.test(val);
    const hasLower = /[a-z]/.test(val);
    const hasSpec = /[^A-Za-z0-9]/.test(val);

    const updateCheck = (el, valid) => {
      if (!el) return;
      el.style.color = valid ? "#10b981" : "#94a3b8";
      el.innerHTML = (valid ? "✓ " : "• ") + el.getAttribute("data-label");
    };

    updateCheck(lenCheck, hasLen);
    updateCheck(upperCheck, hasUpper);
    updateCheck(lowerCheck, hasLower);
    updateCheck(specCheck, hasSpec);
  });
}

// Subscription Actions
async function updateSubscriptionStatus(subId, newStatus) {
  if (!confirm(`Are you sure you want to transition this subscription to '${newStatus}'?`)) return;

  try {
    const res = await fetch(`/api/subscriptions/${subId}/status`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: newStatus })
    });
    const data = await res.json();
    if (res.ok) {
      showToast(data.message || `Subscription status updated to ${newStatus}`);
      setTimeout(() => window.location.reload(), 1000);
    } else {
      showToast(data.message || "Failed to update status", "error");
    }
  } catch (err) {
    showToast("Network error: " + err.message, "error");
  }
}

// Invoice Actions
async function confirmInvoice(invId) {
  try {
    const res = await fetch(`/api/invoices/${invId}/confirm`, { method: "POST" });
    const data = await res.json();
    if (res.ok) {
      showToast("Invoice confirmed!");
      setTimeout(() => window.location.reload(), 800);
    } else {
      showToast(data.message || "Failed to confirm invoice", "error");
    }
  } catch (err) {
    showToast("Error: " + err.message, "error");
  }
}

async function cancelInvoice(invId) {
  if (!confirm("Are you sure you want to cancel this invoice?")) return;
  try {
    const res = await fetch(`/api/invoices/${invId}/cancel`, { method: "POST" });
    const data = await res.json();
    if (res.ok) {
      showToast("Invoice marked as cancelled.");
      setTimeout(() => window.location.reload(), 800);
    } else {
      showToast(data.message || "Failed to cancel invoice", "error");
    }
  } catch (err) {
    showToast("Error: " + err.message, "error");
  }
}

async function sendInvoice(invId) {
  try {
    const res = await fetch(`/api/invoices/${invId}/send`, { method: "POST" });
    const data = await res.json();
    if (res.ok) {
      showToast("Invoice sent to customer email!");
      setTimeout(() => window.location.reload(), 800);
    } else {
      showToast(data.message || "Failed to send invoice", "error");
    }
  } catch (err) {
    showToast("Error: " + err.message, "error");
  }
}

async function chaseOverdueInvoice(invId, customerName, amount) {
  const note = prompt(`Enter chase reminder note for ${customerName} (Overdue: $${amount}):`, "Sent follow-up reminder for outstanding payment.");
  if (note === null) return;

  try {
    const res = await fetch(`/api/invoices/${invId}/chase`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ note })
    });
    const data = await res.json();
    if (res.ok) {
      showToast(`Chased! Reminder logged and notification dispatched to ${customerName}.`);
      setTimeout(() => window.location.reload(), 1200);
    } else {
      showToast(data.message || "Failed to log chase action", "error");
    }
  } catch (err) {
    showToast("Error: " + err.message, "error");
  }
}

// Payment Modal Opener
function openPaymentModal(invId, invNumber, balanceDue) {
  const modal = document.getElementById("recordPaymentModal");
  if (!modal) return;
  document.getElementById("pay-inv-id").value = invId;
  document.getElementById("pay-inv-number").innerText = invNumber;
  document.getElementById("pay-balance").innerText = "$" + Number(balanceDue).toFixed(2);
  document.getElementById("pay-amount").value = Number(balanceDue).toFixed(2);
  openModal("recordPaymentModal");
}

// Submit Payment
async function submitPaymentForm(event) {
  event.preventDefault();
  const invId = document.getElementById("pay-inv-id").value;
  const amount = parseFloat(document.getElementById("pay-amount").value);
  const method = document.getElementById("pay-method").value;
  const date = document.getElementById("pay-date").value;
  const note = document.getElementById("pay-note").value;

  try {
    const res = await fetch("/api/payments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        invoice_id: invId,
        amount: amount,
        payment_method: method,
        payment_date: date,
        reference_note: note
      })
    });
    const data = await res.json();
    if (res.ok) {
      showToast(`Payment of $${amount.toFixed(2)} recorded! Invoice is now ${data.payment.status}.`);
      closeModal("recordPaymentModal");
      setTimeout(() => window.location.reload(), 1000);
    } else {
      showToast(data.message || "Failed to record payment", "error");
    }
  } catch (err) {
    showToast("Error: " + err.message, "error");
  }
}

// Execute Billing Day
async function triggerBillingDayRun(asOfDate) {
  const btn = document.getElementById("run-billing-btn");
  if (btn) btn.disabled = true;

  try {
    const res = await fetch("/api/billing-day/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ billing_date: asOfDate })
    });
    const data = await res.json();
    if (res.ok) {
      showToast(`Billing Day Complete: ${data.result.invoices_generated} invoices generated!`);
      setTimeout(() => window.location.reload(), 1200);
    } else {
      showToast(data.message || "Billing Day failed", "error");
      if (btn) btn.disabled = false;
    }
  } catch (err) {
    showToast("Error: " + err.message, "error");
    if (btn) btn.disabled = false;
  }
}

// Customer Portal: Accept Quote
async function acceptQuotePortal(subId) {
  if (!confirm("Are you sure you want to accept this quotation and activate your subscription?")) return;
  try {
    const res = await fetch(`/api/quotes/${subId}/confirm`, { method: "POST" });
    const data = await res.json();
    if (res.ok) {
      showToast("Quotation accepted! Your subscription is now confirmed.");
      setTimeout(() => window.location.reload(), 1000);
    } else {
      showToast(data.message || "Failed to accept quote", "error");
    }
  } catch (err) {
    showToast("Error: " + err.message, "error");
  }
}



// Instant Client-Side Table Filter
function filterTable(query, tableId) {
  const table = document.getElementById(tableId);
  if (!table) return;
  const rows = table.querySelectorAll("tbody tr");
  const q = query.toLowerCase().trim();
  
  rows.forEach(row => {
    const text = row.innerText.toLowerCase();
    row.style.display = text.includes(q) ? "" : "none";
  });
}

// Quick Copy Helper
function copyToClipboard(text, msg = "Copied to clipboard!") {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(() => showToast(msg));
  } else {
    const input = document.createElement("input");
    input.value = text;
    document.body.appendChild(input);
    input.select();
    document.execCommand("copy");
    document.body.removeChild(input);
    showToast(msg);
  }
}
