#!/usr/bin/env node
"use strict";

const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const EXPECTED_PACKAGES = ["mote-proxy", "moted", "chat", "chatd"];

function command(...args) {
  const result = spawnSync(args[0], args.slice(1), { encoding: "utf8" });
  if (result.status !== 0) {
    throw new Error(`${args.join(" ")} failed: ${(result.stderr || result.stdout).trim()}`);
  }
  return result.stdout.trim();
}

function sha256(file) {
  return crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");
}

function packageField(asset, field) {
  return command("dpkg-deb", "-f", asset, field);
}

function discoverPackages(assetsDir) {
  const debs = fs.readdirSync(assetsDir)
    .filter((name) => name.endsWith(".deb"))
    .map((name) => path.join(assetsDir, name));
  assert.equal(debs.length, EXPECTED_PACKAGES.length, "bundle must contain exactly four Debian packages");
  const packages = new Map();
  for (const asset of debs) {
    const name = packageField(asset, "Package");
    if (!EXPECTED_PACKAGES.includes(name)) continue;
    assert.equal(packages.has(name), false, `duplicate ${name} package`);
    packages.set(name, {
      name,
      version: packageField(asset, "Version"),
      architecture: packageField(asset, "Architecture"),
      asset,
      sha256: sha256(asset),
    });
  }
  assert.deepEqual([...packages.keys()].sort(), [...EXPECTED_PACKAGES].sort());
  return packages;
}

function validateManifest(assetsDir, packages) {
  const manifestPath = path.join(assetsDir, "release-manifest.json");
  assert.equal(fs.existsSync(manifestPath), true, "release-manifest.json is required");
  const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
  assert.equal(manifest.schema, "mote-transport-dual-channel-public-release/v1");
  assert.equal(manifest.status, "component-qualified");
  assert.equal(manifest.transport?.direct_chat_to_proxy, false);
  assert.equal(manifest.runtime_acceptance, "pending-endpoint-e2e");
  assert.equal(manifest.packages?.length, EXPECTED_PACKAGES.length);
  for (const pkg of packages.values()) {
    const record = manifest.packages.find((value) => value.name === pkg.name);
    assert.ok(record, `manifest is missing ${pkg.name}`);
    assert.equal(record.version, pkg.version);
    assert.equal(record.architecture, pkg.architecture);
    assert.equal(record.asset, path.basename(pkg.asset));
    assert.equal(record.sha256, pkg.sha256);
  }
  assert.deepEqual(
    manifest.packages.map((value) => value.name).sort(),
    [...EXPECTED_PACKAGES].sort(),
  );
  return manifest;
}

function extractPackages(packages, temporaryRoot) {
  const roots = new Map();
  for (const pkg of packages.values()) {
    const root = path.join(temporaryRoot, "packages", pkg.name);
    fs.mkdirSync(root, { recursive: true });
    command("dpkg-deb", "-x", pkg.asset, root);
    roots.set(pkg.name, root);
  }
  return roots;
}

function moduleFrom(roots, packageName, relativePath) {
  const filename = path.join(roots.get(packageName), relativePath);
  assert.equal(fs.existsSync(filename), true, `${packageName} is missing ${relativePath}`);
  return require(filename);
}

function socketMode(socketPath) {
  return fs.statSync(socketPath).mode & 0o777;
}

function closeServer(server) {
  if (!server || !server.listening) return Promise.resolve();
  return new Promise((resolve, reject) => {
    server.close((error) => (error ? reject(error) : resolve()));
  });
}

