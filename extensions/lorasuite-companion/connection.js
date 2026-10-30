import { engineURL } from './capture.js';

// Only known loopback ports and never a token/code. The engine deliberately
// denies extension access to /health; identify its public pairing challenge
// instead. This works with already installed desktop builds, without granting
// the extension access to any additional engine endpoint.
export async function findEngines(preferred) {
  const addresses = [...new Set([preferred, 'http://127.0.0.1:8767', 'http://127.0.0.1:8766', 'http://127.0.0.1:8765'].filter(Boolean).map(engineURL))];
  const results = await Promise.all(addresses.map(async address => {
    try {
      const response = await fetch(`${address}/library/companion/context`, { credentials: 'omit', redirect: 'error', signal: AbortSignal.timeout(1500) });
      if (response.status !== 401) return null;
      const challenge = await response.json();
      return challenge.detail === "Pair this extension in LoraSuite's Model Library" ? address : null;
    } catch { return null; }
  }));
  return results.filter(Boolean);
}
