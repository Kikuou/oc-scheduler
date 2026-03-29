// 終了時刻の自動計算
function calcEndTime() {
  const start = document.getElementById('start_time').value;
  const durSel = document.getElementById('duration_select').value;
  const durCustom = document.getElementById('duration_custom').value;
  const dur = durSel === 'custom' ? parseInt(durCustom) : parseInt(durSel);
  if (!start || isNaN(dur)) {
    document.getElementById('end_time_display').value = '';
    return null;
  }
  const [h, m] = start.split(':').map(Number);
  const total = h * 60 + m + dur;
  const endStr = `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`;
  document.getElementById('end_time_display').value = endStr;
  return endStr;
}

document.getElementById('start_time').addEventListener('change', () => {
  calcEndTime();
  checkVenueConflict();
  checkAllStaffConflicts();
});
document.getElementById('duration_select').addEventListener('change', function () {
  if (this.value === 'custom') {
    document.getElementById('duration_custom').classList.remove('d-none');
    document.getElementById('duration_custom').name = 'duration_min';
    document.querySelectorAll('[name="duration_min"]')[0].name = '_dur_sel';
  } else {
    document.getElementById('duration_custom').classList.add('d-none');
    document.getElementById('duration_custom').name = '_dur_cus';
    document.getElementById('duration_select').name = 'duration_min';
  }
  calcEndTime();
  checkVenueConflict();
  checkAllStaffConflicts();
});
document.getElementById('duration_custom').addEventListener('change', () => {
  calcEndTime();
  checkVenueConflict();
  checkAllStaffConflicts();
});
document.getElementById('venue_select').addEventListener('change', checkVenueConflict);

// 会場重複チェック
async function checkVenueConflict() {
  const venueId = document.getElementById('venue_select').value;
  const start = document.getElementById('start_time').value;
  const end = calcEndTime();
  const msg = document.getElementById('venue_conflict_msg');
  if (!venueId || !start || !end) { msg.textContent = ''; return; }

  const params = new URLSearchParams({
    occasion_id: OCCASION_ID,
    start_time: start,
    end_time: end,
    venue_id: venueId,
  });
  if (EVENT_ID) params.set('exclude_event_id', EVENT_ID);

  const res = await fetch('/api/conflict/venue?' + params);
  const data = await res.json();
  if (data.conflicts.length > 0) {
    msg.textContent = '⚠ 会場重複: ' + data.conflicts.map(c => `${c.start}-${c.end} ${c.title}`).join(', ');
  } else {
    msg.textContent = '';
  }
}

// 担当者重複チェック
async function checkStaffConflict(row) {
  const staffSel = row.querySelector('.staff-select');
  const staffId = staffSel.value;
  const start = document.getElementById('start_time').value;
  const end = calcEndTime();
  const msg = row.querySelector('.conflict-warning');
  if (!staffId || !start || !end) { msg.textContent = ''; return; }

  const params = new URLSearchParams({
    occasion_id: OCCASION_ID,
    start_time: start,
    end_time: end,
    staff_id: staffId,
  });
  if (EVENT_ID) params.set('exclude_event_id', EVENT_ID);

  const res = await fetch('/api/conflict/staff?' + params);
  const data = await res.json();
  if (data.conflicts.length > 0) {
    msg.textContent = '⚠ 担当重複: ' + data.conflicts.map(c => `${c.start}-${c.end} ${c.title}`).join(', ');
  } else {
    msg.textContent = '';
  }
}

function checkAllStaffConflicts() {
  document.querySelectorAll('.assignment-row').forEach(row => checkStaffConflict(row));
}

// 担当者行追加
function addAssignmentRow() {
  const tbody = document.getElementById('assignment_rows');
  const tr = document.createElement('tr');
  tr.className = 'assignment-row';
  tr.innerHTML = `
    <td>
      <select name="staff_id[]" class="form-select form-select-sm staff-select" required>
        ${STAFF_OPTIONS}
      </select>
      <div class="conflict-warning text-warning small mt-1"></div>
    </td>
    <td>
      <select name="role_id[]" class="form-select form-select-sm" required>
        ${ROLE_OPTIONS}
      </select>
    </td>
    <td><button type="button" class="btn btn-outline-danger btn-sm" onclick="removeRow(this)">削除</button></td>
  `;
  tbody.appendChild(tr);
  tr.querySelector('.staff-select').addEventListener('change', () => checkStaffConflict(tr));
}

function removeRow(btn) {
  btn.closest('tr').remove();
}

// 既存行にイベントを設定
document.querySelectorAll('.assignment-row').forEach(row => {
  row.querySelector('.staff-select').addEventListener('change', () => checkStaffConflict(row));
});

// テンプレート適用
function applyTemplate(title, duration) {
  document.getElementById('title_input').value = title;
  if (duration) {
    const sel = document.getElementById('duration_select');
    // 既存オプションに一致するものがあれば選択
    let found = false;
    for (const opt of sel.options) {
      if (parseInt(opt.value) === duration) {
        sel.value = opt.value;
        found = true;
        break;
      }
    }
    if (!found) {
      sel.value = 'custom';
      document.getElementById('duration_custom').classList.remove('d-none');
      document.getElementById('duration_custom').value = duration;
    }
    calcEndTime();
  }
}

// 初期計算
calcEndTime();
