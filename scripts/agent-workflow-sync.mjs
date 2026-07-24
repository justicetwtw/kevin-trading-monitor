#!/usr/bin/env node

import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const DEFAULT_CONFIG = 'config/agent-workflow-sync.json';
const CONTRACT_MARKER = '<!-- shared-agent-workflow-contract:v1 -->';

export function normalizeText(value) {
  const normalized = String(value).replace(/\r\n?/g, '\n');
  return normalized.endsWith('\n') ? normalized : `${normalized}\n`;
}

export function sha256(value) {
  return crypto.createHash('sha256').update(normalizeText(value), 'utf8').digest('hex');
}

export function parseContract(value) {
  const text = normalizeText(value);
  if (!text.includes(CONTRACT_MARKER)) {
    throw new Error('contract_marker_missing');
  }
  const match = text.match(/```json\s*([\s\S]*?)\s*```/);
  if (!match) throw new Error('contract_metadata_missing');
  let metadata;
  try {
    metadata = JSON.parse(match[1]);
  } catch {
    throw new Error('contract_metadata_invalid_json');
  }
  if (metadata.schema !== 'shared-agent-workflow-contract:v1') {
    throw new Error('contract_schema_invalid');
  }
  if (!/^[0-9]{4}-[0-9]{2}-[0-9]{2}\.[0-9]+$/.test(String(metadata.contract_version || ''))) {
    throw new Error('contract_version_invalid');
  }
  const authority = metadata.authority || {};
  if (!authority.repository || !authority.ref || !authority.path) {
    throw new Error('contract_authority_invalid');
  }
  return { text, metadata, digest: sha256(text) };
}

export async function readConfig(configPath = DEFAULT_CONFIG) {
  const raw = await fs.readFile(configPath, 'utf8');
  const config = JSON.parse(raw);
  if (config.schema !== 'agent-workflow-sync-config:v1') throw new Error('config_schema_invalid');
  if (!['source', 'consumer'].includes(config.role)) throw new Error('config_role_invalid');
  for (const key of ['repository', 'default_ref', 'contract_path', 'source_repository', 'source_ref', 'peer_repository', 'peer_ref']) {
    if (!config[key]) throw new Error(`config_missing_${key}`);
  }
  if (!Array.isArray(config.source_policy_paths)) config.source_policy_paths = [];
  return config;
}

function rawUrl(repository, ref, relativePath) {
  const encodedPath = relativePath.split('/').map(encodeURIComponent).join('/');
  return `https://raw.githubusercontent.com/${repository}/${encodeURIComponent(ref)}/${encodedPath}`;
}

export async function fetchRemoteContract(repository, ref, relativePath, fetchImpl = fetch) {
  const response = await fetchImpl(rawUrl(repository, ref, relativePath), {
    headers: { 'user-agent': 'agent-workflow-sync/v1' },
    signal: AbortSignal.timeout(20000),
  });
  if (!response.ok) throw new Error(`remote_fetch_failed_${response.status}`);
  return parseContract(await response.text());
}

function printJson(payload) {
  process.stdout.write(`${JSON.stringify(payload, null, 2)}\n`);
}

function gitShow(ref, relativePath) {
  try {
    return execFileSync('git', ['show', `${ref}:${relativePath}`], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] });
  } catch {
    return null;
  }
}

function gitChangedPaths(base, head) {
  const output = execFileSync('git', ['diff', '--name-only', `${base}...${head}`, '--'], {
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'inherit'],
  });
  return output.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
}

export function compareContracts(local, remote) {
  return {
    status: local.text === remote.text ? 'synced' : 'drift',
    local_version: local.metadata.contract_version,
    remote_version: remote.metadata.contract_version,
    local_sha256: local.digest,
    remote_sha256: remote.digest,
  };
}

async function localCommand(configPath) {
  const config = await readConfig(configPath);
  const contract = parseContract(await fs.readFile(config.contract_path, 'utf8'));
  const authority = contract.metadata.authority;
  if (authority.repository !== config.source_repository || authority.ref !== config.source_ref || authority.path !== config.contract_path) {
    throw new Error('contract_authority_config_mismatch');
  }
  if (!contract.metadata.consumers?.includes(config.repository)) throw new Error('contract_consumer_missing');
  printJson({
    status: 'ok',
    role: config.role,
    repository: config.repository,
    contract_version: contract.metadata.contract_version,
    sha256: contract.digest,
  });
}

