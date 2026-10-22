const events = document.querySelector('#events');
document.querySelector('#sample').addEventListener('click', async () => {
  const output = document.querySelector('#sample-result');
  try {
    const response = await fetch('sample-report.json', {credentials:'omit', signal:AbortSignal.timeout(10000)});
    if (!response.ok) throw new Error(`Sample returned HTTP ${response.status}`);
    const report = await response.json();
    output.textContent = `OFFLINE FIXTURES · ${report.count} repositories · complete: ${report.complete}\n\n${report.repositories.map(row => `${row.repository} | ${row.language} | ${row.license}`).join('\n')}`;
  } catch (error) {
    output.textContent = error.message;
  }
});
document.querySelector('#simulate').addEventListener('click', () => {
  events.replaceChildren();
  for (const message of ['Secondary A → LAB-001 queued', 'Secondary B → LAB-001 validated', 'Secondary A → LAB-001 completed']) {
    const item = document.createElement('li');
    item.textContent = message;
    events.append(item);
  }
});
const result = document.querySelector('#result');
let requests = 0;
const cache = new Map();
document.querySelector('#audit').addEventListener('submit', async (event) => {
  event.preventDefault();
  const owner = document.querySelector('#owner').value.trim();
  const repo = document.querySelector('#repo').value.trim();
  if (!/^[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?$/i.test(owner) || !/^[a-z0-9_.-]{1,100}$/i.test(repo) || ['.', '..'].includes(repo)) {
    result.textContent = 'Enter a valid owner and repository name.';
    return;
  }
  if (owner.toLowerCase() === 'brunnojob') {
    result.textContent = 'Blocked: the main account is excluded from automation targets.';
    return;
  }
  if (requests >= 10) {
    result.textContent = 'Session request budget exhausted. No request sent.';
    return;
  }
  const target = `${owner}/${repo}`;
  const previous = cache.get(target);
  const headers = {Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'};
  if (previous?.etag) headers['If-None-Match'] = previous.etag;
  const button = document.querySelector('#submit');
  button.disabled = true;
  result.textContent = 'Inspecting public metadata…';
  requests += 1;
  try {
    const response = await fetch(`https://api.github.com/repos/${target}`, {method:'GET', headers, credentials:'omit', redirect:'error', signal:AbortSignal.timeout(15000)});
    if (response.status === 403 || response.status === 429) throw new Error('API limit or access refusal. Stopped without retry.');
    if (!response.ok && response.status !== 304) throw new Error(`GitHub returned HTTP ${response.status}.`);
    const data = response.status === 304 && previous ? previous.data : await response.json();
    if (data.full_name?.toLowerCase() !== target.toLowerCase()) throw new Error('Repository identity mismatch.');
    cache.set(target, {etag:response.headers.get('ETag'), data});
    const checks = [['Description', Boolean(data.description)], ['License', Boolean(data.license)], ['Issues enabled', Boolean(data.has_issues)], ['Active', !data.archived]];
    result.textContent = `${data.full_name}\n${checks.map(([label, passed]) => `${passed ? 'PASS' : 'CHECK'}  ${label}`).join('\n')}\n\nRequests: ${requests}/10`;
  } catch (error) {
    result.textContent = `${error.message}\nNo automatic retry. Requests: ${requests}/10`;
  } finally {
    button.disabled = false;
  }
});
