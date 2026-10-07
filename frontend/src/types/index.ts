export interface HealthResponse {
  status: string;
  version: string;
  is_storage_safe: boolean;
  storage_free_percent: number;
  database_connected: boolean;
  ae_title: string;
  dicom_port: number;
}

export interface StorageTelemetry {
  total_bytes: number;
  free_bytes: number;
  used_bytes: number;
  free_percent: number;
  is_watermark_safe: boolean;
  min_required_percent: number;
}

export interface QueueTelemetry {
  staged_count: number;
  processing_count: number;
  processed_count: number;
  forwarded_count: number;
  failed_count: number;
  quarantined_count: number;
}

export interface SystemTelemetry {
  cpu_percent: number;
  memory_total_mb: number;
  memory_used_mb: number;
  memory_percent: number;
  process_memory_mb: number;
  storage: StorageTelemetry;
  queues: QueueTelemetry;
  database_size_bytes: number;
}

export interface InstanceItem {
  sop_instance_uid: string;
  sop_class_uid: string;
  study_instance_uid: string;
  series_instance_uid: string;
  calling_ae_title: string;
  original_file_path: string;
  processed_file_path: string | null;
  file_size_bytes: number;
  sha256_hash: string;
  pipeline_status: string;
  retry_count: number;
  error_message: string | null;
  received_at: string;
  processed_at: string | null;
  forwarded_at: string | null;
}

export interface QueueListResponse {
  total_count: number;
  instances: InstanceItem[];
}

export interface ModalityItem {
  ae_title: string;
  ip_address: string;
  description: string | null;
  is_active: number;
  created_at: string;
}

export interface AuditRecordItem {
  log_id: number;
  timestamp: string;
  event_type: string;
  actor: string;
  patient_hash: string | null;
  details: Record<string, any>;
  previous_hash: string;
  current_hash: string;
}

export interface AuditVerificationResult {
  is_chain_intact: boolean;
  total_records_verified: number;
  error_message: string | null;
}

export interface ActionResponse {
  success: boolean;
  message: string;
  details?: Record<string, any>;
}
