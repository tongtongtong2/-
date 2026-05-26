(function () {
  function postJSON(url, body) {
    return fetch(url, {
      method: 'POST',
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined,
    }).then(async (r) => {
      const data = await r.json().catch(() => ({}));
      if (!r.ok || data.success === false) {
        throw new Error(data.error || '请求失败');
      }
      return data;
    });
  }

  function bind(id, url, busyText, successFn) {
    const btn = document.getElementById(id);
    if (!btn) return;
    btn.addEventListener('click', async () => {
      const original = btn.textContent;
      btn.disabled = true;
      btn.textContent = busyText;
      try {
        const data = await postJSON(url);
        if (successFn) successFn(data);
        setTimeout(() => window.location.reload(), 600);
      } catch (e) {
        alert('操作失败：' + e.message);
        btn.disabled = false;
        btn.textContent = original;
      }
    });
  }

  bind('btn-trigger-selection', '/api/trigger_selection', '选股中…', (d) => {
    console.log('已写入推荐：', d.inserted);
  });
  bind('btn-trigger-open-fill', '/api/trigger_open_fill', '回填中…', (d) => {
    console.log('filled:', d.filled, 'voided:', d.voided);
  });
  bind('btn-trigger-update', '/api/trigger_update', '更新中…', (d) => {
    console.log('updated:', d.updated, 'closed:', d.closed);
  });

  // ★ 自选观察池切换
  document.addEventListener('click', async (ev) => {
    const btn = ev.target.closest('.js-watch-toggle');
    if (!btn) return;
    const id = btn.dataset.recId;
    const watched = btn.dataset.watched === '1';
    const original = btn.innerHTML;
    btn.disabled = true;
    btn.textContent = '…';
    try {
      const data = await postJSON('/api/watch/' + id);
      if (data.is_watched) {
        btn.dataset.watched = '1';
        btn.classList.remove('btn-outline-secondary', 'btn-outline-danger');
        btn.classList.add('btn-warning');
        btn.innerHTML = original.includes('☆') ? '★ 已观察' : '★';
        const row = btn.closest('tr');
        if (row) row.classList.add('table-warning');
      } else {
        btn.dataset.watched = '0';
        btn.classList.remove('btn-warning');
        btn.classList.add('btn-outline-secondary');
        btn.innerHTML = '☆ 加入';
        const row = btn.closest('tr');
        if (row) row.classList.remove('table-warning');
        if (window.location.pathname === '/watchlist' && row) {
          row.style.transition = 'opacity .3s';
          row.style.opacity = '0';
          setTimeout(() => row.remove(), 300);
        }
      }
    } catch (e) {
      alert('操作失败：' + e.message);
      btn.innerHTML = original;
    } finally {
      btn.disabled = false;
    }
  });

  // ★ 成本价 inline 编辑 — 点击推荐价单元格即可修改
  // ★ 现价 inline 编辑 — 点击现价单元格即可修改（自动重算涨跌幅）
  document.addEventListener('click', async (ev) => {
    const cell = ev.target.closest('.js-editable-price, .js-editable-curprice');
    if (!cell) return;
    const recId = cell.dataset.recId;
    const current = cell.dataset.price;
    if (!recId || !current) return;
    const isCurPrice = cell.classList.contains('js-editable-curprice');

    const input = document.createElement('input');
    input.type = 'number';
    input.step = '0.01';
    input.value = current;
    input.className = 'form-control form-control-sm editable-price-input';

    const originalHTML = cell.innerHTML;
    cell.innerHTML = '';
    cell.appendChild(input);
    input.focus();
    input.select();

    const finish = async (save) => {
      if (save) {
        const newPrice = parseFloat(input.value);
        if (isNaN(newPrice) || newPrice <= 0) {
          cell.innerHTML = originalHTML;
          return;
        }
        if (Math.abs(newPrice - parseFloat(current)) < 0.001) {
          cell.innerHTML = originalHTML;
          return;
        }
        input.disabled = true;
        try {
          const url = isCurPrice
            ? '/api/rec/' + recId + '/curprice'
            : '/api/rec/' + recId + '/price';
          const data = await postJSON(url, { price: newPrice });
          cell.innerHTML = parseFloat(data.price).toFixed(2);
          cell.dataset.price = data.price;
          // 现价更新后刷新涨跌幅显示
          if (isCurPrice && data.change_percent !== undefined) {
            const row = cell.closest('tr');
            if (row) {
              const changeCell = row.querySelector('.js-change-cell');
              if (changeCell) {
                const pct = data.change_percent;
                changeCell.textContent = (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%';
                changeCell.className = changeCell.className.replace(/text-up|text-down/g, '')
                  + (pct > 0 ? ' text-up' : pct < 0 ? ' text-down' : '');
              }
            }
          }
        } catch (e) {
          alert('修改失败：' + e.message);
          cell.innerHTML = originalHTML;
        }
      } else {
        cell.innerHTML = originalHTML;
      }
    };

    input.addEventListener('blur', () => finish(true));
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); finish(true); }
      if (e.key === 'Escape') { e.preventDefault(); finish(false); }
    });
  });

  // ★ 持仓股数 inline 编辑 — 修改后自动刷新盈亏金额
  document.addEventListener('click', async (ev) => {
    const cell = ev.target.closest('.js-editable-shares');
    if (!cell) return;
    const recId = cell.dataset.recId;
    const current = cell.dataset.shares || '0';
    if (!recId) return;

    const input = document.createElement('input');
    input.type = 'number';
    input.step = '100';
    input.min = '0';
    input.value = current;
    input.className = 'form-control form-control-sm editable-price-input';
    input.style.width = '80px';

    const originalHTML = cell.innerHTML;
    cell.innerHTML = '';
    cell.appendChild(input);
    input.focus();
    input.select();

    const finish = async (save) => {
      if (save) {
        const newShares = parseInt(input.value) || 0;
        if (newShares < 0) { cell.innerHTML = originalHTML; return; }
        if (newShares === parseInt(current)) { cell.innerHTML = originalHTML; return; }
        input.disabled = true;
        try {
          const data = await postJSON('/api/rec/' + recId + '/shares', { shares: newShares });
          cell.innerHTML = newShares > 0 ? newShares.toLocaleString() : '<span class="text-muted">-</span>';
          cell.dataset.shares = newShares;
          // 更新盈亏金额
          const row = cell.closest('tr');
          if (row) {
            const pnlCell = row.querySelector('.js-pnl-cell');
            if (pnlCell && data.pnl_amount !== undefined) {
              const amt = data.pnl_amount;
              pnlCell.textContent = (amt >= 0 ? '+' : '') + amt.toFixed(2);
              pnlCell.className = pnlCell.className.replace(/text-up|text-down/g, '')
                + (amt > 0 ? ' text-up' : amt < 0 ? ' text-down' : '');
            }
          }
        } catch (e) {
          alert('修改失败：' + e.message);
          cell.innerHTML = originalHTML;
        }
      } else {
        cell.innerHTML = originalHTML;
      }
    };

    input.addEventListener('blur', () => finish(true));
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); finish(true); }
      if (e.key === 'Escape') { e.preventDefault(); finish(false); }
    });
  });
})();
