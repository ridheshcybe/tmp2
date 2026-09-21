// ══════════════════════════════════════════════════════════════════════════════
// AeroTwin — Cutaway Engine Twin
// ══════════════════════════════════════════════════════════════════════════════
//
// Hosts the cutaway engine viewer inside the cockpit and drives it from the
// live twin state.
//
// The viewer (public/cutaway/index.html) is a complete Three.js application in
// its own right: an STL engine block and piston, a section plane, a bloom pass,
// thirteen systems that can be stripped off the engine one stage at a time, and
// per-part tooltips. It is hosted as-is and spoken to over postMessage, through
// public/cutaway/aerotwin-bridge.js, rather than reimplemented as React Three
// Fiber components.
//
// Two specific reasons for hosting rather than bundling:
//
//  1. The viewer is global r128-era Three.js (`THREE.STLLoader`,
//     `THREE.OrbitControls`) while this app bundles three 0.169 as ES modules.
//     Both in one page would mean two Three.js copies fighting over globals.
//  2. The bridge has to run *inside* the viewer's document. The viewer's state
//     (`TUNE`, `SYSTEMS`, `scene`, `applySystemCut`, `pickAt`) is declared with
//     top-level `const`/`let`, which makes it a lexical global of that document
//     — reachable by another script in the page, but not a property of
//     `contentWindow`, so this component cannot touch it directly.
//
// Everything operational — health, faults, RUL, charts — still comes from the
// shared cockpit context, so this view sits on the same live stream as the rest
// of the dashboard.
// ══════════════════════════════════════════════════════════════════════════════

import { useCallback, useEffect, useRef, useState } from 'react';
import clsx from 'clsx';
import { Box, Gauge, Radio, RefreshCw, RotateCcw, Thermometer, TriangleAlert } from 'lucide-react';

import { useTelemetry } from '../../context/TelemetryContext';
import { HEALTH_CATEGORY_STYLES, faultLabel, phaseLabel } from '../../lib/adapters';

// ─── Viewer wiring ─────────────────────────────────────────────────────────────

const VIEWER_URL = '/cutaway/index.html';
const BRIDGE_URL = '/cutaway/aerotwin-bridge.js';

/** What the viewer reports once its model has loaded. */
interface BridgeReady {
  /** Cylinder groups carrying their own CP session tint. */
  cylinders: number;
  /** Visible systems tinted from the hottest cylinder. */
  systems: number;
  ready: boolean;
}

interface PickedPart {
  system: string;
  cyl: number | null;
}

interface CutawayTwinViewProps {
  className?: string;
  showControls?: boolean;
}

// ══════════════════════════════════════════════════════════════════════════════

