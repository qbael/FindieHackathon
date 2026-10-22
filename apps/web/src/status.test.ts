import assert from 'node:assert/strict';
import test from 'node:test';
import { readSystemStatus } from './status.ts';

test('accepts actual scaffold readiness without inventing availability', () => {
  const value = {
    name: 'Findie API',
    stage: 'scaffold',
    database: 'ready',
    ai: 'unavailable',
    features: { business: false, authentication: false, storage: false },
  };
  assert.deepEqual(readSystemStatus(value), value);
});

test('rejects malformed or unexpected API responses', () => {
  for (const value of [null, [], {}, 'ready', { database: 'ready' }, {
    name: 'Findie API',
    stage: 'scaffold',
    database: 'ready',
    ai: 'unknown',
    features: { business: false, authentication: false, storage: false },
  }]) {
    assert.throws(() => readSystemStatus(value));
  }
});
