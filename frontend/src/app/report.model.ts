/** 与后端报告结构对应（只声明用到的字段）。 */

export interface SourcedValue {
  key: string;
  label: string;
  value: number | null;
  unit: string;
  available: boolean;
  reason_if_unavailable: string | null;
  formula: string | null;
  method: string | null;
  inputs: Record<string, unknown>;
  diagnostics: Record<string, any>;
  warnings: string[];
}

export interface ElasticFit {
  available: boolean;
  reason_if_unavailable: string | null;
  modulus_mpa: number | null;
  r2: number | null;
  rmse_mpa: number | null;
  residual_mpa: number[];
  used_indices: number[];
  interval_influence: {
    available: boolean;
    reason?: string;
    trim_points_each_side?: number;
    max_abs_drift_percent?: number;
    drift_percent?: Record<string, number>;
    full?: { modulus_mpa: number; r2: number; n_points: number };
  };
}

export interface CurveSeries {
  index: number[];
  time_s: number[];
  force_n: number[];
  crosshead_displacement_mm: number[];
  extensometer_displacement_mm: (number | null)[];
  engineering_stress_mpa: (number | null)[];
  engineering_strain: (number | null)[];
  true_stress_mpa: (number | null)[];
  true_strain: (number | null)[];
  valid_strain: boolean[];
}

export interface Report {
  report_id: string | null;
  specimen_id: string;
  generated_at: string;
  summary: Record<string, number | null>;
  results: SourcedValue[];
  elastic_fit: ElasticFit;
  offset_yield: {
    available: boolean;
    proof_stress_mpa: number | null;
    proof_strain: number | null;
    reason_if_unavailable: string | null;
    offset: number;
    index_a?: number;
    index_b?: number;
  };
  yield_plateau: {
    available: boolean;
    upper_yield_mpa: number | null;
    lower_yield_mpa: number | null;
    reason_if_unavailable: string | null;
  };
  series: CurveSeries;
  curve_limits: {
    max_force_index: number;
    fracture_index: number;
    true_curve_valid_until_index: number;
    extensometer_removed_at_index: number | null;
  };
  excluded_points: { index: number; reason: string; author: string;
                      created_at: string }[];
  plan: Record<string, any>;
  strain_source: string;
  warnings: string[];
  unavailable_reasons: string[];
}

export interface AnalyzeRequest {
  test_id: string;
  strain_source: 'extensometer' | 'crosshead';
  elastic_index_min: number | null;
  elastic_index_max: number | null;
  offset: number;
  min_elastic_points: number;
  r2_warning_threshold: number;
  notes?: string | null;
  excluded_points: { index: number; reason: string; author: string }[];
}

export interface TestItem {
  id: string;
  test_code: string;
  specimen_code: string;
}
