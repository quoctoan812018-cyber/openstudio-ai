import type { Job } from "@openstudio/protocol";
import { useCallback, useEffect, useRef, useState } from "react";
import { useApi } from "../api/connection";
import { subscribeEvents } from "../api/sse";
import { useI18n } from "../i18n";

/** Theo dõi job của một project qua SSE; gọi onChange khi job kết thúc hoặc state máy trạng thái đổi. */
export function useProjectJobs(pid: string, onChange: () => void) {
  const api = useApi();
  const [jobs, setJobs] = useState<Job[]>([]);
  const cb = useRef(onChange);
  cb.current = onChange;

  const refresh = useCallback(async () => {
    setJobs((await api.jobs(pid)).slice(0, 8));
  }, [api, pid]);

  useEffect(() => {
    void refresh().catch(() => undefined);
    const ctl = new AbortController();
    subscribeEvents(api.conn, { projectId: pid }, (e) => {
      if (e.type === "job.progress" && e.jobId) {
        setJobs((js) => js.map((j) => (j.id === e.jobId ? { ...j, status: "running", progress: e.data as Job["progress"] } : j)));
      } else if (e.type.startsWith("job.") || e.type === "state.changed") {
        void refresh().catch(() => undefined);
        cb.current();
      }
    }, ctl.signal);
    return () => ctl.abort();
  }, [api, pid, refresh]);

  return { jobs, refresh, running: jobs.some((j) => j.status === "running" || j.status === "queued") };
}

export function JobList({ jobs }: { jobs: Job[] }) {
  const { t } = useI18n();
  if (!jobs.length) return null;
  return (
    <ul className="mb-4 space-y-2 rounded-xl border border-zinc-200 p-3 dark:border-zinc-800" aria-label="jobs">
      {jobs.slice(0, 4).map((j) => {
        const p = j.progress;
        return (
          <li key={j.id} className="text-sm">
            <div className="flex justify-between">
              <span>{j.type} · {p?.message || p?.phase || j.status}</span>
              <span className={j.status === "failed" ? "text-red-600" : ""}>
                {j.status === "failed" ? j.error?.message : j.status === "succeeded" ? t("sub.done") : `${Math.round(p?.percent ?? 0)}%`}
              </span>
            </div>
            {(j.status === "running" || j.status === "queued") && <progress className="w-full" max={100} value={p?.percent ?? 0} />}
          </li>
        );
      })}
    </ul>
  );
}
