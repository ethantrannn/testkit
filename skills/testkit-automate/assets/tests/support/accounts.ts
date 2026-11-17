// Test accounts come from environment variables only:
//   TESTKIT_E2E_<ROLE>_EMAIL, TESTKIT_E2E_<ROLE>_PASSWORD   (e.g. TESTKIT_E2E_MEMBER_EMAIL)
//   TESTKIT_E2E_<ROLE>_NAME   optional display name, for cases that check it
// Locally run_suite.py fills them from qa/accounts.local.json; in CI they are pipeline secrets.
import path from 'node:path';

export type Credentials = { email: string; password: string; name?: string };

export function envKey(role: string): string {
  return role.toUpperCase().replace(/[^A-Z0-9]/g, '_');
}

export function credentials(role: string): Credentials {
  const key = envKey(role);
  const email = process.env[`TESTKIT_E2E_${key}_EMAIL`];
  const password = process.env[`TESTKIT_E2E_${key}_PASSWORD`];
  if (!email || !password) {
    throw new Error(`Set TESTKIT_E2E_${key}_EMAIL and TESTKIT_E2E_${key}_PASSWORD for role "${role}".`);
  }
  return { email, password, name: process.env[`TESTKIT_E2E_${key}_NAME`] };
}

/** storageState file written by auth.setup.ts; .auth/ is git-ignored. */
export function authFile(role: string): string {
  return path.join(__dirname, '..', '..', '.auth', `${role}.json`);
}

/** Use in specs that must start signed out: test.use({ storageState: SIGNED_OUT }). */
export const SIGNED_OUT = { cookies: [], origins: [] };
