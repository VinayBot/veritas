import { useCallback, useEffect, useRef, useState } from 'react'
import { JOB_STREAM_URL, cancelJob, getJob, readSse, withAuth } from '@/lib/api/client'
import type { Job, JobStatus } from '@/lib/api/types'

export interface JobView {
  status: JobStatus | 'idle'
  /** 0..1, work actually completed as reported by the backend. */
  progress: number
  message: string | null
  result: Record<string, unknown> | null
  error: string | null
  active: boolean
  cancel: () => void
}

const TERMINAL: JobStatus[] = ['done', 'failed', 'cancelled']

/**
 * Follows a background job through its event stream. Progress is whatever the backend
 * reported, nothing interpolated. If the stream drops, the job's status is re-read so the
 * view never sits on a stale "running".
 */
export function useJob(jobId: string | null, onDone?: (job: Job) => void): JobView {
  const [status, setStatus] = useState<JobView['status']>('idle')
  const [progress, setProgress] = useState(0)
  const [message, setMessage] = useState<string | null>(null)
  const [result, setResult] = useState<Record<string, unknown> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const onDoneRef = useRef(onDone)
  onDoneRef.current = onDone

  useEffect(() => {
    if (!jobId) {
      setStatus('idle')
      return
    }
    let cancelled = false
    const controller = new AbortController()
    setStatus('queued')
    setProgress(0)
    setMessage('Queued')
    setResult(null)
    setError(null)

    const settle = async () => {
      try {
        const job = await getJob(jobId)
        if (cancelled) return
        setStatus(job.status)
        setProgress(job.progress)
        setMessage(job.message)
        setResult(job.result)
        setError(job.error)
        if (TERMINAL.includes(job.status)) onDoneRef.current?.(job)
        return job
      } catch (err) {
        if (!cancelled) {
          setStatus('failed')
          setError(err instanceof Error ? err.message : 'Could not read the job status')
        }
      }
    }

    const follow = async () => {
      try {
        const resp = await fetch(JOB_STREAM_URL(jobId), { signal: controller.signal, headers: withAuth() })
        await readSse(resp, (event, data) => {
          if (cancelled) return
          const payload = data as { progress?: number; message?: string; status?: JobStatus }
          if (event === 'status' && payload.status) setStatus(payload.status)
          if (event === 'progress') {
            setStatus((prev) => (prev === 'queued' && (payload.progress ?? 0) > 0 ? 'running' : prev))
            if (typeof payload.progress === 'number') setProgress(payload.progress)
            if (payload.message) setMessage(payload.message)
          }
        })
      } catch {
        // Aborted or dropped: fall through to reading the authoritative status.
      }
      if (cancelled) return
      const job = await settle()
      // The stream ended while the job was still going (a proxy timeout, say): keep following.
      if (job && !TERMINAL.includes(job.status) && !cancelled) window.setTimeout(() => void follow(), 1500)
    }
    void follow()

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [jobId])

  const cancel = useCallback(() => {
    if (jobId) void cancelJob(jobId).catch(() => {})
  }, [jobId])

  return {
    status,
    progress,
    message,
    result,
    error,
    active: status === 'queued' || status === 'running',
    cancel,
  }
}
