// ══════════════════════════════════════════════════════════════════════════════
// Aero Piston Engine Digital Twin - Telemetry Strip Charts
// ══════════════════════════════════════════════════════════════════════════════
//
// High-performance real-time streaming strip charts using Chart.js:
// - CHT spread (4 cylinders)
// - EGT spread (4 cylinders)
// - RPM & Fuel Flow
// - VAE Anomaly Reconstruction Loss
//
// ══════════════════════════════════════════════════════════════════════════════

import { useMemo } from 'react';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler,
  ChartOptions,
  ChartData,
} from 'chart.js';
import { Line } from 'react-chartjs-2';
import { useTelemetry } from '../../context/TelemetryContext';
import clsx from 'clsx';

// ══════════════════════════════════════════════════════════════════════════════
// Register Chart.js components
// ══════════════════════════════════════════════════════════════════════════════

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler
);

// ══════════════════════════════════════════════════════════════════════════════
// Types
// ══════════════════════════════════════════════════════════════════════════════

interface TelemetryStripChartsProps {
  className?: string;
  showAll?: boolean;
}

// ══════════════════════════════════════════════════════════════════════════════
// Constants
// ══════════════════════════════════════════════════════════════════════════════

const CHART_COLORS = {
  cyl1: '#06b6d4', // Cyan
  cyl2: '#f59e0b', // Amber
  cyl3: '#10b981', // Green
  cyl4: '#ef4444', // Red
  rpm: '#8b5cf6', // Purple
  fuelFlow: '#ec4899', // Pink
  anomaly: '#f97316', // Orange
};

const CHART_BG_COLORS = {
  cyl1: 'rgba(6, 182, 212, 0.1)',
  cyl2: 'rgba(245, 158, 11, 0.1)',
  cyl3: 'rgba(16, 185, 129, 0.1)',
  cyl4: 'rgba(239, 68, 68, 0.1)',
  rpm: 'rgba(139, 92, 246, 0.1)',
  fuelFlow: 'rgba(236, 72, 153, 0.1)',
  anomaly: 'rgba(249, 115, 22, 0.1)',
};

// ══════════════════════════════════════════════════════════════════════════════
// Shared Chart Options
// ══════════════════════════════════════════════════════════════════════════════

const baseChartOptions: ChartOptions<'line'> = {
  responsive: true,
  maintainAspectRatio: false,
  animation: {
    duration: 0, // Disable animation for real-time performance
  },
  interaction: {
    intersect: false,
    mode: 'index',
  },
  plugins: {
    legend: {
      display: true,
      position: 'top',
      labels: {
        color: '#9ca3af',
        font: {
          family: 'JetBrains Mono, monospace',
          size: 10,
        },
        boxWidth: 12,
        padding: 8,
      },
    },
    tooltip: {
      backgroundColor: 'rgba(17, 24, 39, 0.95)',
      titleColor: '#f3f4f6',
      bodyColor: '#d1d5db',
      borderColor: '#374151',
      borderWidth: 1,
      titleFont: {
        family: 'JetBrains Mono, monospace',
      },
      bodyFont: {
        family: 'JetBrains Mono, monospace',
      },
      padding: 10,
      displayColors: true,
    },
  },
  scales: {
    x: {
      display: true,
      grid: {
        color: 'rgba(31, 41, 55, 0.5)',
      },
      ticks: {
        color: '#6b7280',
        font: {
          family: 'JetBrains Mono, monospace',
          size: 9,
        },
        maxTicksLimit: 10,
      },
    },
    y: {
      display: true,
      grid: {
        color: 'rgba(31, 41, 55, 0.5)',
      },
      ticks: {
        color: '#6b7280',
        font: {
          family: 'JetBrains Mono, monospace',
          size: 10,
        },
      },
    },
  },
  elements: {
    point: {
      radius: 0,
      hoverRadius: 4,
    },
    line: {
      borderWidth: 1.5,
      tension: 0.3,
    },
  },
};

// ══════════════════════════════════════════════════════════════════════════════
// Generic Strip Chart Component
// ══════════════════════════════════════════════════════════════════════════════

