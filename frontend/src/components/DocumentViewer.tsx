import { useEffect, useState } from "react";

export function DocumentViewer({ docNum, onClose }: { docNum: number; onClose: () => void }) {
  const [state, setState] = useState<"loading" | "ready" | "absent" | "error">("loading");
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let objUrl: string | null = null;
    let cancelled = false;
    setState("loading"); setUrl(null);
    fetch(`/api/document/${docNum}`)
      .then(async (r) => {
        if (cancelled) return;
        if (r.status === 404) return setState("absent");
        if (!r.ok) return setState("error");
        const blob = await r.blob();
        if (cancelled) return;
        objUrl = URL.createObjectURL(blob);
        setUrl(objUrl); setState("ready");
      })
      .catch(() => { if (!cancelled) setState("error"); });
    return () => { cancelled = true; if (objUrl) URL.revokeObjectURL(objUrl); };
  }, [docNum]);
  return (
    <aside className="doc-viewer" aria-label="Source document">
      <div className="doc-viewer-head">
        Source document · <span className="mono">Doc {docNum}</span>
        <button className="link" onClick={onClose}>Close</button>
      </div>
      {state === "loading" && <div className="loading">Loading source document…</div>}
      {state === "absent" && <div className="callout warn">No source document on file for this finding.</div>}
      {state === "error" && <div className="callout warn">Couldn’t load the source document.</div>}
      {state === "ready" && url && (
        <object data={url} type="application/pdf" className="doc-frame" aria-label={`Invoice ${docNum}`} />
      )}
    </aside>
  );
}
