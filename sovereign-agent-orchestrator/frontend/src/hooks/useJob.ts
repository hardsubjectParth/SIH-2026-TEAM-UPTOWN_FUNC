import { useEffect, useState } from 'react'
import useSWR from 'swr'
import { approveJob, cancelJob, getJob, listJobs, streamJobEvents } from '../services/api'
import type { JobEvent, JobStatus } from '../types/api'
import { useAuth } from '../context/AuthContext'

const TERMINAL: JobStatus[] = ['done', 'failed', 'cancelled']

// GET /agent?limit= -- a real aggregate endpoint the rebuild spec's §5 table didn't
// know about (it suggested "poll each known job_id" as a fallback). Used for the
// Agent Tasks page's stat row and list instead of that fallback.
export function useJobs(limit = 50) {
  const { token } = useAuth()
  const { data, error, isLoading } = useSWR(
    token ? ['jobs', token, limit] : null,
    ([, authToken, jobLimit]) => listJobs(authToken, jobLimit),
    { refreshInterval: 5000 },
  )
  return { jobs: data?.data ?? [], error, isLoading }
}

export function useJob(jobId?: string | null) {
  const { token } = useAuth()
  const { data, error, mutate } = useSWR(
    token && jobId ? ['job', jobId, token] : null,
    ([, id, authToken]) => getJob(id, authToken),
    { refreshInterval: (latest) => (latest && TERMINAL.includes(latest.status) ? 0 : 1200) },
  )
  return { job: data, error, mutate }
}

// Live SSE activity for one job. Cleans up its AbortController on jobId/unmount change --
// without that, submitting a second turn before the first job finishes leaks an open
// stream reader loop in the background indefinitely.
export function useJobEvents(jobId?: string | null) {
  const { token } = useAuth()
  const [events, setEvents] = useState<JobEvent[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!token || !jobId) return
    setEvents([])
    setError(null)
    const controller = new AbortController()
    streamJobEvents(jobId, token, (event) => setEvents((current) => [...current, event]), controller.signal).catch((cause) => {
      if (controller.signal.aborted) return
      setError(cause instanceof Error ? cause.message : 'Unable to connect to agent events')
    })
    return () => controller.abort()
  }, [jobId, token])

  return { events, error }
}

export function useApproveJob(jobId: string) {
  const { token } = useAuth()
  return (approved: boolean, reviewerUserId: string) => {
    if (!token) return Promise.reject(new Error('Not authenticated'))
    return approveJob(jobId, approved, reviewerUserId, token)
  }
}

export function useCancelJob(jobId: string) {
  const { token } = useAuth()
  return () => {
    if (!token) return Promise.reject(new Error('Not authenticated'))
    return cancelJob(jobId, token)
  }
}
