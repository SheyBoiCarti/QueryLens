import { test, expect, Page } from '@playwright/test';

const connectionString = process.env.QUERYLENS_E2E_DATABASE_URL;
const prefix = `Playwright ${Date.now()}`;
const createdIds = new Set<string>();
const headers = { 'X-QueryLens-Client': 'web' };

async function navigate(page: Page, name: string) {
  await page.getByRole('button', { name, exact: true }).click();
}

async function addConnection(page: Page, name: string) {
  await navigate(page, 'Connections');
  await page.getByRole('button', { name: 'Add connection', exact: true }).click();
  await page.getByLabel('Connection link', { exact: true }).fill(connectionString!);
  await page.getByRole('button', { name: 'Use connection link' }).click();
  await page.getByLabel('Connection name', { exact: true }).fill(name);
  const pending = page.waitForResponse(r => r.url().endsWith('/api/v1/connections') && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Save connection', exact: true }).click();
  const response = await pending;
  expect(response.status()).toBe(201);
  const connection = await response.json();
  createdIds.add(connection.id);
  expect(Object.keys(connection.allowed_tables).length).toBeGreaterThan(0);
  await expect(page.getByText(name, { exact: true })).toBeVisible();
  return connection;
}

async function runSql(page: Page, connectionId: string, sql: string) {
  const response = await page.request.post('/api/v1/queries/sql', { headers, data: { connection_id: connectionId, sql } });
  expect(response.status()).toBe(202);
  const accepted = await response.json();
  await expect.poll(async () => {
    const result = await page.request.get(`/api/v1/queries/${accepted.query_id}`);
    return (await result.json()).status;
  }).toBe('completed');
  return accepted.query_id as string;
}

async function waitForCompleted(page: Page, queryId: string) {
  let run: Record<string, any> = {};
  await expect.poll(async () => {
    run = await (await page.request.get(`/api/v1/queries/${queryId}`)).json();
    return run.status;
  }, { timeout: 45_000 }).toBe('completed');
  return run;
}

async function submitQuestion(page: Page, question: string, followUp = false) {
  const pending = page.waitForResponse(r => r.url().endsWith('/api/v1/queries') && r.request().method() === 'POST');
  await page.getByRole('textbox', { name: followUp ? 'Ask a follow-up question' : 'Ask a natural-language question', exact: true }).fill(question);
  await page.getByRole('button', { name: followUp ? 'Ask follow-up' : 'Run query', exact: true }).click();
  const response = await pending;
  expect(response.status()).toBe(202);
  const { query_id } = await response.json();
  return waitForCompleted(page, query_id);
}

async function inspect(page: Page, queryId: string) {
  await navigate(page, 'History');
  const row = page.getByRole('row').filter({ has: page.getByRole('button', { name: `Delete query ${queryId}`, exact: true }) });
  await row.getByRole('button', { name: 'Inspect', exact: true }).click();
  await page.locator('summary').filter({ hasText: /^Executed SQL$/ }).click();
  await expect(page.getByRole('button', { name: 'Edit SQL', exact: true })).toBeVisible();
}

test('live connection, schema, analytics, saved questions and replacement lifecycle', async ({ page }) => {
  test.skip(!connectionString, 'Set QUERYLENS_E2E_DATABASE_URL to a read-only PostgreSQL test source.');
  test.setTimeout(240_000);
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('dialog', dialog => dialog.accept());
  await page.goto('/');
  try {
    const connection = await addConnection(page, `${prefix} primary`);
    const source = page.locator('.connection-row').filter({ hasText: `${prefix} primary` });
    await source.getByRole('button', { name: 'Test connection', exact: true }).click();
    await expect(source.getByText(/Connected: PostgreSQL/)).toBeVisible();
    await source.getByRole('button', { name: 'Edit', exact: true }).click();
    await page.getByLabel('Connection name', { exact: true }).fill(`${prefix} renamed`);
    await page.getByRole('button', { name: 'Save connection', exact: true }).click();
    await expect(page.getByText(`${prefix} renamed`, { exact: true })).toBeVisible();
    const coldReads = await Promise.all(['schema', 'labels', 'metrics'].map(path =>
      page.request.get(`/api/v1/connections/${connection.id}/${path}`)));
    expect(coldReads.map(response => response.status())).toEqual([200, 200, 200]);

    const table = Object.keys(connection.allowed_tables).find(name => name.endsWith('.customers'))!;
    expect(table).toBeTruthy();
    await page.locator('.connection-row').filter({ hasText: `${prefix} renamed` }).getByRole('button', { name: 'Select tables' }).click();
    await expect(page.getByRole('button', { name: 'Save selections', exact: true })).toBeEnabled();
    await page.getByRole('button', { name: 'Save selections', exact: true }).click();
    await expect(page.getByText(`${prefix} renamed`, { exact: true })).toBeVisible();
    await navigate(page, 'Explore schema');
    await page.getByLabel('Schema database').selectOption(connection.id);
    await expect(page.getByRole('button', { name: table, exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Refresh schema', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Refresh schema', exact: true })).toBeEnabled();
    await expect(page.getByRole('button', { name: 'Save labels', exact: true })).toBeEnabled();
    await page.getByLabel(`${table} display name`, { exact: true }).fill('QA Customers');
    await page.getByRole('button', { name: 'Save labels', exact: true }).click();
    await expect(page.getByRole('button', { name: `QA Customers ${table}`, exact: true })).toBeVisible();

    await page.getByRole('button', { name: 'Define metric', exact: true }).click();
    await page.getByLabel('Metric key', { exact: true }).fill('qa_customer_count');
    await page.getByLabel('Display name', { exact: true }).fill('QA customer count');
    await page.getByLabel('Table', { exact: true }).selectOption(table);
    await page.getByLabel('Measure column', { exact: true }).selectOption('id');
    await page.getByLabel('Aggregation', { exact: true }).selectOption('count');
    await page.getByRole('button', { name: 'Save metric', exact: true }).click();
    await page.getByRole('button', { name: 'Edit QA customer count', exact: true }).click();
    await page.getByLabel('Units', { exact: true }).fill('customers');
    await page.getByRole('button', { name: 'Save metric', exact: true }).click();
    await expect(page.getByText(/customers · version 2/)).toBeVisible();
    await page.getByRole('button', { name: 'Delete metric', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Edit QA customer count', exact: true })).toHaveCount(0);

    const queryId = await runSql(page, connection.id, `SELECT id, name FROM ${table} ORDER BY id LIMIT 3`);
    await inspect(page, queryId);
    const download = page.waitForEvent('download');
    await page.getByRole('link', { name: 'Download CSV', exact: true }).click();
    expect((await download).suggestedFilename()).toMatch(/\.csv$/);
    await page.getByRole('button', { name: 'Edit SQL', exact: true }).click();
    await page.getByRole('textbox', { name: 'SQL Editor', exact: true }).fill(`SELECT count(*) AS total FROM ${table}`);
    const editedResponse = page.waitForResponse(r => r.url().endsWith('/queries/sql') && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Run edited SQL', exact: true }).click();
    const edited = await (await editedResponse).json();
    await waitForCompleted(page, edited.query_id);
    await expect(page.getByRole('link', { name: 'Download CSV', exact: true })).toHaveAttribute('href', `/api/v1/queries/${edited.query_id}/export?format=csv`);
    await page.getByRole('button', { name: 'Save as question', exact: true }).click();
    await page.getByLabel('Title', { exact: false }).fill(`${prefix} saved count`);
    await page.getByRole('button', { name: 'Save question', exact: true }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await page.getByRole('button', { name: 'Browse saved questions', exact: true }).click();
    await page.getByRole('button', { name: 'View or run', exact: true }).click();
    const savedResponse = page.waitForResponse(r => /\/saved-questions\/[^/]+\/run$/.test(r.url()) && r.request().method() === 'POST');
    await page.getByRole('button', { name: /^(Run Saved Question|Run with Filters)$/ }).click();
    const saved = await (await savedResponse).json();
    await waitForCompleted(page, saved.query_id);
    await expect(page.getByRole('link', { name: 'Download CSV', exact: true })).toHaveAttribute('href', `/api/v1/queries/${saved.query_id}/export?format=csv`);
    await page.getByRole('button', { name: 'Show diagnostics', exact: true }).click();
    await expect(page.getByText('Execution attempts', { exact: false })).toBeVisible();

    // Keep a remembered schema selection and active run while deleting the source.
    await navigate(page, 'Explore schema');
    await page.getByLabel('Schema database').selectOption(connection.id);
    await navigate(page, 'Connections');
    await page.locator('.connection-row').filter({ hasText: `${prefix} renamed` }).getByRole('button', { name: 'Delete', exact: true }).click();
    await expect(page.getByText(`${prefix} renamed`, { exact: true })).toHaveCount(0);
    const replacement = await addConnection(page, `${prefix} replacement`);
    await navigate(page, 'Explore schema');
    await expect(page.getByLabel('Schema database')).not.toHaveValue(connection.id);
    await page.getByLabel('Schema database').selectOption(replacement.id);
    await expect(page.getByRole('button', { name: table, exact: true })).toBeVisible();
    await navigate(page, 'History');
    await expect(page.getByRole('heading', { name: 'History' })).toBeVisible();
    await expect(page.getByRole('alert')).toHaveCount(0);
    await navigate(page, 'Ask data');
    await expect(page.getByLabel('Database source')).not.toHaveValue(connection.id);
    await expect(page.getByLabel('Database source')).toBeEnabled();
    await expect(page.getByRole('alert')).toHaveCount(0);
    const newRun = await runSql(page, replacement.id, `SELECT count(*) AS total FROM ${table}`);
    await inspect(page, newRun);
    await expect(page.getByLabel('Database source')).toHaveValue(replacement.id);
    expect(errors).toEqual([]);
  } finally {
    for (const id of createdIds) await page.request.delete(`/api/v1/connections/${id}`, { headers });
  }
});

test('live LLM questions, follow-ups, charts and saved question variations', async ({ page }) => {
  test.skip(!connectionString || process.env.QUERYLENS_E2E_LLM !== 'true', 'Configure an LLM on the API and set QUERYLENS_E2E_LLM=true.');
  test.setTimeout(240_000);
  page.on('dialog', dialog => dialog.accept());
  await page.goto('/');
  const connection = await addConnection(page, `${prefix} LLM`);
  try {
    const table = Object.keys(connection.allowed_tables).find(name => name.endsWith('.customers'))!;
    const baselineId = await runSql(page, connection.id, `SELECT count(*) AS total FROM ${table}`);
    const baseline = await waitForCompleted(page, baselineId);
    await navigate(page, 'Ask data');
    await page.getByLabel('Database source').selectOption(connection.id);
    const count = await submitQuestion(page, 'How many customers are there? Return a single total customer count.');
    expect(count.rows).toHaveLength(1);
    expect(String(Object.values(count.rows[0])[0])).toBe(String(baseline.rows[0].total));
    await expect(page.getByRole('button', { name: 'Save as question', exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Save as question', exact: true }).click();
    await page.getByLabel('Title', { exact: false }).fill(`${prefix} LLM customer count`);
    await page.getByRole('button', { name: 'Save question', exact: true }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);

    const filteredBaselineId = await runSql(page, connection.id, `SELECT count(*) AS total FROM ${table} WHERE tier = 'enterprise'`);
    const filteredBaseline = await waitForCompleted(page, filteredBaselineId);
    const followUp = await submitQuestion(page, "Only count customers whose tier is 'enterprise'.", true);
    expect(followUp.origin).toBe('follow_up');
    expect(followUp.parent_query_id).toBe(count.query_id);
    expect(String(Object.values(followUp.rows[0])[0])).toBe(String(filteredBaseline.rows[0].total));
    await page.getByRole('button', { name: 'Start new question', exact: true }).click();
    const grouped = await submitQuestion(page, 'Show the number of orders for each order status, ordered by status.');
    expect(grouped.rows.length).toBeGreaterThan(0);
    await expect(page.getByRole('tab', { name: 'Table', exact: true })).toBeVisible();
    await page.getByRole('tab', { name: 'Table', exact: true }).click();
    await expect(page.getByRole('table')).toBeVisible();

    await page.getByRole('button', { name: 'Browse saved questions', exact: true }).click();
    await page.getByRole('button', { name: 'View or run', exact: true }).click();
    await page.getByRole('button', { name: 'Edit definition', exact: true }).click();
    await page.getByLabel('Saved question title').fill(`${prefix} revised count`);
    await page.getByRole('button', { name: 'Save definition', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Edit definition', exact: true })).toBeVisible();
    await page.getByLabel('Variation request').fill("Only count customers whose tier is 'enterprise'.");
    const variationResponse = page.waitForResponse(r => r.url().endsWith('/api/v1/queries') && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Ask for a variation', exact: true }).click();
    const accepted = await (await variationResponse).json();
    const variation = await waitForCompleted(page, accepted.query_id);
    expect(String(Object.values(variation.rows[0])[0])).toBe(String(filteredBaseline.rows[0].total));
    await expect(page.getByRole('alert')).toHaveCount(0);
  } finally {
    await page.request.delete(`/api/v1/connections/${connection.id}`, { headers });
  }
});

test('empty results, rejected SQL, cancellation, history deletion and revoked table access', async ({ page }) => {
  test.skip(!connectionString, 'Set QUERYLENS_E2E_DATABASE_URL.');
  page.on('dialog', dialog => dialog.accept());
  await page.goto('/');
  const connection = await addConnection(page, `${prefix} recovery`);
  try {
    const table = Object.keys(connection.allowed_tables).find(name => name.endsWith('.customers'))!;
    const emptyId = await runSql(page, connection.id, `SELECT id FROM ${table} WHERE 1 = 0`);
    await inspect(page, emptyId);
    await expect(page.getByText('Query completed with 0 rows returned.', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Edit SQL', exact: true }).click();
    await page.getByRole('textbox', { name: 'SQL Editor', exact: true }).fill('SELECT id FROM nonexistent_qa_table');
    const rejectedResponse = page.waitForResponse(r => r.url().endsWith('/queries/sql') && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Run edited SQL', exact: true }).click();
    const rejected = await (await rejectedResponse).json();
    await expect.poll(async () => (await (await page.request.get(`/api/v1/queries/${rejected.query_id}`)).json()).status).toBe('rejected');
    await page.getByRole('button', { name: 'View previous successful answer', exact: true }).click();
    await expect(page.getByText('Query completed with 0 rows returned.', { exact: true })).toBeVisible();

    const accepted = await (await page.request.post('/api/v1/queries/sql', {
      headers, data: { connection_id: connection.id, sql: `SELECT id FROM ${table}` },
    })).json();
    const cancelled = await page.request.post(`/api/v1/queries/${accepted.query_id}/cancel`, { headers });
    expect(cancelled.status()).toBe(200);
    expect((await cancelled.json()).status).toBe('cancelled');
    await navigate(page, 'History');
    const cancelledRow = page.getByRole('row').filter({ has: page.getByRole('button', { name: `Delete query ${accepted.query_id}`, exact: true }) });
    await cancelledRow.getByRole('button', { name: 'Inspect', exact: true }).click();
    await expect(page.getByText('Query was cancelled.', { exact: true })).toBeVisible();
    await expect(page.getByLabel('Database source')).toBeEnabled();
    await navigate(page, 'History');
    await page.getByRole('button', { name: `Delete query ${accepted.query_id}`, exact: true }).click();
    await expect(page.getByRole('button', { name: `Delete query ${accepted.query_id}`, exact: true })).toHaveCount(0);

    await navigate(page, 'Connections');
    await page.locator('.connection-row').filter({ hasText: `${prefix} recovery` }).getByRole('button', { name: 'Select tables' }).click();
    for (const key of Object.keys(connection.allowed_tables)) await page.getByLabel(key, { exact: true }).uncheck();
    await page.getByRole('button', { name: 'Save selections', exact: true }).click();
    await expect(page.getByText(`${prefix} recovery`, { exact: true })).toBeVisible();
    await navigate(page, 'Explore schema');
    await page.getByLabel('Schema database').selectOption(connection.id);
    await expect(page.getByText('Select allowed tables and columns in Connections to enable analytics.')).toBeVisible();
    const revokedRun = await page.request.get(`/api/v1/queries/${emptyId}`);
    expect((await revokedRun.json()).results_available).toBe(false);
    expect((await page.request.get(`/api/v1/queries/${emptyId}/export`)).status()).toBe(410);
    await navigate(page, 'History');
    await expect(page.getByRole('alert')).toHaveCount(0);
  } finally {
    await page.request.delete(`/api/v1/connections/${connection.id}`, { headers });
  }
});
