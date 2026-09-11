import { validateAnyPayload, type ViewerAnyPayload } from './contracts.js';

export async function loadPayload(url = '/bundle/chart_payload.json'): Promise<ViewerAnyPayload> {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`chart payload request failed: ${response.status}`);
  return validateAnyPayload(await response.json() as unknown);
}

export { validateAnyPayload, validateDiagnosticPayload, validatePayload } from './contracts.js';
export type { DiagnosticViewerPayload, ViewerAnyPayload, ViewerPayload } from './contracts.js';
