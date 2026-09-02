#!/usr/bin/env node
"use strict";

const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const EXPECTED_PACKAGES = ["mote-proxy", "moted", "schat", "schatd"];

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
  assert.equal(manifest.schema, "mote-transport-dual-channel-public-release/v2");
  assert.equal(manifest.status, "component-qualified");
  assert.equal(manifest.transport?.direct_schat_to_proxy, false);
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
  let localSchatd;
  let remoteSchatd;
  let remoteSchatdClosed = false;
  let proxy;

  try {
    const roots = extractPackages(packages, temporaryRoot);
    const schat = moduleFrom(roots, "schat", "usr/lib/schat/client.js");
    const schatd = moduleFrom(roots, "schatd", "usr/lib/schatd/runtime.js");
    const proxyModule = moduleFrom(roots, "mote-proxy", "usr/lib/mote-proxy/msg-runtime.js");
    const moted = moduleFrom(roots, "moted", "usr/lib/moted/msg-dispatch-runtime.js");

    assert.equal(schat.APP_SCHEMA, schatd.APP_SCHEMA);
    assert.equal(schatd.PROXY_REQUEST_SCHEMA, proxyModule.LOCAL_MSG_SCHEMA);
    assert.equal(schatd.MESSAGE_SCHEMA, proxyModule.MSG_SCHEMA);
    assert.equal(proxyModule.MSG_SCHEMA, moted.MSG_SCHEMA);
    assert.equal(schatd.DELIVERY_SCHEMA, moted.SCHATD_DELIVERY_SCHEMA);

    const schatSource = fs.readFileSync(
      path.join(roots.get("schat"), "usr/lib/schat/client.js"), "utf8",
    );
    assert.equal(schatSource.includes("mote-proxy/msg.sock"), false);
    assert.equal(schatSource.includes("mote-proxy.local-msg"), false);

    const runtimeRoot = path.join(temporaryRoot, "runtime");
    const localAppSocket = path.join(runtimeRoot, "local/schatd/apps.sock");
    const localIngressSocket = path.join(runtimeRoot, "local/schatd/ingress.sock");
    const proxySocket = path.join(runtimeRoot, "local/mote-proxy/msg.sock");
    const remoteAppSocket = path.join(runtimeRoot, "remote/schatd/apps.sock");
    const remoteIngressSocket = path.join(runtimeRoot, "remote/schatd/ingress.sock");

    remoteSchatd = new schatd.SchatdRuntime({
      ingressSocketPath: remoteIngressSocket,
      appSocketPath: remoteAppSocket,
      store: new schatd.SchatStore(path.join(runtimeRoot, "remote/inbox.ndjson")),
    });
    await remoteSchatd.listen();

    const targetMoted = new moted.MsgDispatchRuntime({
      localEndpoint: "medge-tv.mote",
      socketPath: remoteIngressSocket,
      timeoutMs: 1000,
    });
    const localMoted = new moted.MsgDispatchRuntime({
      localEndpoint: "medge-home.mote",
      socketPath: localIngressSocket,
      timeoutMs: 1000,
    });

    proxy = new proxyModule.MsgRuntime({
      socketPath: proxySocket,
      localTarget: "medge-home.mote",
      resolveTarget: async (target) => {
        assert.ok(["local.mote", "medge-tv.mote"].includes(target));
        return {
          targetMma: target === "local.mote"
            ? "dc/edge/local-moted-app"
            : "dc/edge/remote-moted-app",
        };
      },
      send: async (targetMma, envelope) => {
        const runtime = targetMma === "dc/edge/local-moted-app" ? localMoted : targetMoted;
        const result = await runtime.dispatch({ from: "dc/edge/mote-proxy-app;n=1" }, envelope);
        return { ErrCode: 0, ErrMsg: "OK", result };
      },
    });
    fs.mkdirSync(path.dirname(proxySocket), { recursive: true, mode: 0o750 });
    await proxy.listen();

    localSchatd = new schatd.SchatdRuntime({
      ingressSocketPath: localIngressSocket,
      appSocketPath: localAppSocket,
      proxySocketPath: proxySocket,
      proxyTimeoutMs: 1000,
      store: new schatd.SchatStore(path.join(runtimeRoot, "local/inbox.ndjson")),
    });
    await localSchatd.listen();

    const ids = {
      sessionId: "11111111-1111-4111-8111-111111111111",
      messageId: "22222222-2222-4222-8222-222222222222",
    };
    const ready = await schat.connectTarget("medge-tv.mote", ids.sessionId, {
      socketPath: localAppSocket,
      timeoutMs: 1000,
    });
    assert.equal(ready.status, "ready");
    assert.equal(ready.session_id, ids.sessionId);
    assert.equal(remoteSchatd.snapshot().recent_messages, 0);
    const first = await schat.sendText("medge-tv.mote", "hello from exact Debian artifacts", {
      socketPath: localAppSocket,
      timeoutMs: 1000,
      ...ids,
    });
    assert.equal(first.status, "accepted");

    const duplicate = await schat.sendText("medge-tv.mote", "hello from exact Debian artifacts", {
      socketPath: localAppSocket,
      timeoutMs: 1000,
      ...ids,
    });
    assert.equal(duplicate.duplicate, true);

    const inbox = await schat.receiveInbox(0, 50, {
      socketPath: remoteAppSocket,
      timeoutMs: 1000,
    });
    assert.equal(inbox.messages.length, 1);
    assert.equal(inbox.messages[0].message_id, ids.messageId);
    assert.equal(inbox.messages[0].payload.text, "hello from exact Debian artifacts");
    assert.equal((await schat.statusApp({ socketPath: remoteAppSocket, timeoutMs: 1000 })).latest_sequence, 1);

    const selfIds = {
      sessionId: "55555555-5555-4555-8555-555555555555",
      messageId: "66666666-6666-4666-8666-666666666666",
    };
    const selfFirst = await schat.sendText("local.mote", "one terminating self delivery", {
      socketPath: localAppSocket,
      timeoutMs: 1000,
      ...selfIds,
    });
    const selfDuplicate = await schat.sendText("local.mote", "one terminating self delivery", {
      socketPath: localAppSocket,
      timeoutMs: 1000,
      ...selfIds,
    });
    assert.equal(selfFirst.duplicate, false);
    assert.equal(selfDuplicate.duplicate, true);
    const localInbox = await schat.receiveInbox(0, 50, {
      socketPath: localAppSocket,
      timeoutMs: 1000,
    });
    assert.equal(localInbox.messages.length, 1);
    assert.equal(localMoted.snapshot().accepted_total, 2);

    assert.deepEqual(schat.parseSlashCommand("/help"), { op: "help" });
    assert.deepEqual(schat.parseSlashCommand("/status"), { op: "status" });
    assert.deepEqual(schat.parseSlashCommand("/inbox 0 10"), { op: "inbox", after: 0, limit: 10 });
    assert.throws(() => schat.parseSlashCommand("/receive"));
    assert.deepEqual(schat.parseSlashCommand("/quit"), { op: "quit" });
    assert.throws(() => schat.parseSlashCommand(".quit"));

    for (const socketPath of [localAppSocket, remoteAppSocket]) {
      assert.equal(socketMode(socketPath), 0o666, `${path.basename(socketPath)} must use mode 0666`);
    }
    for (const socketPath of [localIngressSocket, proxySocket, remoteIngressSocket]) {
      assert.equal(socketMode(socketPath), 0o660, `${path.basename(socketPath)} must use mode 0660`);
    }

    await remoteSchatd.close();
    remoteSchatdClosed = true;
    await assert.rejects(
      schat.connectTarget("medge-tv.mote", "77777777-7777-4777-8777-777777777777", {
        socketPath: localAppSocket,
        timeoutMs: 1000,
      }),
      /temporarily unavailable/,
    );
    await assert.rejects(
      schat.sendText("medge-tv.mote", "D failure containment", {
        socketPath: localAppSocket,
        timeoutMs: 1000,
        sessionId: "33333333-3333-4333-8333-333333333333",
        messageId: "44444444-4444-4444-8444-444444444444",
      }),
      /temporarily unavailable/,
    );
    assert.equal(proxy.snapshot().listening, true);
    assert.equal(localSchatd.snapshot().app_listening, true);
    assert.equal((await schat.statusApp({ socketPath: localAppSocket, timeoutMs: 1000 })).latest_sequence, 1);
    assert.equal(targetMoted.snapshot().rejected_total, 2);

    return {
      schema: "mote.transport.bundle-e2e/v1",
      status: "passed",
      generated_at: new Date().toISOString(),
      source: "exact-debian-release-assets",
      release_tag: manifest.tag,
      application_path: "schat -> local schatd -> local mote-proxy -> xMSG -> target moted -> remote schatd -> remote schat",
      transport_bridge: "in-process-simulated-native-xmsg",
      endpoint_runtime: "not-tested",
      packages: Object.fromEntries([...packages.values()].map((pkg) => [pkg.name, {
        version: pkg.version,
        architecture: pkg.architecture,
        asset: path.basename(pkg.asset),
        sha256: pkg.sha256,
      }])),
      checks: {
        schat_to_schat_package_chain: "passed",
        remote_ready_before_prompt: "passed",
        connect_has_no_inbox_record: "passed",
        duplicate_message_idempotency: "passed",
        self_delivery_loop_containment: "passed",
        slash_command_locality: "passed",
        open_local_app_socket_and_protected_ingress: "passed",
        d_failure_containment: "passed",
        schat_proxy_bypass_absent: "passed",
      },
    };
  } finally {
    if (localSchatd) await localSchatd.close();
    if (proxy) await closeServer(proxy.server);
    if (remoteSchatd && !remoteSchatdClosed) await remoteSchatd.close();
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