async function compareCommand(configPath) {
  const config = await readConfig(configPath);
  const local = parseContract(await fs.readFile(config.contract_path, 'utf8'));
  const remoteRepository = config.role === 'source' ? config.peer_repository : config.source_repository;
  const remoteRef = config.role === 'source' ? config.peer_ref : config.source_ref;
  const remote = await fetchRemoteContract(remoteRepository, remoteRef, config.contract_path);
  const comparison = compareContracts(local, remote);
  printJson({
    ...comparison,
    role: config.role,
    repository: config.repository,
    remote_repository: remoteRepository,
    remote_ref: remoteRef,
  });
  if (comparison.status !== 'synced') process.exitCode = 2;
}

async function syncCommand(configPath, write) {
  const config = await readConfig(configPath);
  if (config.role !== 'consumer') throw new Error('sync_only_allowed_for_consumer');
  const localRaw = await fs.readFile(config.contract_path, 'utf8').catch(() => '');
  const local = localRaw ? parseContract(localRaw) : null;
  const remote = await fetchRemoteContract(config.source_repository, config.source_ref, config.contract_path);
  const changed = !local || local.text !== remote.text;
  if (changed && write) {
    await fs.mkdir(path.dirname(config.contract_path), { recursive: true });
    await fs.writeFile(config.contract_path, remote.text, 'utf8');
  }
  printJson({
    status: changed ? 'updated' : 'already_synced',
    changed,
    wrote: Boolean(changed && write),
    source_repository: config.source_repository,
    source_ref: config.source_ref,
    contract_version: remote.metadata.contract_version,
    sha256: remote.digest,
  });
}

async function sourceGuardCommand(configPath, base, head) {
  const config = await readConfig(configPath);
  if (config.role !== 'source') throw new Error('source_guard_only_allowed_for_source');
  if (!base || !head) throw new Error('source_guard_missing_ref');
  const changedPaths = gitChangedPaths(base, head);
  const watchedChanged = config.source_policy_paths.filter((item) => changedPaths.includes(item));
  if (watchedChanged.length === 0) {
    printJson({ status: 'not_applicable', watched_changed: [] });
    return;
  }
  if (!changedPaths.includes(config.contract_path)) {
    printJson({ status: 'blocked', code: 'portable_contract_not_updated', watched_changed: watchedChanged });
    process.exitCode = 3;
    return;
  }
  const headContract = parseContract(await fs.readFile(config.contract_path, 'utf8'));
  const baseRaw = gitShow(base, config.contract_path);
  if (baseRaw) {
    const baseContract = parseContract(baseRaw);
    if (baseContract.metadata.contract_version === headContract.metadata.contract_version) {
      printJson({
        status: 'blocked',
        code: 'portable_contract_version_not_incremented',
        watched_changed: watchedChanged,
        contract_version: headContract.metadata.contract_version,
      });
      process.exitCode = 3;
      return;
    }
  }
  printJson({
    status: 'ok',
    watched_changed: watchedChanged,
    contract_version: headContract.metadata.contract_version,
    sha256: headContract.digest,
  });
}

function parseArgs(argv) {
  const [command = 'local', ...rest] = argv;
  let configPath = DEFAULT_CONFIG;
  let write = false;
  let base = '';
  let head = '';
  for (let index = 0; index < rest.length; index += 1) {
    const token = rest[index];
    if (token === '--config') configPath = rest[++index];
    else if (token === '--write') write = true;
    else if (token === '--base') base = rest[++index];
    else if (token === '--head') head = rest[++index];
    else throw new Error(`unknown_argument_${token}`);
  }
  return { command, configPath, write, base, head };
}

export async function main(argv = process.argv.slice(2)) {
  const { command, configPath, write, base, head } = parseArgs(argv);
  if (command === 'local') return localCommand(configPath);
  if (command === 'compare') return compareCommand(configPath);
  if (command === 'sync') return syncCommand(configPath, write);
  if (command === 'source-guard') return sourceGuardCommand(configPath, base, head);
  throw new Error(`unknown_command_${command}`);
}

const isEntryPoint = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isEntryPoint) {
  main().catch((error) => {
    process.stderr.write(`${error.message || error}\n`);
    process.exitCode = 1;
  });
}
