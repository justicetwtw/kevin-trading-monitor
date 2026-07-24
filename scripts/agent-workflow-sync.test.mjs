import assert from 'node:assert/strict';
import test from 'node:test';

import {
  compareContracts,
  fetchRemoteContract,
  normalizeText,
  parseContract,
  sha256,
} from './agent-workflow-sync.mjs';

const CONTRACT = `<!-- shared-agent-workflow-contract:v1 -->
\`\`\`json
{
  "schema": "shared-agent-workflow-contract:v1",
  "contract_version": "2026-07-24.1",
  "authority": {
    "repository": "justicetwtw/jin-yi-yang-bot",
    "ref": "main",
    "path": "docs/shared-agent-workflow-contract.md"
  },
  "consumers": ["justicetwtw/jin-yi-yang-bot", "justicetwtw/kevin-trading-monitor"]
}
\`\`\`

# Contract
`;

test('normalizes CRLF and final newline deterministically', () => {
  assert.equal(normalizeText('a\r\nb'), 'a\nb\n');
  assert.equal(sha256('a\r\nb'), sha256('a\nb\n'));
});

test('parses valid contract metadata and digest', () => {
  const parsed = parseContract(CONTRACT);
  assert.equal(parsed.metadata.contract_version, '2026-07-24.1');
  assert.equal(parsed.metadata.authority.repository, 'justicetwtw/jin-yi-yang-bot');
  assert.match(parsed.digest, /^[a-f0-9]{64}$/);
});

test('rejects missing marker and invalid version', () => {
  assert.throws(() => parseContract(CONTRACT.replace('<!-- shared-agent-workflow-contract:v1 -->', '')), /contract_marker_missing/);
  assert.throws(() => parseContract(CONTRACT.replace('2026-07-24.1', 'latest')), /contract_version_invalid/);
});

test('compares exact normalized bytes', () => {
  const first = parseContract(CONTRACT);
  const same = parseContract(CONTRACT.replace(/\n/g, '\r\n'));
  const changed = parseContract(CONTRACT.replace('# Contract', '# Changed'));
  assert.equal(compareContracts(first, same).status, 'synced');
  assert.equal(compareContracts(first, changed).status, 'drift');
});

test('fetches and validates a remote contract through injected fetch', async () => {
  const fakeFetch = async () => ({ ok: true, status: 200, text: async () => CONTRACT });
  const parsed = await fetchRemoteContract(
    'justicetwtw/jin-yi-yang-bot',
    'main',
    'docs/shared-agent-workflow-contract.md',
    fakeFetch,
  );
  assert.equal(parsed.metadata.schema, 'shared-agent-workflow-contract:v1');
});
