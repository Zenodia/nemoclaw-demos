#!/usr/bin/env node
/**
 * Create an encrypted openAiApi credential for n8n import:credentials.
 * Runs inside the n8n container; reads encryption key from /home/node/.n8n/config.
 */
const crypto = require('crypto');
const fs = require('fs');

const RANDOM_BYTES = Buffer.from('53616c7465645f5f', 'hex');

function getKeyAndIv(salt, key) {
  const password = Buffer.concat([Buffer.from(key, 'binary'), salt]);
  const hash1 = crypto.createHash('md5').update(password).digest();
  const hash2 = crypto.createHash('md5').update(Buffer.concat([hash1, password])).digest();
  const iv = crypto.createHash('md5').update(Buffer.concat([hash2, password])).digest();
  const derivedKey = Buffer.concat([hash1, hash2]);
  return [derivedKey, iv];
}

function encrypt(data, key) {
  const salt = crypto.randomBytes(8);
  const [derivedKey, iv] = getKeyAndIv(salt, key);
  const cipher = crypto.createCipheriv('aes-256-cbc', derivedKey, iv);
  const encrypted = cipher.update(data);
  return Buffer.concat([RANDOM_BYTES, salt, encrypted, cipher.final()]).toString('base64');
}

const apiKey = process.env.NVIDIA_API_KEY;
const baseUrl = process.env.NVIDIA_BASE_URL || 'https://integrate.api.nvidia.com/v1';
if (!apiKey) {
  console.error('NVIDIA_API_KEY is required');
  process.exit(1);
}

const encryptionKey = JSON.parse(fs.readFileSync('/home/node/.n8n/config', 'utf8')).encryptionKey;
const payload = JSON.stringify({ apiKey, url: baseUrl });
const encrypted = encrypt(payload, encryptionKey);

const cred = [
  {
    id: 'rO9tDpks1CwG9AN7',
    name: 'NVIDIAInferenceAPI',
    type: 'openAiApi',
    data: encrypted,
  },
];

const out = '/home/node/.n8n/nvidia-credential.json';
fs.writeFileSync(out, JSON.stringify(cred, null, 2));
console.log('Wrote', out);
