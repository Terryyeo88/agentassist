import { useState } from "react";
import { App } from "./App";
import { SourceSelector } from "./components/SourceSelector";
import { XeroUploadPanel } from "./components/XeroUploadPanel";

/** The bound input source for the review run. `null` until the user explicitly picks one. */
export type Source = "b1_demo" | "xero_upload";

/**
 * Root — the source gate. A review run starts with NO feeder bound: the app boots to a
 * SourceSelector empty state and the user explicitly picks the input source before anything
 * runs (no B1 oracle is shown first).
 *
 *   - source === null         → the SourceSelector chooser; nothing is fetched/run.
 *   - source === "b1_demo"    → mounts the EXISTING <App/> (the frozen SBODEMOSG review
 *                               surface, unchanged — it fetches GET /review + POST /command
 *                               on its own mount).
 *   - source === "xero_upload"→ mounts <XeroUploadPanel/> (upload → the engine RUNS on the
 *                               Xero-F5 / extract branches; findings render as candidates in the
 *                               shared review screen with adjudication, and Xero-F5 sign-off).
 *                               Sales/extract get decisions but no Sign button; a data-coverage
 *                               preview accompanies every upload.
 *
 * Box-isolation: the source choice only gates which surface mounts. The B1 F5 boxes still come
 * straight from the frozen GET /review and are never recomputed by the selector.
 */
export function Root() {
  const [source, setSource] = useState<Source | null>(null);

  if (source === null) {
    return <SourceSelector onPick={setSource} />;
  }
  if (source === "xero_upload") {
    return <XeroUploadPanel onChangeSource={() => setSource(null)} />;
  }
  return <App />;
}
