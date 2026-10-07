import React, { useState, useEffect } from 'react';
import { 
  Activity, 
  Server, 
  Database, 
  HardDrive, 
  ShieldCheck, 
  UploadCloud, 
  Radio, 
  Layers,
  AlertCircle,
  CheckCircle2,
  RefreshCw,
  Plus,
  Cpu,
  FileCheck
} from 'lucide-react';
import {
  fetchHealth,
  fetchTelemetry,
  fetchQueue,
  fetchModalities,
  createModality,
  toggleModality,
  fetchAuditTrail,
  verifyAuditChain,
  triggerWalCheckpoint
} from './services/api';
import {
  HealthResponse,
  SystemTelemetry,
  InstanceItem,
  ModalityItem,
  AuditRecordItem,
  AuditVerificationResult
} from './types';

export default function App() {
  const [activeTab, setActiveTab] = useState<'overview' | 'queue' | 'modalities' | 'audit'>('overview');
  
  // Dynamic State
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [telemetry, setTelemetry] = useState<SystemTelemetry | null>(null);
  const [instances, setInstances] = useState<InstanceItem[]>([]);
  const [queueStatusFilter, setQueueStatusFilter] = useState<string>('');
  const [modalities, setModalities] = useState<ModalityItem[]>([]);
  const [auditLogs, setAuditLogs] = useState<AuditRecordItem[]>([]);
  const [verifyResult, setVerifyResult] = useState<AuditVerificationResult | null>(null);
  const [isVerifying, setIsVerifying] = useState(false);
  const [isCheckpointing, setIsCheckpointing] = useState(false);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  // New Modality Form State
  const [newAeTitle, setNewAeTitle] = useState('');
  const [newIpAddress, setNewIpAddress] = useState('');
  const [newDescription, setNewDescription] = useState('');
  const [isAddingModality, setIsAddingModality] = useState(false);

  // Polling data every 3 seconds
  useEffect(() => {
    const loadTelemetry = async () => {
      try {
        const [hData, tData] = await Promise.all([
          fetchHealth().catch(() => null),
          fetchTelemetry().catch(() => null),
        ]);
        if (hData) setHealth(hData);
        if (tData) setTelemetry(tData);
      } catch (err) {
        console.error("Telemetry poll error:", err);
      }
    };

    loadTelemetry();
    const interval = setInterval(loadTelemetry, 3000);
    return () => clearInterval(interval);
  }, []);

  // Tab specific data load
  useEffect(() => {
    if (activeTab === 'queue') {
      fetchQueue(queueStatusFilter || undefined).then(res => setInstances(res.instances)).catch(console.error);
    } else if (activeTab === 'modalities') {
      fetchModalities().then(setModalities).catch(console.error);
    } else if (activeTab === 'audit') {
      fetchAuditTrail().then(setAuditLogs).catch(console.error);
    }
  }, [activeTab, queueStatusFilter]);

  const handleAddModality = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newAeTitle || !newIpAddress) return;
    try {
      await createModality({
        ae_title: newAeTitle,
        ip_address: newIpAddress,
        description: newDescription,
        is_active: true,
      });
      setNewAeTitle('');
      setNewIpAddress('');
      setNewDescription('');
      setIsAddingModality(false);
      const updated = await fetchModalities();
      setModalities(updated);
      setActionMessage(`Modality '${newAeTitle.toUpperCase()}' registered successfully.`);
    } catch (err: any) {
      alert(`Error registering modality: ${err.message}`);
    }
  };

  const handleToggleModality = async (aeTitle: string) => {
    try {
      const res = await toggleModality(aeTitle);
      const updated = await fetchModalities();
      setModalities(updated);
      setActionMessage(res.message);
    } catch (err: any) {
      alert(`Error toggling modality: ${err.message}`);
    }
  };

  const handleVerifyAuditChain = async () => {
    setIsVerifying(true);
    try {
      const res = await verifyAuditChain();
      setVerifyResult(res);
    } catch (err: any) {
      alert(`Audit verification error: ${err.message}`);
    } finally {
      setIsVerifying(false);
    }
  };

  const handleCheckpoint = async () => {
    setIsCheckpointing(true);
    try {
      const res = await triggerWalCheckpoint();
      setActionMessage(res.message);
    } catch (err: any) {
      alert(`Checkpoint error: ${err.message}`);
    } finally {
      setIsCheckpointing(false);
    }
  };

  const freeStoragePercent = telemetry?.storage?.free_percent ?? (health?.storage_free_percent ?? 0);
  const isStorageSafe = telemetry?.storage?.is_watermark_safe ?? (health?.is_storage_safe ?? true);

  return (
    <div className="min-h-screen flex flex-col bg-background text-foreground">
      {/* Top Navigation Bar */}
      <header className="border-b border-border bg-card/60 backdrop-blur px-6 py-4 flex items-center justify-between sticky top-0 z-50">
        <div className="flex items-center space-x-3">
          <div className="h-9 w-9 rounded-lg bg-primary/20 border border-primary/40 flex items-center justify-center text-primary">
            <Radio className="h-5 w-5 animate-pulse" />
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <h1 className="text-lg font-bold tracking-tight text-white">ProRadCS Edge Node</h1>
              <span className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary border border-primary/20 font-medium">
                {health?.version || 'v1.0.0-PROD'}
              </span>
            </div>
            <p className="text-xs text-muted-foreground">Zero-Trust Medical DICOM Ingestion &amp; WAN Relay Appliance</p>
          </div>
        </div>

        {/* Global Node Status Indicators */}
        <div className="flex items-center space-x-6 text-xs">
          <div className="flex items-center space-x-2">
            <span className={`h-2.5 w-2.5 rounded-full ${isStorageSafe ? 'bg-emerald-400 animate-ping' : 'bg-red-400 animate-ping'}`}></span>
            <span className="text-muted-foreground">SCP Port {health?.dicom_port || 104}:</span>
            <span className={`font-semibold ${isStorageSafe ? 'text-emerald-400' : 'text-red-400'}`}>
              {isStorageSafe ? 'ONLINE' : 'WATERMARK REJECT (0xA700)'}
            </span>
          </div>

          <div className="flex items-center space-x-2">
            <ShieldCheck className="h-4 w-4 text-primary" />
            <span className="text-muted-foreground">Account:</span>
            <span className="font-mono text-zinc-300">PacsServiceWorker</span>
          </div>

          <div className="flex items-center space-x-2">
            <HardDrive className="h-4 w-4 text-accent" />
            <span className="text-muted-foreground">Archive Free:</span>
            <span className={`font-semibold ${freeStoragePercent < 15 ? 'text-amber-400' : 'text-zinc-200'}`}>
              {freeStoragePercent.toFixed(1)}% Free
            </span>
          </div>

          <button
            onClick={handleCheckpoint}
            disabled={isCheckpointing}
            className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-card/60 hover:bg-card border border-border text-xs text-zinc-200 transition-colors"
            title="Force SQLite WAL checkpoint TRUNCATE to flush disk journal"
          >
            <Database className="h-3.5 w-3.5 text-primary" />
            <span>{isCheckpointing ? 'Checkpointing...' : 'WAL Checkpoint'}</span>
          </button>
        </div>
      </header>

      {/* Action Notification Banner */}
      {actionMessage && (
        <div className="bg-primary/10 border-b border-primary/30 px-6 py-2 flex items-center justify-between text-xs text-primary">
          <span>{actionMessage}</span>
          <button onClick={() => setActionMessage(null)} className="hover:text-white font-bold">&times;</button>
        </div>
      )}

      {/* Main Content Area */}
      <main className="flex-1 p-6 max-w-7xl mx-auto w-full space-y-6">
        {/* Navigation Tabs */}
        <div className="flex space-x-2 border-b border-border pb-2">
          {[
            { id: 'overview', label: 'Telemetry Overview', icon: Activity },
            { id: 'queue', label: 'Staging & Pipeline Queue', icon: Layers },
            { id: 'modalities', label: 'Modality Registry', icon: Server },
            { id: 'audit', label: 'Audit Trail (Hash-Chained)', icon: ShieldCheck },
          ].map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id as any)}
                className={`flex items-center space-x-2 px-4 py-2 rounded-lg text-xs font-medium transition-all ${
                  isActive
                    ? 'bg-primary/20 text-primary border border-primary/30 shadow-sm'
                    : 'text-muted-foreground hover:text-foreground hover:bg-card/40'
                }`}
              >
                <Icon className="h-4 w-4" />
                <span>{tab.label}</span>
              </button>
            );
          })}
        </div>

        {/* TAB 1: OVERVIEW */}
        {activeTab === 'overview' && (
          <div className="space-y-6">
            {/* Quick Stats Grid */}
            <section className="grid grid-cols-1 md:grid-cols-4 gap-4">
              <div className="glass-panel p-4 rounded-xl border border-border">
                <div className="flex items-center justify-between text-muted-foreground mb-2">
                  <span className="text-xs uppercase font-semibold tracking-wider">CPU Utilization</span>
                  <Cpu className="h-4 w-4 text-primary" />
                </div>
                <div className="text-2xl font-bold font-mono text-white">
                  {telemetry ? `${telemetry.cpu_percent.toFixed(1)}%` : '...'}
                </div>
                <p className="text-[11px] text-muted-foreground mt-1">Multi-core Transcoding Worker</p>
              </div>

              <div className="glass-panel p-4 rounded-xl border border-border">
                <div className="flex items-center justify-between text-muted-foreground mb-2">
                  <span className="text-xs uppercase font-semibold tracking-wider">Staged Queue</span>
                  <Layers className="h-4 w-4 text-accent" />
                </div>
                <div className="text-2xl font-bold font-mono text-white">
                  {telemetry ? telemetry.queues.staged_count : '0'}
                </div>
                <p className="text-[11px] text-muted-foreground mt-1">Pending background processing</p>
              </div>

              <div className="glass-panel p-4 rounded-xl border border-border">
                <div className="flex items-center justify-between text-muted-foreground mb-2">
                  <span className="text-xs uppercase font-semibold tracking-wider">Forwarded to Cloud</span>
                  <UploadCloud className="h-4 w-4 text-emerald-400" />
                </div>
                <div className="text-2xl font-bold font-mono text-white">
                  {telemetry ? telemetry.queues.forwarded_count : '0'}
                </div>
                <p className="text-[11px] text-muted-foreground mt-1">STOW-RS / HTTPS 443 Relay</p>
              </div>

              <div className="glass-panel p-4 rounded-xl border border-border">
                <div className="flex items-center justify-between text-muted-foreground mb-2">
                  <span className="text-xs uppercase font-semibold tracking-wider">Storage Free</span>
                  <Database className="h-4 w-4 text-amber-400" />
                </div>
                <div className="text-2xl font-bold font-mono text-white">
                  {freeStoragePercent.toFixed(1)}%
                </div>
                <p className="text-[11px] text-muted-foreground mt-1">NFR-002 Trigger Floor: &lt;10%</p>
              </div>
            </section>

            {/* Service Status Cards */}
            <section className="glass-panel rounded-xl p-6 border border-border space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold text-white tracking-wide flex items-center space-x-2">
                  <Server className="h-4 w-4 text-primary" />
                  <span>Decoupled Windows Background Services</span>
                </h2>
                <span className="text-xs text-muted-foreground font-mono">Managed via NSSM (SCM)</span>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-2">
                <div className="p-4 rounded-lg bg-card/40 border border-border flex items-start space-x-3">
                  <div className="p-2 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                    <Radio className="h-4 w-4" />
                  </div>
                  <div>
                    <p className="text-xs font-medium text-white">DicomReceiverService</p>
                    <p className="text-[11px] text-muted-foreground font-mono">Port {health?.dicom_port || 104} / pynetdicom</p>
                    <span className="inline-block mt-2 text-[10px] uppercase font-semibold px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300">
                      ONLINE (Port 104)
                    </span>
                  </div>
                </div>

                <div className="p-4 rounded-lg bg-card/40 border border-border flex items-start space-x-3">
                  <div className="p-2 rounded bg-accent/10 text-accent border border-accent/20">
                    <Layers className="h-4 w-4" />
                  </div>
                  <div>
                    <p className="text-xs font-medium text-white">ProcessorWorker</p>
                    <p className="text-[11px] text-muted-foreground font-mono">openjpeg + STOW-RS</p>
                    <span className="inline-block mt-2 text-[10px] uppercase font-semibold px-2 py-0.5 rounded bg-accent/20 text-accent">
                      ACTIVE ({telemetry?.queues?.processing_count ?? 0} Working)
                    </span>
                  </div>
                </div>

                <div className="p-4 rounded-lg bg-card/40 border border-border flex items-start space-x-3">
                  <div className="p-2 rounded bg-primary/10 text-primary border border-primary/20">
                    <Activity className="h-4 w-4" />
                  </div>
                  <div>
                    <p className="text-xs font-medium text-white">WebDashboardService</p>
                    <p className="text-[11px] text-muted-foreground font-mono">127.0.0.1:8080 / FastAPI</p>
                    <span className="inline-block mt-2 text-[10px] uppercase font-semibold px-2 py-0.5 rounded bg-primary/20 text-primary">
                      ONLINE
                    </span>
                  </div>
                </div>
              </div>
            </section>
          </div>
        )}

        {/* TAB 2: QUEUE */}
        {activeTab === 'queue' && (
          <section className="glass-panel rounded-xl p-6 border border-border space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-sm font-semibold text-white tracking-wide">DICOM Ingestion &amp; Relay Pipeline</h2>
                <p className="text-xs text-muted-foreground">Real-time status of instances progressing from STAGED to FORWARDED</p>
              </div>

              {/* Status Filter */}
              <div className="flex items-center space-x-2 text-xs">
                <span className="text-muted-foreground">Filter:</span>
                <select
                  value={queueStatusFilter}
                  onChange={(e) => setQueueStatusFilter(e.target.value)}
                  className="bg-card border border-border rounded px-2.5 py-1 text-xs text-zinc-200"
                >
                  <option value="">All States</option>
                  <option value="STAGED">STAGED</option>
                  <option value="PROCESSING">PROCESSING</option>
                  <option value="PROCESSED">PROCESSED</option>
                  <option value="UPLOADING">UPLOADING</option>
                  <option value="FORWARDED">FORWARDED</option>
                  <option value="FAILED">FAILED</option>
                  <option value="QUARANTINED">QUARANTINED</option>
                </select>
                <button
                  onClick={() => fetchQueue(queueStatusFilter || undefined).then(res => setInstances(res.instances))}
                  className="p-1.5 rounded bg-card hover:bg-card/80 border border-border text-muted-foreground hover:text-white"
                >
                  <RefreshCw className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>

            {/* Queue Table */}
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs border-collapse">
                <thead>
                  <tr className="border-b border-border text-muted-foreground font-medium">
                    <th className="py-2.5 px-3">SOP Instance UID</th>
                    <th className="py-2.5 px-3">Calling AE</th>
                    <th className="py-2.5 px-3">Size</th>
                    <th className="py-2.5 px-3">Pipeline Status</th>
                    <th className="py-2.5 px-3">Retries</th>
                    <th className="py-2.5 px-3">Received At</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/50 font-mono">
                  {instances.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="py-6 text-center text-muted-foreground">
                        No DICOM instances found in the selected queue filter.
                      </td>
                    </tr>
                  ) : (
                    instances.map((inst) => {
                      const statusColors: Record<string, string> = {
                        STAGED: 'bg-zinc-500/20 text-zinc-300 border-zinc-500/30',
                        PROCESSING: 'bg-accent/20 text-accent border-accent/30',
                        PROCESSED: 'bg-blue-500/20 text-blue-300 border-blue-500/30',
                        UPLOADING: 'bg-amber-500/20 text-amber-300 border-amber-500/30',
                        FORWARDED: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30',
                        FAILED: 'bg-red-500/20 text-red-300 border-red-500/30',
                        QUARANTINED: 'bg-purple-500/20 text-purple-300 border-purple-500/30',
                      };
                      return (
                        <tr key={inst.sop_instance_uid} className="hover:bg-card/40 transition-colors">
                          <td className="py-2.5 px-3 text-zinc-300 truncate max-w-xs" title={inst.sop_instance_uid}>
                            {inst.sop_instance_uid}
                          </td>
                          <td className="py-2.5 px-3 text-zinc-400">{inst.calling_ae_title}</td>
                          <td className="py-2.5 px-3 text-zinc-400">{(inst.file_size_bytes / 1024).toFixed(1)} KB</td>
                          <td className="py-2.5 px-3">
                            <span className={`inline-block px-2 py-0.5 rounded text-[10px] font-semibold border ${statusColors[inst.pipeline_status] || 'bg-zinc-800 text-zinc-400'}`}>
                              {inst.pipeline_status}
                            </span>
                          </td>
                          <td className="py-2.5 px-3 text-zinc-400">{inst.retry_count}</td>
                          <td className="py-2.5 px-3 text-zinc-400">{inst.received_at}</td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {/* TAB 3: MODALITIES */}
        {activeTab === 'modalities' && (
          <section className="glass-panel rounded-xl p-6 border border-border space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-sm font-semibold text-white tracking-wide">Modality Whitelist Registry</h2>
                <p className="text-xs text-muted-foreground">Authorized CT, MRI, and X-ray devices permitted to initiate C-STORE</p>
              </div>

              <button
                onClick={() => setIsAddingModality(!isAddingModality)}
                className="flex items-center space-x-1 px-3 py-1.5 rounded-lg bg-primary hover:bg-primary/90 text-primary-foreground text-xs font-medium transition-colors"
              >
                <Plus className="h-3.5 w-3.5" />
                <span>Register Modality</span>
              </button>
            </div>

            {/* Registration Form */}
            {isAddingModality && (
              <form onSubmit={handleAddModality} className="p-4 rounded-lg bg-card/60 border border-border space-y-3">
                <h3 className="text-xs font-semibold text-white">Register New Medical Modality</h3>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  <div>
                    <label className="block text-[11px] text-muted-foreground mb-1">AE Title (1-16 chars)</label>
                    <input
                      type="text"
                      maxLength={16}
                      required
                      placeholder="CT_SCANNER_02"
                      value={newAeTitle}
                      onChange={(e) => setNewAeTitle(e.target.value)}
                      className="w-full bg-background border border-border rounded px-3 py-1.5 text-xs text-zinc-200 uppercase font-mono"
                    />
                  </div>
                  <div>
                    <label className="block text-[11px] text-muted-foreground mb-1">IP Address</label>
                    <input
                      type="text"
                      required
                      placeholder="192.168.1.50 or *"
                      value={newIpAddress}
                      onChange={(e) => setNewIpAddress(e.target.value)}
                      className="w-full bg-background border border-border rounded px-3 py-1.5 text-xs text-zinc-200 font-mono"
                    />
                  </div>
                  <div>
                    <label className="block text-[11px] text-muted-foreground mb-1">Description</label>
                    <input
                      type="text"
                      placeholder="Emergency Room CT"
                      value={newDescription}
                      onChange={(e) => setNewDescription(e.target.value)}
                      className="w-full bg-background border border-border rounded px-3 py-1.5 text-xs text-zinc-200"
                    />
                  </div>
                </div>
                <div className="flex justify-end space-x-2 pt-2">
                  <button
                    type="button"
                    onClick={() => setIsAddingModality(false)}
                    className="px-3 py-1 rounded bg-card hover:bg-card/80 border border-border text-xs text-zinc-300"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="px-3 py-1 rounded bg-primary text-primary-foreground text-xs font-medium"
                  >
                    Save Modality
                  </button>
                </div>
              </form>
            )}

            {/* Modalities Table */}
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs border-collapse">
                <thead>
                  <tr className="border-b border-border text-muted-foreground font-medium">
                    <th className="py-2.5 px-3">AE Title</th>
                    <th className="py-2.5 px-3">IP Address</th>
                    <th className="py-2.5 px-3">Description</th>
                    <th className="py-2.5 px-3">Status</th>
                    <th className="py-2.5 px-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/50">
                  {modalities.map((mod) => (
                    <tr key={mod.ae_title} className="hover:bg-card/40 transition-colors">
                      <td className="py-2.5 px-3 font-mono font-bold text-white">{mod.ae_title}</td>
                      <td className="py-2.5 px-3 font-mono text-zinc-400">{mod.ip_address}</td>
                      <td className="py-2.5 px-3 text-zinc-400">{mod.description || '—'}</td>
                      <td className="py-2.5 px-3">
                        <span className={`inline-block px-2 py-0.5 rounded text-[10px] font-semibold ${mod.is_active ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' : 'bg-red-500/20 text-red-400 border border-red-500/30'}`}>
                          {mod.is_active ? 'ACTIVE' : 'DISABLED'}
                        </span>
                      </td>
                      <td className="py-2.5 px-3 text-right">
                        <button
                          onClick={() => handleToggleModality(mod.ae_title)}
                          className="px-2.5 py-1 rounded bg-card hover:bg-card/80 border border-border text-[11px] text-zinc-300"
                        >
                          {mod.is_active ? 'Disable' : 'Enable'}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {/* TAB 4: AUDIT */}
        {activeTab === 'audit' && (
          <section className="glass-panel rounded-xl p-6 border border-border space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-sm font-semibold text-white tracking-wide">HIPAA Cryptographic Chained Audit Trail</h2>
                <p className="text-xs text-muted-foreground">Immutable blockchain-style SHA-256 hash chaining with strict Zero-PHI</p>
              </div>

              <button
                onClick={handleVerifyAuditChain}
                disabled={isVerifying}
                className="flex items-center space-x-2 px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-medium transition-colors"
              >
                <FileCheck className="h-4 w-4" />
                <span>{isVerifying ? 'Verifying Hashes...' : 'Verify Chain Integrity'}</span>
              </button>
            </div>

            {/* Verification Result Banner */}
            {verifyResult && (
              <div className={`p-4 rounded-lg border text-xs flex items-center space-x-3 ${verifyResult.is_chain_intact ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300' : 'bg-red-500/10 border-red-500/30 text-red-300'}`}>
                {verifyResult.is_chain_intact ? (
                  <CheckCircle2 className="h-5 w-5 text-emerald-400 flex-shrink-0" />
                ) : (
                  <AlertCircle className="h-5 w-5 text-red-400 flex-shrink-0" />
                )}
                <div>
                  <p className="font-semibold">
                    {verifyResult.is_chain_intact ? 'Cryptographic Audit Trail Verified Intact' : 'Audit Chain Tampering Detected!'}
                  </p>
                  <p className="text-[11px] opacity-90">
                    {verifyResult.is_chain_intact
                      ? `All ${verifyResult.total_records_verified} cryptographic blocks verified from genesis. No broken links.`
                      : verifyResult.error_message}
                  </p>
                </div>
              </div>
            )}

            {/* Audit Log Table */}
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs border-collapse font-mono">
                <thead>
                  <tr className="border-b border-border text-muted-foreground font-sans font-medium">
                    <th className="py-2.5 px-3">ID</th>
                    <th className="py-2.5 px-3">Timestamp (UTC)</th>
                    <th className="py-2.5 px-3">Event Type</th>
                    <th className="py-2.5 px-3">Actor</th>
                    <th className="py-2.5 px-3">Patient Hash</th>
                    <th className="py-2.5 px-3">SHA-256 Digest</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/50 text-[11px]">
                  {auditLogs.map((log) => (
                    <tr key={log.log_id} className="hover:bg-card/40 transition-colors">
                      <td className="py-2.5 px-3 text-zinc-400 font-bold">#{log.log_id}</td>
                      <td className="py-2.5 px-3 text-zinc-400">{log.timestamp}</td>
                      <td className="py-2.5 px-3 text-primary font-semibold font-sans">{log.event_type}</td>
                      <td className="py-2.5 px-3 text-zinc-300">{log.actor}</td>
                      <td className="py-2.5 px-3 text-zinc-400">
                        {log.patient_hash ? `${log.patient_hash.substring(0, 10)}...` : 'NONE'}
                      </td>
                      <td className="py-2.5 px-3 text-emerald-400 truncate max-w-xs" title={log.current_hash}>
                        {log.current_hash.substring(0, 16)}...
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}
      </main>

      {/* Footer */}
      <footer className="border-t border-border px-6 py-3 text-center text-xs text-muted-foreground flex items-center justify-between max-w-7xl mx-auto w-full">
        <span>ProRadCS DICOM Gateway &bull; IEC 62304 Class B &bull; HIPAA PS 3.15 Conformance Profile</span>
        <span className="font-mono text-[11px]">Machine Security: PacsServiceWorker</span>
      </footer>
    </div>
  );
}