async function verify(assetsDir) {
  const packages = discoverPackages(assetsDir);
  const manifest = validateManifest(assetsDir, packages);
  const temporaryRoot = fs.mkdtempSync(path.join(os.tmpdir(), "mote-dual-channel-e2e-"));
  let localChatd;
  let remoteChatd;
  let remoteChatdClosed = false;
  let proxy;

  try {
    const roots = extractPackages(packages, temporaryRoot);
    const chat = moduleFrom(roots, "chat", "usr/lib/chat/client.js");
    const chatd = moduleFrom(roots, "chatd", "usr/lib/chatd/runtime.js");
    const proxyModule = moduleFrom(roots, "mote-proxy", "usr/lib/mote-proxy/msg-runtime.js");
    const moted = moduleFrom(roots, "moted", "usr/lib/moted/msg-dispatch-runtime.js");

    assert.equal(chat.APP_SCHEMA, chatd.APP_SCHEMA);
    assert.equal(chatd.PROXY_REQUEST_SCHEMA, proxyModule.LOCAL_MSG_SCHEMA);
    assert.equal(chatd.MESSAGE_SCHEMA, proxyModule.MSG_SCHEMA);
    assert.equal(proxyModule.MSG_SCHEMA, moted.MSG_SCHEMA);
    assert.equal(chatd.DELIVERY_SCHEMA, moted.CHATD_DELIVERY_SCHEMA);

    const chatSource = fs.readFileSync(
      path.join(roots.get("chat"), "usr/lib/chat/client.js"), "utf8",
    );
    assert.equal(chatSource.includes("mote-proxy/msg.sock"), false);
    assert.equal(chatSource.includes("mote-proxy.local-msg"), false);

    const runtimeRoot = path.join(temporaryRoot, "runtime");
    const localAppSocket = path.join(runtimeRoot, "local/chatd/apps.sock");
    const localIngressSocket = path.join(runtimeRoot, "local/chatd/ingress.sock");
    const proxySocket = path.join(runtimeRoot, "local/mote-proxy/msg.sock");
    const remoteAppSocket = path.join(runtimeRoot, "remote/chatd/apps.sock");
    const remoteIngressSocket = path.join(runtimeRoot, "remote/chatd/ingress.sock");

    remoteChatd = new chatd.ChatdRuntime({
      ingressSocketPath: remoteIngressSocket,
      appSocketPath: remoteAppSocket,
      store: new chatd.ChatStore(path.join(runtimeRoot, "remote/inbox.ndjson")),
    });
    await remoteChatd.listen();

    const targetMoted = new moted.MsgDispatchRuntime({
      localEndpoint: "medge-tv.mote",
      socketPath: remoteIngressSocket,
      timeoutMs: 1000,
    });

    proxy = new proxyModule.MsgRuntime({
      socketPath: proxySocket,
      localTarget: "medge-home.mote",
      resolveTarget: async (target) => {
        assert.equal(target, "medge-tv.mote");
        return { targetMma: "dc/edge/moted-app" };
      },
      send: async (targetMma, envelope) => {
        assert.equal(targetMma, "dc/edge/moted-app");
        return targetMoted.dispatch({ from: "dc/edge/mote-proxy-app;n=1" }, envelope);
      },
    });
    fs.mkdirSync(path.dirname(proxySocket), { recursive: true, mode: 0o750 });
    await proxy.listen();

    localChatd = new chatd.ChatdRuntime({
      ingressSocketPath: localIngressSocket,
      appSocketPath: localAppSocket,
      proxySocketPath: proxySocket,
      proxyTimeoutMs: 1000,
      store: new chatd.ChatStore(path.join(runtimeRoot, "local/inbox.ndjson")),
    });
    await localChatd.listen();

    const ids = {
      sessionId: "11111111-1111-4111-8111-111111111111",
      messageId: "22222222-2222-4222-8222-222222222222",
    };
    const first = await chat.sendText("medge-tv.mote", "hello from exact Debian artifacts", {
      socketPath: localAppSocket,
      timeoutMs: 1000,
      ...ids,
    });
    assert.equal(first.status, "accepted");

    const duplicate = await chat.sendText("medge-tv.mote", "hello from exact Debian artifacts", {
      socketPath: localAppSocket,
      timeoutMs: 1000,
      ...ids,
    });
    assert.equal(duplicate.duplicate, true);

    const inbox = await chat.receiveInbox(0, 50, {
      socketPath: remoteAppSocket,
      timeoutMs: 1000,
    });
    assert.equal(inbox.messages.length, 1);
    assert.equal(inbox.messages[0].message_id, ids.messageId);
    assert.equal(inbox.messages[0].payload.text, "hello from exact Debian artifacts");
    assert.equal((await chat.statusApp({ socketPath: remoteAppSocket, timeoutMs: 1000 })).latest_sequence, 1);

    assert.deepEqual(chat.parseSlashCommand("/help"), { op: "help" });
    assert.deepEqual(chat.parseSlashCommand("/status"), { op: "status" });
    assert.deepEqual(chat.parseSlashCommand("/receive 0 10"), { op: "receive", after: 0, limit: 10 });
    assert.deepEqual(chat.parseSlashCommand("/quit"), { op: "quit" });
    assert.throws(() => chat.parseSlashCommand(".quit"));

    for (const socketPath of [
      localAppSocket, localIngressSocket, proxySocket, remoteAppSocket, remoteIngressSocket,
    ]) {
      assert.equal(socketMode(socketPath), 0o660, `${path.basename(socketPath)} must use mode 0660`);
    }

    await remoteChatd.close();
    remoteChatdClosed = true;
    await assert.rejects(
      chat.sendText("medge-tv.mote", "D failure containment", {
        socketPath: localAppSocket,
        timeoutMs: 1000,
        sessionId: "33333333-3333-4333-8333-333333333333",
        messageId: "44444444-4444-4444-8444-444444444444",
      }),
      /temporarily unavailable/,
    );
    assert.equal(proxy.snapshot().listening, true);
    assert.equal(localChatd.snapshot().app_listening, true);
    assert.equal((await chat.statusApp({ socketPath: localAppSocket, timeoutMs: 1000 })).latest_sequence, 0);
    assert.equal(targetMoted.snapshot().rejected_total, 1);

    return {
      schema: "mote.transport.bundle-e2e/v1",
      status: "passed",
      generated_at: new Date().toISOString(),
      source: "exact-debian-release-assets",
      release_tag: manifest.tag,
      application_path: "chat -> local chatd -> local mote-proxy -> xMSG -> target moted -> remote chatd -> remote chat",
      transport_bridge: "in-process-simulated-native-xmsg",
      endpoint_runtime: "not-tested",
      packages: Object.fromEntries([...packages.values()].map((pkg) => [pkg.name, {
        version: pkg.version,
        architecture: pkg.architecture,
        asset: path.basename(pkg.asset),
        sha256: pkg.sha256,
      }])),
      checks: {
        chat_to_chat_package_chain: "passed",
        duplicate_message_idempotency: "passed",
        slash_command_locality: "passed",
        group_scoped_socket_modes: "passed",
        d_failure_containment: "passed",
        chat_proxy_bypass_absent: "passed",
      },
    };
  } finally {
    if (localChatd) await localChatd.close();
    if (proxy) await closeServer(proxy.server);
    if (remoteChatd && !remoteChatdClosed) await remoteChatd.close();
    fs.rmSync(temporaryRoot, { recursive: true, force: true });
  }
}

function parseArguments(argv) {
  const values = { assetsDir: null, output: null };
  for (let index = 0; index < argv.length; index += 1) {
    if (argv[index] === "--assets-dir") values.assetsDir = argv[++index];
    else if (argv[index] === "--output") values.output = argv[++index];
    else throw new Error(`unknown argument: ${argv[index]}`);
  }
  if (!values.assetsDir) throw new Error("usage: verify-dual-channel-bundle.js --assets-dir DIR [--output FILE]");
  return values;
}

async function main() {
  const options = parseArguments(process.argv.slice(2));
  const evidence = await verify(path.resolve(options.assetsDir));
  const serialized = `${JSON.stringify(evidence, null, 2)}\n`;
  if (options.output) fs.writeFileSync(path.resolve(options.output), serialized, { mode: 0o644 });
  process.stdout.write(serialized);
}

main().catch((error) => {
  process.stderr.write(`dual-channel bundle verification failed: ${error.message}\n`);
  process.exitCode = 1;
});
