import { useState } from 'react';
import { 
  Activity, 
  Server, 
  Database, 
  HardDrive, 
  ShieldCheck, 
  UploadCloud, 
  Radio, 
  Layers
} from 'lucide-react';

export default function App() {
  const [activeTab, setActiveTab] = useState<'overview' | 'queue' | 'modalities' | 'audit'>('overview');

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
                v1.0.0-PROD
              </span>
            </div>
            <p className="text-xs text-muted-foreground">Zero-Trust Medical DICOM Ingestion & WAN Relay Appliance</p>
          </div>
        </div>

        {/* Global Node Status Indicators */}
        <div className="flex items-center space-x-6 text-xs">
          <div className="flex items-center space-x-2">
            <span className="h-2 w-2 rounded-full bg-emerald-400 animate-ping"></span>
            <span className="h-2 w-2 rounded-full bg-emerald-500 -ml-4"></span>
            <span className="text-muted-foreground">SCP Port 104:</span>
            <span className="font-semibold text-emerald-400">ONLINE</span>
          </div>

          <div className="flex items-center space-x-2">
            <ShieldCheck className="h-4 w-4 text-primary" />
            <span className="text-muted-foreground">Account:</span>
            <span className="font-mono text-zinc-300">PacsServiceWorker</span>
          </div>

          <div className="flex items-center space-x-2">
            <HardDrive className="h-4 w-4 text-accent" />
            <span className="text-muted-foreground">Archive:</span>
            <span className="font-semibold text-zinc-200">D:\DICOM_Archive (84% Free)</span>
          </div>
        </div>
      </header>

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

        {/* Quick Stats Grid */}
        <section className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div className="glass-panel p-4 rounded-xl border border-border">
            <div className="flex items-center justify-between text-muted-foreground mb-2">
              <span className="text-xs uppercase font-semibold tracking-wider">Active Associations</span>
              <Activity className="h-4 w-4 text-primary" />
            </div>
            <div className="text-2xl font-bold font-mono text-white">0</div>
            <p className="text-[11px] text-muted-foreground mt-1">DIMSE C-STORE / C-ECHO SCP</p>
          </div>

          <div className="glass-panel p-4 rounded-xl border border-border">
            <div className="flex items-center justify-between text-muted-foreground mb-2">
              <span className="text-xs uppercase font-semibold tracking-wider">Staged Instances</span>
              <Layers className="h-4 w-4 text-accent" />
            </div>
            <div className="text-2xl font-bold font-mono text-white">0</div>
            <p className="text-[11px] text-muted-foreground mt-1">Pending background processing</p>
          </div>

          <div className="glass-panel p-4 rounded-xl border border-border">
            <div className="flex items-center justify-between text-muted-foreground mb-2">
              <span className="text-xs uppercase font-semibold tracking-wider">Forwarded to Cloud</span>
              <UploadCloud className="h-4 w-4 text-emerald-400" />
            </div>
            <div className="text-2xl font-bold font-mono text-white">0</div>
            <p className="text-[11px] text-muted-foreground mt-1">STOW-RS / TLS 1.3 Relay</p>
          </div>

          <div className="glass-panel p-4 rounded-xl border border-border">
            <div className="flex items-center justify-between text-muted-foreground mb-2">
              <span className="text-xs uppercase font-semibold tracking-wider">Storage Watermark</span>
              <Database className="h-4 w-4 text-amber-400" />
            </div>
            <div className="text-2xl font-bold font-mono text-white">16.2%</div>
            <p className="text-[11px] text-muted-foreground mt-1">Safety trigger: &gt;90% triggers 0xA700</p>
          </div>
        </section>

        {/* Telemetry Panel */}
        <section className="glass-panel rounded-xl p-6 border border-border space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-white tracking-wide flex items-center space-x-2">
              <Server className="h-4 w-4 text-primary" />
              <span>Edge Node Service Status</span>
            </h2>
            <span className="text-xs text-muted-foreground font-mono">SQLite WAL Mode Active</span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-2">
            <div className="p-4 rounded-lg bg-card/40 border border-border flex items-start space-x-3">
              <div className="p-2 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                <Radio className="h-4 w-4" />
              </div>
              <div>
                <p className="text-xs font-medium text-white">DicomReceiverService</p>
                <p className="text-[11px] text-muted-foreground font-mono">Port 104 / pynetdicom</p>
                <span className="inline-block mt-2 text-[10px] uppercase font-semibold px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300">
                  Ready (Standby)
                </span>
              </div>
            </div>

            <div className="p-4 rounded-lg bg-card/40 border border-border flex items-start space-x-3">
              <div className="p-2 rounded bg-accent/10 text-accent border border-accent/20">
                <Layers className="h-4 w-4" />
              </div>
              <div>
                <p className="text-xs font-medium text-white">ProcessorWorker</p>
                <p className="text-[11px] text-muted-foreground font-mono">pylibjpeg + STOW-RS</p>
                <span className="inline-block mt-2 text-[10px] uppercase font-semibold px-2 py-0.5 rounded bg-accent/20 text-accent">
                  Ready (Standby)
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
                  Active
                </span>
              </div>
            </div>
          </div>
        </section>
      </main>

      {/* Footer */}
      <footer className="border-t border-border px-6 py-3 text-center text-xs text-muted-foreground">
        ProRadCS DICOM Gateway &bull; IEC 62304 Class B &bull; HIPAA PS 3.15 Conformance Profile
      </footer>
    </div>
  );
}
