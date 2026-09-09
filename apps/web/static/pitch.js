/* Progressive browsing; server owns search, constraints, claims and event persistence. */
const form = document.querySelector('#search-form');
let sequence = 0;
let controller;
async function search() {
  const query = document.querySelector('#query').value.trim();
  const category = document.querySelector('#category').value;
  const current = ++sequence;
  controller?.abort();
  controller = new AbortController();
  const results = document.querySelector('#results');
  const error = document.querySelector('#search-error');
  const summary = document.querySelector('#result-summary');
  error.hidden = true;
  results.setAttribute('aria-busy', 'true');
  summary.textContent = 'Finding your kind of different…';
  try {
    const params = new URLSearchParams({q: query, category});
    const response = await fetch('/api/search?' + params, {signal: controller.signal});
    if (!response.ok) throw new Error('Search is temporarily unavailable. Please try again.');
    const data = await response.json();
    if (current !== sequence) return;
    results.innerHTML = data.html || '<div class="empty-results"><h2>Nothing at that price.</h2><p>Try a wider budget or a different description.<br>This is a limited demo collection, not a stock check.</p></div>';
    summary.textContent = `${data.count} ${query ? 'results' : 'objects in the demo collection'}`;
    document.querySelector('#applied-filter').textContent = data.filter_label;
    document.querySelector('#clear-search').hidden = !query && !category;
    history.replaceState(null, '', '/catalog?' + params);
  } catch (failure) {
    if (failure.name !== 'AbortError' && current === sequence) {
      error.textContent = failure.message;
      error.hidden = false;
      summary.textContent = 'Search could not finish; previous results remain below.';
    }
  } finally { if (current === sequence) results.setAttribute('aria-busy', 'false'); }
}
if (form) {
  const query = document.querySelector('#query');
  const params = new URLSearchParams(location.search);
  document.querySelector('#category').value = params.get('category') || '';
  form.addEventListener('submit', event => { event.preventDefault(); search(); });
  document.querySelector('#category').addEventListener('change', search);
  document.querySelectorAll('[data-query]').forEach(chip => chip.addEventListener('click', () => { query.value = chip.dataset.query; search(); }));
  document.querySelector('#clear-search').addEventListener('click', () => { query.value = ''; document.querySelector('#category').value = ''; search(); });
  if (query.value || params.get('category')) search();
}
const dialog = document.querySelector('#demo-dialog');
document.querySelectorAll('.demo-action').forEach(button => button.addEventListener('click', async () => {
  document.querySelector('#dialog-title').textContent = button.dataset.kind === 'call' ? 'A direct line to the shop.' : 'From discovery to the door.';
  document.querySelector('#dialog-copy').textContent = 'This is a demo. No real business is contacted and no navigation is opened. In a live shop, this connects visitors with the business.';
  dialog.showModal();
  const params = new URLSearchParams({kind:button.dataset.kind, item_id:button.dataset.item, search_id:button.dataset.search});
  try {
    const response = await fetch('/api/demo-action?' + params);
    if (!response.ok) throw new Error();
  } catch (_) { document.querySelector('#dialog-copy').textContent += ' The demo interaction could not be recorded.'; }
}));
document.querySelectorAll('.dialog-close,.dialog-done').forEach(button => button.addEventListener('click', () => dialog.close()));
