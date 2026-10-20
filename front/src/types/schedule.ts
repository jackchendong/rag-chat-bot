export interface ScheduledTask {
  id: string
  conversation_id: string
  name: string
  prompt: string
  kind: 'once' | 'cron'
  timezone: string
  cron: string | null
  run_at: string | null
  status: string
  next_run_at: string | null
  created_at: string
}

export interface ScheduledRun {
  id: string
  task_id: string
  source: string
  status: string
  prompt: string
  scheduled_at: string
  started_at: string | null
  finished_at: string | null
  assistant_message_id: string | null
  error: string | null
  message_status: string | null
  result_preview: string | null
  result_truncated: boolean
}

export interface ScheduleInput {
  name: string
  prompt: string
  kind: 'once' | 'cron'
  timezone: string
  cron: string | null
  run_at: string | null
}
