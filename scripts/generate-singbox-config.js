const fs = require('fs');
const path = require('path');

const ROOT_DIR = path.resolve(__dirname, '..');
const ARTIFACTS_DIR = path.join(ROOT_DIR, 'artifacts');
const CONFIG_DIR = path.join(ROOT_DIR, 'runtime');
const CONFIG_FILE = path.join(CONFIG_DIR, 'sing-box.json');

function main () {
  ensureDir(ARTIFACTS_DIR);
  ensureDir(CONFIG_DIR);

  const outbound = resolveOutbound();
  if (!outbound) {
    console.log('No sing-box source provided. Skipping sing-box config generation.');
    return;
  }

  const localHttpPort = Number(process.env.LOCAL_HTTP_PROXY_PORT || 7890);
  const localSocksPort = Number(process.env.LOCAL_SOCKS_PROXY_PORT || 7891);
  const localListen = process.env.LOCAL_PROXY_LISTEN || '127.0.0.1';

  const config = {
    log: {
      level: process.env.SINGBOX_LOG_LEVEL || 'info',
      timestamp: true
    },
    inbounds: [
      {
        type: 'mixed',
        tag: 'mixed-in',
        listen: localListen,
        listen_port: localHttpPort,
        sniff: true,
        sniff_override_destination: true
      },
      {
        type: 'socks',
        tag: 'socks-in',
        listen: localListen,
        listen_port: localSocksPort,
        sniff: true,
        sniff_override_destination: true
      }
    ],
    outbounds: [
      outbound,
      {
        type: 'direct',
        tag: 'direct'
      }
    ],
    route: {
      auto_detect_interface: true,
      final: outbound.tag || 'proxy-out'
    }
  };

  fs.writeFileSync(CONFIG_FILE, JSON.stringify(removeUndefined(config), null, 2));
  console.log(`sing-box config written to ${CONFIG_FILE}`);
  console.log(`Outbound type: ${outbound.type}`);
  console.log(`HTTP proxy: http://${localListen}:${localHttpPort}`);
  console.log(`SOCKS proxy: socks5://${localListen}:${localSocksPort}`);
}

function resolveOutbound () {
  const rawOutboundJson = (process.env.SINGBOX_OUTBOUND_JSON || '').trim();
  if (rawOutboundJson) {
    const outbound = JSON.parse(rawOutboundJson);
    if (!outbound || typeof outbound !== 'object' || Array.isArray(outbound)) {
      throw new Error('SINGBOX_OUTBOUND_JSON must be a JSON object.');
    }

    outbound.tag = outbound.tag || 'proxy-out';
    return outbound;
  }

  const vmessLink = firstNonEmpty(process.env.VMESS_URL, process.env.SINGBOX_VMESS_URL);
  if (vmessLink) {
    return buildVmessOutbound(parseVmess(vmessLink));
  }

  const vlessLink = firstNonEmpty(process.env.VLESS_URL, process.env.SINGBOX_VLESS_URL);
  if (vlessLink) {
    return buildVlessOutbound(parseStandardUrl(vlessLink, 'vless://'));
  }

  const trojanLink = firstNonEmpty(process.env.TROJAN_URL, process.env.SINGBOX_TROJAN_URL);
  if (trojanLink) {
    return buildTrojanOutbound(parseStandardUrl(trojanLink, 'trojan://'));
  }

  const hysteria2Link = firstNonEmpty(process.env.HY2_URL, process.env.HYSTERIA2_URL, process.env.SINGBOX_HY2_URL);
  if (hysteria2Link) {
    return buildHysteria2Outbound(parseStandardUrl(hysteria2Link, 'hy2://', 'hysteria2://'));
  }

  return null;
}

