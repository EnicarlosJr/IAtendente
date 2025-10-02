// static/js/solicitacoes.js

// --- CSRF helpers ---
function getCookie(name) {
  const m = document.cookie.match('(^|;)\\s*' + name + '\\s*=\\s*([^;]+)');
  return m ? m.pop() : '';
}
const csrftoken = getCookie('csrftoken');

async function postForm(url, dataObj) {
  if (!url) throw new Error("URL ausente");
  const form = new URLSearchParams();
  Object.entries(dataObj || {}).forEach(([k, v]) => form.append(k, v ?? ''));
  const resp = await fetch(url, {
    method: 'POST',
    headers: {
      'X-CSRFToken': csrftoken,
      'X-Requested-With': 'XMLHttpRequest',
      'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
    },
    body: form.toString(),
  });
  if (!resp.ok) {
    const txt = await resp.text();
    throw new Error(`HTTP ${resp.status} - ${txt}`);
  }
  try { return await resp.json(); } catch { return {}; }
}

// --- Ações de Solicitação ---
async function openConfirm(btn) {
  try {
    const url = btn.dataset.confirmUrl;
    const servicoId = btn.dataset.servicoId || '';
    const precoCotado = btn.dataset.preco || '';

    const inicioAttr = btn.dataset.inicio || '';

    const payload = { servico_id: servicoId, preco_cotado: precoCotado };
    if (inicioAttr) payload.inicio = inicioAttr;

    btn.disabled = true; btn.textContent = "Confirmando...";
    await postForm(url, payload);
    location.reload();
  } catch (e) {
    alert('Erro ao confirmar: ' + e.message);
  } finally {
    btn.disabled = false; btn.textContent = "✅ Confirmar";
  }
}


async function openDeny(btn) {
  try {
    const url = btn.dataset.denyUrl;
    const motivo = prompt('Motivo da negativa (opcional):', '') || '';
    btn.disabled = true; btn.textContent = "Negando...";
    await postForm(url, { motivo });
    location.reload();
  } catch (e) {
    alert('Erro ao negar: ' + e.message);
  } finally {
    btn.disabled = false; btn.textContent = "❌ Negar";
  }
}

// --- Ações de Agendamento ---
async function submitFinalize(btn) {
  try {
    const url = btn.dataset.finalizeUrl;
    if (!confirm('Finalizar este atendimento?')) return;
    btn.disabled = true; btn.textContent = "Finalizando...";
    await postForm(url, {});
    location.reload();
  } catch (e) {
    alert('Erro ao finalizar: ' + e.message);
  } finally {
    btn.disabled = false; btn.textContent = "🏁 Finalizar";
  }
}

async function submitNoShow(btn) {
  try {
    const url = btn.dataset.noshowUrl;
    if (!confirm('Marcar como no-show?')) return;
    btn.disabled = true; btn.textContent = "Marcando...";
    await postForm(url, {});
    location.reload();
  } catch (e) {
    alert('Erro ao marcar no-show: ' + e.message);
  } finally {
    btn.disabled = false; btn.textContent = "🚫 No-show";
  }
}

// expõe no escopo global (para uso em onclick="")
window.openConfirm = openConfirm;
window.openDeny = openDeny;
window.submitFinalize = submitFinalize;
window.submitNoShow = submitNoShow;
