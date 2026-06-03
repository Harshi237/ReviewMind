/**
 * home.js – Landing page logic
 */

function setPackage(name) {
  document.getElementById('packageInput').value = name;
  document.getElementById('packageInput').focus();
}

function showStatus(msg, type = 'info') {
  const el = document.getElementById('statusArea');
  el.className = `status-area mt-3 status-${type}`;
  el.innerHTML = msg;
  el.classList.remove('d-none');
}

function hideStatus() {
  document.getElementById('statusArea').classList.add('d-none');
}

function setLoading(loading) {
  const btn     = document.getElementById('analyzeBtn');
  const btnText = document.getElementById('analyzeBtnText');
  const spinner = document.getElementById('analyzeBtnSpinner');
  btn.disabled     = loading;
  btnText.classList.toggle('d-none', loading);
  spinner.classList.toggle('d-none', !loading);
}

async function startAnalysis() {
  const pkg       = document.getElementById('packageInput').value.trim();
  const maxStr    = document.getElementById('reviewCount').value.trim();
  const max       = parseInt(maxStr) || 20;

  if (!pkg) {
    showStatus('<i class="bi bi-exclamation-circle me-2"></i>Please enter a package name.', 'error');
    return;
  }

  // Basic package name format check
  if (!/^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$/i.test(pkg)) {
    showStatus('<i class="bi bi-exclamation-circle me-2"></i>Invalid package name. Example: <strong>com.whatsapp</strong>', 'error');
    return;
  }

  setLoading(true);
  hideStatus();

  try {
    // Step 1 — fetch and analyse reviews
    showStatus('<i class="bi bi-hourglass-split me-2"></i>Fetching and analysing reviews… This may take a minute.', 'info');

    const result = await Api.analyzeApp(pkg, max);

    showStatus(
      `<i class="bi bi-check2-circle me-2"></i>
       Analysis complete! <strong>${result.totalAnalysed}</strong> of 
       <strong>${result.totalFetched}</strong> reviews analysed. 
       Redirecting to dashboard…`,
      'success'
    );

    // Store context for dashboard
    sessionStorage.setItem('rma_package', pkg);
    sessionStorage.setItem('rma_period', '30d');
    sessionStorage.setItem('rma_analyzeResult', JSON.stringify(result));

    // Redirect after brief pause
    setTimeout(() => {
      window.location.href = 'dashboard.html';
    }, 1200);

  } catch (err) {
    setLoading(false);
    showStatus(
      `<i class="bi bi-x-circle me-2"></i><strong>Error:</strong> ${err.message}`,
      'error'
    );
  }
}

// Allow Enter key to trigger analysis
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('packageInput').addEventListener('keydown', e => {
    if (e.key === 'Enter') startAnalysis();
  });
});
