import { validatePayload, type ViewerPayload } from './contracts.js';

export async function loadPayload(url = '/bundle/chart_payload.json'): Promise<ViewerPayload> {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`chart payload request failed: ${response.status}`);
  return validatePayload(await response.json() as unknown);
}

export { validatePayload } from './contracts.js';
export type { ViewerPayload } from './contracts.js';
