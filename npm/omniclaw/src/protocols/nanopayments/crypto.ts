import { createCipheriv, createDecipheriv, pbkdf2Sync, randomBytes } from "node:crypto";

const PBKDF2_ITERATIONS = 480_000;
const KEY_LENGTH = 32;
const SALT_LENGTH = 16;
const NONCE_LENGTH = 12;
const ALGO = "aes-256-gcm";

export interface EncryptedPrivateKey {
  salt: string;
  nonce: string;
  ciphertext: string;
  tag: string;
}

export function encryptPrivateKey(privateKey: string, secret: string): EncryptedPrivateKey {
  const salt = randomBytes(SALT_LENGTH);
  const key = pbkdf2Sync(secret, salt, PBKDF2_ITERATIONS, KEY_LENGTH, "sha256");
  const nonce = randomBytes(NONCE_LENGTH);
  const cipher = createCipheriv(ALGO, key, nonce);
  const ciphertext = Buffer.concat([cipher.update(privateKey, "utf8"), cipher.final()]);
  const tag = cipher.getAuthTag();

  return {
    salt: salt.toString("base64"),
    nonce: nonce.toString("base64"),
    ciphertext: ciphertext.toString("base64"),
    tag: tag.toString("base64")
  };
}

export function decryptPrivateKey(payload: EncryptedPrivateKey, secret: string): string {
  const salt = Buffer.from(payload.salt, "base64");
  const key = pbkdf2Sync(secret, salt, PBKDF2_ITERATIONS, KEY_LENGTH, "sha256");
  const nonce = Buffer.from(payload.nonce, "base64");
  const decipher = createDecipheriv(ALGO, key, nonce);
  decipher.setAuthTag(Buffer.from(payload.tag, "base64"));
  const plaintext = Buffer.concat([
    decipher.update(Buffer.from(payload.ciphertext, "base64")),
    decipher.final()
  ]);
  return plaintext.toString("utf8");
}
