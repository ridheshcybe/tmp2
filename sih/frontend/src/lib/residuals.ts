// ══════════════════════════════════════════════════════════════════════════════
// Aero Piston Engine Digital Twin — residual channel labels
// ══════════════════════════════════════════════════════════════════════════════
//
// The twin reports residuals keyed by channel (`r_cht_max`). These are the
// plain-language names used when showing them to an engineer, mirroring
// RESIDUAL_NAMES in ml/health_index.py.
// ══════════════════════════════════════════════════════════════════════════════

export const RESIDUAL_LABELS: Record<string, string> = {
  r_cht_avg: 'CHT residual (avg)',
  r_cht_max: 'CHT residual (worst cyl)',
  r_egt_avg: 'EGT residual (avg)',
  r_egt_max: 'EGT residual (worst cyl)',
  r_fuel: 'Fuel-flow residual',
  r_oil_p: 'Oil-pressure residual',
  r_oil_t: 'Oil-temperature residual',
  r_vib: 'Vibration residual',
  r_batt: 'Battery-voltage residual',
  r_alt: 'Alternator-current residual',
};