function parseVmess (vmessLink) {
  const encoded = vmessLink.replace(/^vmess:\/\//i, '').trim();
  const decodedText = Buffer.from(encoded, 'base64').toString('utf8').trim();
  if (!decodedText.startsWith('{')) {
    throw new Error('VMESS_URL does not contain a supported JSON payload.');
  }

  const parsed = JSON.parse(decodedText);
  if (!parsed.add || !parsed.port || !parsed.id) {
    throw new Error('VMESS_URL is missing required fields: add, port, or id.');
  }

  return parsed;
}

function parseStandardUrl (value, ...allowedPrefixes) {
  const input = String(value || '').trim();
  const matchedPrefix = allowedPrefixes.find((prefix) => input.toLowerCase().startsWith(prefix.toLowerCase()));
  if (!matchedPrefix) {
    throw new Error(`Unsupported URL format: expected ${allowedPrefixes.join(' or ')}`);
  }

  const url = new URL(input);
  const query = {};
  url.searchParams.forEach((innerValue, key) => {
    query[key] = innerValue;
  });

  return {
    protocol: url.protocol.replace(':', '').toLowerCase(),
    username: decodeURIComponent(url.username || ''),
    password: decodeURIComponent(url.password || ''),
    hostname: url.hostname,
    port: url.port ? Number(url.port) : undefined,
    pathname: decodeURIComponent(url.pathname || ''),
    hash: decodeURIComponent(url.hash.replace(/^#/, '')),
    query
  };
}

function buildVmessOutbound (vmess) {
  const pathValue = vmess.path || '/';
  const hostValue = vmess.host || undefined;
  const serverName = vmess.sni || vmess.host || vmess.add;
  const tlsEnabled = String(vmess.tls || '').toLowerCase() === 'tls';
  const network = String(vmess.net || 'tcp').toLowerCase();

  const outbound = {
    type: 'vmess',
    tag: 'proxy-out',
    server: vmess.add,
    server_port: Number(vmess.port),
    uuid: vmess.id,
    security: normalizeSecurity(vmess.scy),
    alter_id: Number(vmess.aid || 0)
  };

  if (tlsEnabled) {
    outbound.tls = buildTlsBlock({
      enabled: true,
      serverName,
      insecure: false,
      alpn: vmess.alpn,
      fingerprint: vmess.fp
    });
  }

  outbound.transport = buildTransport(network, {
    host: hostValue,
    path: pathValue,
    serviceName: vmess.serviceName,
    mode: vmess.mode,
    authority: vmess.authority,
    type: vmess.type,
    headerType: vmess.type,
    seed: vmess.seed
  });

  return removeUndefined(outbound);
}

function buildVlessOutbound (parsed) {
  if (!parsed.username || !parsed.hostname || !parsed.port) {
    throw new Error('VLESS_URL must include uuid, host, and port.');
  }

  const network = normalizeNetwork(parsed.query.type || 'tcp');
  const security = String(parsed.query.security || '').toLowerCase();
  const outbound = {
    type: 'vless',
    tag: 'proxy-out',
    server: parsed.hostname,
    server_port: Number(parsed.port),
    uuid: parsed.username,
    flow: parsed.query.flow || undefined,
    packet_encoding: parsed.query.packetEncoding || parsed.query.packet_encoding || undefined
  };

  if (security === 'tls' || security === 'reality') {
    outbound.tls = buildTlsBlock({
      enabled: true,
      serverName: parsed.query.sni || parsed.hostname,
      insecure: parseBooleanText(parsed.query.allowInsecure || parsed.query.insecure),
      alpn: parsed.query.alpn,
      fingerprint: parsed.query.fp || parsed.query.fingerprint,
      realityPublicKey: parsed.query.pbk || parsed.query.publicKey,
      realityShortId: parsed.query.sid || parsed.query.shortId
    });
    if (security === 'reality') {
      outbound.tls.reality = removeUndefined({
        enabled: true,
        public_key: parsed.query.pbk || parsed.query.publicKey,
        short_id: parsed.query.sid || parsed.query.shortId
      });
    }
  }

  outbound.transport = buildTransport(network, {
    host: parsed.query.host,
    path: parsed.query.path,
    serviceName: parsed.query.serviceName,
    mode: parsed.query.mode,
    authority: parsed.query.authority,
    headerType: parsed.query.headerType,
    seed: parsed.query.seed
  });

  return removeUndefined(outbound);
}

function buildTrojanOutbound (parsed) {
  if (!parsed.username || !parsed.hostname || !parsed.port) {
    throw new Error('TROJAN_URL must include password, host, and port.');
  }

  const network = normalizeNetwork(parsed.query.type || 'tcp');
  const security = String(parsed.query.security || 'tls').toLowerCase();
  const outbound = {
    type: 'trojan',
    tag: 'proxy-out',
    server: parsed.hostname,
    server_port: Number(parsed.port),
    password: parsed.username
  };

  if (security === 'tls' || security === '') {
    outbound.tls = buildTlsBlock({
      enabled: true,
      serverName: parsed.query.sni || parsed.hostname,
      insecure: parseBooleanText(parsed.query.allowInsecure || parsed.query.insecure),
      alpn: parsed.query.alpn,
      fingerprint: parsed.query.fp || parsed.query.fingerprint
    });
  }

  outbound.transport = buildTransport(network, {
    host: parsed.query.host,
    path: parsed.query.path,
    serviceName: parsed.query.serviceName,
    mode: parsed.query.mode,
    authority: parsed.query.authority,
    headerType: parsed.query.headerType,
    seed: parsed.query.seed
  });

  return removeUndefined(outbound);
}

function buildHysteria2Outbound (parsed) {
  const password = parsed.username || parsed.password || parsed.query.password;
  if (!password || !parsed.hostname || !parsed.port) {
    throw new Error('HY2_URL must include password, host, and port.');
  }

  const outbound = {
    type: 'hysteria2',
    tag: 'proxy-out',
    server: parsed.hostname,
    server_port: Number(parsed.port),
    password,
    up_mbps: toNumberOrUndefined(parsed.query.upmbps || parsed.query.up || parsed.query.upload),
    down_mbps: toNumberOrUndefined(parsed.query.downmbps || parsed.query.down || parsed.query.download),
    obfs: parsed.query.obfs ? {
      type: parsed.query.obfs,
      password: parsed.query['obfs-password'] || parsed.query.obfsPassword || parsed.query.password2
    } : undefined,
    tls: buildTlsBlock({
      enabled: true,
      serverName: parsed.query.sni || parsed.hostname,
      insecure: parseBooleanText(parsed.query.insecure || parsed.query.allowInsecure),
      alpn: parsed.query.alpn,
      fingerprint: parsed.query.fp || parsed.query.fingerprint
    })
  };

  return removeUndefined(outbound);
}

function buildTlsBlock (options) {
  if (!options || !options.enabled) {
    return undefined;
  }

  const block = {
    enabled: true,
    server_name: options.serverName,
    insecure: Boolean(options.insecure)
  };

  const alpn = splitCsv(options.alpn);
  if (alpn.length) {
    block.alpn = alpn;
  }

  if (options.fingerprint) {
    block.utls = {
      enabled: true,
      fingerprint: options.fingerprint
    };
  }

  if (options.realityPublicKey || options.realityShortId) {
    block.reality = removeUndefined({
      enabled: true,
      public_key: options.realityPublicKey,
      short_id: options.realityShortId
    });
  }

  return removeUndefined(block);
}

function buildTransport (network, options) {
  const normalized = normalizeNetwork(network);
  if (!normalized || normalized === 'tcp') {
    return undefined;
  }

  if (normalized === 'ws') {
    const pathValue = options.path || '/';
    const earlyData = extractEarlyData(pathValue);
    const normalizedPath = removeEarlyDataQuery(pathValue);
    return removeUndefined({
      type: 'ws',
      path: normalizedPath,
      headers: options.host ? { Host: options.host } : undefined,
      max_early_data: earlyData,
      early_data_header_name: earlyData ? 'Sec-WebSocket-Protocol' : undefined
    });
  }

  if (normalized === 'grpc') {
    return removeUndefined({
      type: 'grpc',
      service_name: options.serviceName || options.path || undefined,
      idle_timeout: '15s'
    });
  }

  if (normalized === 'http') {
    return removeUndefined({
      type: 'http',
      host: options.host ? splitCsv(options.host) : undefined,
      path: options.path || undefined,
      method: 'GET'
    });
  }

  if (normalized === 'httpupgrade') {
    return removeUndefined({
      type: 'httpupgrade',
      host: options.host,
      path: options.path || '/'
    });
  }

  if (normalized === 'kcp') {
    return removeUndefined({
      type: 'mkcp',
      header: options.headerType || 'none',
      seed: options.seed
    });
  }

  return undefined;
}

function extractEarlyData (pathValue) {
  const match = String(pathValue).match(/[?&]ed=(\d+)/i);
  return match ? Number(match[1]) : undefined;
}

function removeEarlyDataQuery (pathValue) {
  const input = String(pathValue || '/').trim() || '/';
  const cleaned = input
    .replace(/([?&])ed=\d+&?/i, '$1')
    .replace(/[?&]$/, '');

  return cleaned || '/';
}

function normalizeSecurity (value) {
  const normalized = String(value || 'auto').trim().toLowerCase();
  if (normalized === 'none') {
    return 'auto';
  }

  return normalized || 'auto';
}

function normalizeNetwork (value) {
  return String(value || 'tcp').trim().toLowerCase();
}

function splitCsv (value) {
  return String(value || '').split(',').map((item) => item.trim()).filter(Boolean);
}

function parseBooleanText (value) {
  if (value === undefined || value === null || value === '') {
    return false;
  }

  return /^(1|true|yes|on)$/i.test(String(value));
}

function toNumberOrUndefined (value) {
  if (value === undefined || value === null || value === '') {
    return undefined;
  }

  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? numberValue : undefined;
}

function firstNonEmpty (...values) {
  for (const value of values) {
    if (value && String(value).trim()) {
      return String(value).trim();
    }
  }

  return '';
}

function removeUndefined (value) {
  if (Array.isArray(value)) {
    return value.map(removeUndefined);
  }

  if (!value || typeof value !== 'object') {
    return value;
  }

  const result = {};
  for (const [key, innerValue] of Object.entries(value)) {
    if (innerValue === undefined) {
      continue;
    }

    result[key] = removeUndefined(innerValue);
  }

  return result;
}

function ensureDir (dirPath) {
  fs.mkdirSync(dirPath, { recursive: true });
}

main();
