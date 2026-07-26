import { validatePayload, type ViewerPayload } from './contracts.js';

export async function loadPayload(path = '/bundle/chart_payload.json'): Promise<ViewerPayload> {
  const response = await fetch(path, { cache: 'no-store' });
  if (!response.ok) throw new Error(`payload request failed: ${response.status}`);
  return validatePayload(await response.json());
}