interface StripChartProps {
  title: string;
  data: ChartData<'line'>;
  options?: ChartOptions<'line'>;
  height?: number;
}

function StripChart({ title, data, options, height = 150 }: StripChartProps) {
  return (
    <div className="hud-panel">
      <h3 className="text-xs font-medium text-cockpit-muted mb-2">{title}</h3>
      <div style={{ height }}>
        <Line data={data} options={options} />
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// Main Component
// ══════════════════════════════════════════════════════════════════════════════

export default function TelemetryStripCharts({
  className,
  showAll = true,
}: TelemetryStripChartsProps) {
  const { frameHistory } = useTelemetry();
  
  // Generate time labels
  const timeLabels = useMemo(() => {
    return frameHistory.map((_, i) => {
      const secondsAgo = (frameHistory.length - 1 - i) * 0.1;
      return `-${secondsAgo.toFixed(0)}s`;
    });
  }, [frameHistory.length]);
  
  // ─── CHT Chart Data ────────────────────────────────────────────────────
  
  const chtData: ChartData<'line'> = useMemo(() => ({
    labels: timeLabels,
    datasets: [
      {
        label: 'CHT 1',
        data: frameHistory.map((f) => f.cht?.[0] ?? null),
        borderColor: CHART_COLORS.cyl1,
        backgroundColor: CHART_BG_COLORS.cyl1,
        fill: false,
      },
      {
        label: 'CHT 2',
        data: frameHistory.map((f) => f.cht?.[1] ?? null),
        borderColor: CHART_COLORS.cyl2,
        backgroundColor: CHART_BG_COLORS.cyl2,
        fill: false,
      },
      {
        label: 'CHT 3',
        data: frameHistory.map((f) => f.cht?.[2] ?? null),
        borderColor: CHART_COLORS.cyl3,
        backgroundColor: CHART_BG_COLORS.cyl3,
        fill: false,
      },
      {
        label: 'CHT 4',
        data: frameHistory.map((f) => f.cht?.[3] ?? null),
        borderColor: CHART_COLORS.cyl4,
        backgroundColor: CHART_BG_COLORS.cyl4,
        fill: false,
      },
    ],
  }), [frameHistory, timeLabels]);
  
  const chtOptions: ChartOptions<'line'> = useMemo(() => ({
    ...baseChartOptions,
    scales: {
      ...baseChartOptions.scales,
      y: {
        ...baseChartOptions.scales?.y,
        min: 100,
        max: 280,
        title: {
          display: true,
          text: '°C',
          color: '#6b7280',
          font: { size: 10 },
        },
      },
    },
  }), []);
  
  // ─── EGT Chart Data ────────────────────────────────────────────────────
  
  const egtData: ChartData<'line'> = useMemo(() => ({
    labels: timeLabels,
    datasets: [
      {
        label: 'EGT 1',
        data: frameHistory.map((f) => f.egt?.[0] ?? null),
        borderColor: CHART_COLORS.cyl1,
        backgroundColor: CHART_BG_COLORS.cyl1,
        fill: false,
      },
      {
        label: 'EGT 2',
        data: frameHistory.map((f) => f.egt?.[1] ?? null),
        borderColor: CHART_COLORS.cyl2,
        backgroundColor: CHART_BG_COLORS.cyl2,
        fill: false,
      },
      {
        label: 'EGT 3',
        data: frameHistory.map((f) => f.egt?.[2] ?? null),
        borderColor: CHART_COLORS.cyl3,
        backgroundColor: CHART_BG_COLORS.cyl3,
        fill: false,
      },
      {
        label: 'EGT 4',
        data: frameHistory.map((f) => f.egt?.[3] ?? null),
        borderColor: CHART_COLORS.cyl4,
        backgroundColor: CHART_BG_COLORS.cyl4,
        fill: false,
      },
    ],
  }), [frameHistory, timeLabels]);
  
  const egtOptions: ChartOptions<'line'> = useMemo(() => ({
    ...baseChartOptions,
    scales: {
      ...baseChartOptions.scales,
      y: {
        ...baseChartOptions.scales?.y,
        min: 400,
        max: 950,
        title: {
          display: true,
          text: '°C',
          color: '#6b7280',
          font: { size: 10 },
        },
      },
    },
  }), []);
  
  // ─── RPM & Fuel Flow Chart Data ────────────────────────────────────────
  
  const rpmFuelData: ChartData<'line'> = useMemo(() => ({
    labels: timeLabels,
    datasets: [
      {
        label: 'RPM',
        data: frameHistory.map((f) => f.rpm ?? null),
        borderColor: CHART_COLORS.rpm,
        backgroundColor: CHART_BG_COLORS.rpm,
        fill: false,
        yAxisID: 'y',
      },
      {
        label: 'Fuel Flow (L/hr)',
        data: frameHistory.map((f) => f.fuel_flow_lph ?? null),
        borderColor: CHART_COLORS.fuelFlow,
        backgroundColor: CHART_BG_COLORS.fuelFlow,
        fill: false,
        yAxisID: 'y1',
      },
    ],
  }), [frameHistory, timeLabels]);
  
  const rpmFuelOptions: ChartOptions<'line'> = useMemo(() => ({
    ...baseChartOptions,
    scales: {
      ...baseChartOptions.scales,
      y: {
        ...baseChartOptions.scales?.y,
        position: 'left',
        min: 0,
        max: 3200,
        title: {
          display: true,
          text: 'RPM',
          color: CHART_COLORS.rpm,
          font: { size: 10 },
        },
      },
      y1: {
        ...baseChartOptions.scales?.y,
        position: 'right',
        min: 0,
        max: 30,
        grid: {
          drawOnChartArea: false,
        },
        title: {
          display: true,
          text: 'L/hr',
          color: CHART_COLORS.fuelFlow,
          font: { size: 10 },
        },
      },
    },
  }), []);
  
  // ─── Anomaly Score Chart Data ──────────────────────────────────────────
  
  const anomalyData: ChartData<'line'> = useMemo(() => ({
    labels: timeLabels,
    datasets: [
      {
        label: 'Anomaly Score',
        data: frameHistory.map((f) => f.anomaly?.score ?? null),
        borderColor: CHART_COLORS.anomaly,
        backgroundColor: CHART_BG_COLORS.anomaly,
        fill: true,
      },
      {
        label: 'Threshold',
        data: frameHistory.map(() => 50),
        borderColor: 'rgba(239, 68, 68, 0.5)',
        borderDash: [5, 5],
        pointRadius: 0,
        fill: false,
      },
    ],
  }), [frameHistory, timeLabels]);
  
  const anomalyOptions: ChartOptions<'line'> = useMemo(() => ({
    ...baseChartOptions,
    scales: {
      ...baseChartOptions.scales,
      y: {
        ...baseChartOptions.scales?.y,
        min: 0,
        max: 100,
        title: {
          display: true,
          text: 'Score',
          color: '#6b7280',
          font: { size: 10 },
        },
      },
    },
  }), []);
  
  // ─── Render ────────────────────────────────────────────────────────────
  
  return (
    <div className={clsx('space-y-4', className)}>
      {showAll && (
        <>
          {/* CHT Chart */}
          <StripChart
            title="Cylinder Head Temperature (CHT)"
            data={chtData}
            options={chtOptions}
            height={160}
          />
          
          {/* EGT Chart */}
          <StripChart
            title="Exhaust Gas Temperature (EGT)"
            data={egtData}
            options={egtOptions}
            height={160}
          />
          
          {/* RPM & Fuel Flow Chart */}
          <StripChart
            title="RPM & Fuel Flow"
            data={rpmFuelData}
            options={rpmFuelOptions}
            height={160}
          />
          
          {/* Anomaly Score Chart */}
          <StripChart
            title="VAE Anomaly Reconstruction Loss"
            data={anomalyData}
            options={anomalyOptions}
            height={120}
          />
        </>
      )}
    </div>
  );
}
