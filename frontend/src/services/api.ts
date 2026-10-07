import {
  ActionResponse,
  AuditRecordItem,
  AuditVerificationResult,
  HealthResponse,
  ModalityItem,
  QueueListResponse,
  SystemTelemetry,
} from '../types';

const API_BASE = '/api';

export async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch(`${API_BASE}/health`);
  if (!res.ok) throw new Error(`Health fetch failed: ${res.statusText}`);
  return res.json();
}

export async function fetchTelemetry(): Promise<SystemTelemetry> {
  const res = await fetch(`${API_BASE}/telemetry`);
  if (!res.ok) throw new Error(`Telemetry fetch failed: ${res.statusText}`);
  return res.json();
}

export async function fetchQueue(status?: string, limit = 50, offset = 0): Promise<QueueListResponse> {
  const url = new URL(`${window.location.origin}${API_BASE}/queue`);
  if (status) url.searchParams.append('status', status);
  url.searchParams.append('limit', limit.toString());
  url.searchParams.append('offset', offset.toString());

  const res = await fetch(url.toString());
  if (!res.ok) throw new Error(`Queue fetch failed: ${res.statusText}`);
  return res.json();
}

export async function fetchModalities(): Promise<ModalityItem[]> {
  const res = await fetch(`${API_BASE}/modalities`);
  if (!res.ok) throw new Error(`Modalities fetch failed: ${res.statusText}`);
  return res.json();
}

export async function createModality(data: {
  ae_title: string;
  ip_address: string;
  description?: string;
  is_active?: boolean;
}): Promise<ModalityItem> {
  const res = await fetch(`${API_BASE}/modalities`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`Create modality failed: ${res.statusText}`);
  return res.json();
}

export async function toggleModality(aeTitle: string): Promise<ActionResponse> {
  const res = await fetch(`${API_BASE}/modalities/${encodeURIComponent(aeTitle)}/toggle`, {
    method: 'POST',
  });
  if (!res.ok) throw new Error(`Toggle modality failed: ${res.statusText}`);
  return res.json();
}

export async function fetchAuditTrail(limit = 50, offset = 0): Promise<AuditRecordItem[]> {
  const res = await fetch(`${API_BASE}/audit?limit=${limit}&offset=${offset}`);
  if (!res.ok) throw new Error(`Audit fetch failed: ${res.statusText}`);
  return res.json();
}

export async function verifyAuditChain(): Promise<AuditVerificationResult> {
  const res = await fetch(`${API_BASE}/audit/verify`);
  if (!res.ok) throw new Error(`Audit verify failed: ${res.statusText}`);
  return res.json();
}

export async function triggerWalCheckpoint(): Promise<ActionResponse> {
  const res = await fetch(`${API_BASE}/actions/checkpoint`, {
    method: 'POST',
  });
  if (!res.ok) throw new Error(`Checkpoint trigger failed: ${res.statusText}`);
  return res.json();
}
