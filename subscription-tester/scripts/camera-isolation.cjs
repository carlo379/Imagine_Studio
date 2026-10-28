'use strict';
// Install before native imports. Reads need only local modules; writes, if any,
// stay in the worker's private cwd. References do not need files from a home dir.
const path = require('node:path');
const os = require('node:os');
const fs = require('node:fs');

function install() {
  const temporary = process.cwd(), library = path.join(os.homedir(), 'Library');
  function violation() {
    const error = new Error('Camera worker isolation violation.');
    error.code = 'camera_renderer_isolation';
    throw error;
  }
  function check(value, writing = false) {
    if (typeof value === 'number') return;
    if (value instanceof URL) value = require('node:url').fileURLToPath(value);
    const filename = path.resolve(Buffer.isBuffer(value) ? value.toString() : String(value));
    const inside = (base) => filename === base || filename.startsWith(base + path.sep);
    if (filename.split(path.sep).includes('Applications') || inside(library) || (writing && !inside(temporary))) violation();
  }
  const reads = ['readFileSync','readFile','openSync','open','statSync','stat','lstatSync','lstat','readdirSync','readdir','accessSync','access','realpathSync','realpath','existsSync','createReadStream'];
  const writes = ['writeFileSync','writeFile','appendFileSync','appendFile','mkdirSync','mkdir','unlinkSync','unlink','rmSync','rm','createWriteStream'];
  for (const name of [...reads, ...writes]) {
    const original = fs[name];
    fs[name] = function(filename, ...args) {
      check(filename, writes.includes(name) || ((name === 'openSync' || name === 'open') && args[0] !== 'r'));
      return original.call(this, filename, ...args);
    };
  }
  for (const name of ['readFile','open','stat','lstat','readdir','access','realpath','writeFile','appendFile','mkdir','unlink','rm']) {
    const original = fs.promises[name];
    fs.promises[name] = function(filename, ...args) {
      check(filename, writes.includes(name) || (name === 'open' && args[0] !== 'r'));
      return original.call(this, filename, ...args);
    };
  }
  const child = require('node:child_process');
  for (const name of ['spawn','spawnSync','exec','execSync','execFile','execFileSync','fork']) child[name] = violation;
  for (const name of ['http','https']) {
    const module = require('node:' + name); module.request = violation; module.get = violation;
  }
  require('node:net').Socket.prototype.connect = violation;
  require('node:tls').connect = violation;
  require('node:dgram').createSocket = violation;
  globalThis.fetch = violation; globalThis.WebSocket = violation;
  return {violation};
}
module.exports = {install};