export default function CutawayTwinView({
  className,
  showControls = true,
}: CutawayTwinViewProps) {

  const { currentFrame, connectionStatus } = useTelemetry();

  const iframeRef = useRef<HTMLIFrameElement>(null);

  const [reloadKey, setReloadKey] = useState(0);
  const [bridge, setBridge] = useState<BridgeReady | null>(null);
  const [picked, setPicked] = useState<PickedPart | null>(null);

  /*  Demo controls: whether the crank follows the live RPM, and whether the
      cylinders are tinted by their head temperature.  */
  const [followRpm, setFollowRpm] = useState(true);
  const [heatmap, setHeatmap] = useState(true);

  // ─── Bridge injection ────────────────────────────────────────────────────

  const injectBridge = useCallback(() => {

    const doc = iframeRef.current?.contentDocument;

    if (!doc || doc.getElementById('aerotwin-bridge')) return;

    const script = doc.createElement('script');

    script.id = 'aerotwin-bridge';
    script.src = BRIDGE_URL;

    (doc.head ?? doc.body).appendChild(script);
  }, []);

  /*
    Inject on load, and keep trying until the bridge is actually in.

    Relying on the load event alone is not enough: it can land before this
    component has attached its handler (and a cached iframe may already be
    loaded by the time React mounts), which leaves the viewer running with no
    bridge at all - driven by nothing, and reporting nothing back.  Injecting
    is idempotent, so retrying is free.
  */
  useEffect(() => {

    injectBridge();

    const timer = setInterval(() => {
      if (bridge) { clearInterval(timer); return; }
      injectBridge();
    }, 400);

    return () => clearInterval(timer);
  }, [injectBridge, bridge, reloadKey]);

  // ─── Messages from the viewer ────────────────────────────────────────────

  useEffect(() => {

    const onMessage = (event: MessageEvent) => {

      /*  Same origin only: the viewer is served by this app.  */
      if (event.origin !== window.location.origin) return;

      const data = event.data as { type?: string; payload?: unknown } | null;

      if (!data || typeof data.type !== 'string') return;

      if (data.type === 'AEROTWIN_READY') {
        setBridge((data.payload as BridgeReady) ?? { cylinders: 0, systems: 0, ready: false });
      } else if (data.type === 'AEROTWIN_PICK') {
        setPicked((data.payload as PickedPart | null) ?? null);
      }
    };

    window.addEventListener('message', onMessage);

    return () => window.removeEventListener('message', onMessage);
  }, []);

  // ─── Live telemetry -> viewer ────────────────────────────────────────────

  useEffect(() => {

    if (!bridge || !currentFrame) return;

    const win = iframeRef.current?.contentWindow;

    if (!win) return;

    win.postMessage(
      {
        type: 'AEROTWIN_TELEMETRY',
        payload: currentFrame,
        options: { followRpm, heatmap },
      },
      window.location.origin,
    );
  }, [currentFrame, bridge, followRpm, heatmap]);

  // ─── Derived display values ──────────────────────────────────────────────

  const health = currentFrame?.health;
  const style = HEALTH_CATEGORY_STYLES[health?.status ?? 'NORMAL'] ?? HEALTH_CATEGORY_STYLES.NORMAL;

  const maxCht = currentFrame?.cht?.length ? Math.max(...currentFrame.cht) : null;
  const maxEgt = currentFrame?.egt?.length ? Math.max(...currentFrame.egt) : null;
  const live = connectionStatus === 'CONNECTED' && Boolean(currentFrame);

  return (
    <div className={clsx('relative w-full h-full', className)}>

      {/* ─── The viewer ─── */}
      <iframe
        key={reloadKey}
        ref={iframeRef}
        src={VIEWER_URL}
        title="AeroTwin cutaway engine"
        onLoad={injectBridge}
        className="w-full h-full border-0 bg-[#0b0f19]"
        /*  The viewer is local, same-origin content; it needs no sandbox
            relaxation beyond being allowed to run its own scripts.  */
      />

      {/* ─── Live state, over the viewer ─── */}
      <div className="absolute top-4 left-4 flex flex-col gap-2 pointer-events-none">

        <div className="glass-card px-3 py-2 flex items-center gap-3">
          <Radio className={clsx('w-4 h-4', live ? 'text-nominal-green' : 'text-alert-red')} />
          <div className="text-xs">
            <p className="text-cockpit-muted">
              {live ? 'Live twin' : connectionStatus === 'CONNECTED' ? 'Waiting for frames' : 'Backend offline'}
            </p>
            <p className="data-display text-white">
              {currentFrame ? `frame ${currentFrame.frame_id} · ${phaseLabel(currentFrame.phase)}` : '---'}
            </p>
          </div>
        </div>

        {currentFrame && (
          <div className="glass-card px-3 py-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
            <span className="text-cockpit-muted flex items-center gap-1">
              <Gauge className="w-3 h-3" /> RPM
            </span>
            <span className="data-display text-hud-amber text-right">
              {currentFrame.rpm.toFixed(0)}
            </span>

            <span className="text-cockpit-muted flex items-center gap-1">
              <Thermometer className="w-3 h-3" /> CHT max
            </span>
            <span className="data-display text-white text-right">
              {maxCht !== null ? `${maxCht.toFixed(0)}°C` : '---'}
            </span>

            <span className="text-cockpit-muted">EGT max</span>
            <span className="data-display text-white text-right">
              {maxEgt !== null ? `${maxEgt.toFixed(0)}°C` : '---'}
            </span>

            <span className="text-cockpit-muted">Health index</span>
            <span className={clsx('data-display text-right', style.text)}>
              {health ? `${health.ehi.toFixed(0)}/100` : '---'}
            </span>
          </div>
        )}

        {currentFrame?.injected_fault && (
          <div className="glass-card px-3 py-2 border border-alert-red/60 flex items-center gap-2">
            <TriangleAlert className="w-4 h-4 text-alert-red animate-pulse" />
            <div className="text-xs">
              <p className="text-alert-red font-medium">Injected fault</p>
              <p className="text-white">{faultLabel(currentFrame.injected_fault)}</p>
            </div>
          </div>
        )}
      </div>

      {/* ─── Health + selection, bottom right ─── */}
      <div className="absolute top-4 right-4 flex flex-col items-end gap-2">

        {health && (
          <div className={clsx('glass-card px-3 py-2 border text-right', style.badge)}>
            <p className="text-[10px] text-cockpit-muted">Engine health</p>
            <p className={clsx('data-display text-lg', style.text)}>
              {health.ehi.toFixed(0)}
              <span className="text-xs text-cockpit-muted">/100</span>
            </p>
            <p className={clsx('text-xs font-medium', style.text)}>{health.status}</p>
          </div>
        )}

        {picked && (
          <div className="glass-card px-3 py-2 text-right text-xs">
            <p className="text-cockpit-muted">Selected</p>
            <p className="text-white">
              {picked.system}
              {picked.cyl ? ` · cylinder ${picked.cyl}` : ''}
            </p>
          </div>
        )}
      </div>

      {/* ─── Controls ─── */}
      {showControls && (
        <div className="absolute bottom-4 left-4 right-4 flex flex-wrap items-center gap-2">

          <div className="glass-card p-2 flex items-center gap-3 text-xs">

            <label className="flex items-center gap-2 cursor-pointer" title="Drive the crankshaft from the live RPM">
              <input
                type="checkbox"
                checked={followRpm}
                onChange={(e) => setFollowRpm(e.target.checked)}
                className="accent-cyber-cyan"
              />
              <span className="text-cockpit-muted">Follow live RPM</span>
            </label>

            <label className="flex items-center gap-2 cursor-pointer" title="Tint each cylinder by its head temperature">
              <input
                type="checkbox"
                checked={heatmap}
                onChange={(e) => setHeatmap(e.target.checked)}
                className="accent-cyber-cyan"
              />
              <span className="text-cockpit-muted">CHT heatmap</span>
            </label>

            <button
              onClick={() => { setBridge(null); setReloadKey((k) => k + 1); }}
              className="p-1.5 rounded bg-cockpit-surface hover:bg-cockpit-border transition-colors"
              title="Reload the viewer"
            >
              <RefreshCw className="w-3.5 h-3.5 text-cockpit-muted" />
            </button>
          </div>

          <div className="glass-card px-3 py-2 flex items-center gap-2 text-xs">
            <Box className={clsx('w-4 h-4', bridge?.ready ? 'text-cyber-cyan' : 'text-cockpit-muted')} />
            <span className="text-cockpit-muted">
              {bridge
                ? bridge.ready
                  ? `${bridge.cylinders} cylinders · ${bridge.systems} systems tinted`
                  : 'model not indexed'
                : 'loading viewer...'}
            </span>
          </div>

          {!followRpm && (
            <div className="glass-card px-3 py-2 flex items-center gap-2 text-xs">
              <RotateCcw className="w-3.5 h-3.5 text-hud-amber" />
              <span className="text-cockpit-muted">Crank on the viewer's own Speed slider</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
