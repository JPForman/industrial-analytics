// Mirrors the Pydantic response models in apps/api/app/schemas.py. Hand-written for now;
// generating them from /openapi.json (openapi-typescript) is the step up when the API grows.

export type Role = 'viewer' | 'engineer' | 'admin'
export type Severity = 'info' | 'warning' | 'critical'

export interface User {
  id: number
  email: string
  role: Role
}

export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface Asset {
  id: number
  name: string
  asset_type: string
  site: string
  edge_node_id: string
  device_id: string
  created_at: string
}

export interface Tag {
  id: number
  asset_id: number
  name: string
  unit: string
}

export interface Reading {
  ts: string
  value: number
}

export interface ReadingsPage {
  items: Reading[]
  next_cursor: string | null
}

export interface AggregateBucket {
  bucket: string
  avg: number
  min: number
  max: number
  count: number
}

export interface Alarm {
  id: number
  rule_id: number
  tag_id: number
  tag_name: string
  unit: string
  asset_id: number
  asset_name: string
  operator: 'gt' | 'lt'
  threshold: number
  severity: Severity
  value: number
  triggered_at: string
  cleared_at: string | null
  acknowledged_at: string | null
  acknowledged_by_id: number | null
}

/** Events pushed over WS /ws/live (see apps/api/app/mqtt_bridge.py). */
export type LiveEvent =
  | { type: 'reading'; tag_id: number; ts: string; value: number }
  | { type: 'alarm'; kind: 'open' | 'clear'; rule_id: number; tag_id: number; severity: Severity }
