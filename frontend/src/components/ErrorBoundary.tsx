import { Component, type ErrorInfo, type ReactNode } from "react";

/**
 * ErrorBoundary — G-2. A render-time throw must cost you one pane, never the whole app.
 *
 * D-47 was this failure exactly: FindingDetail read `completeness.required` on a null, React
 * unmounted the tree, and a user got a white screen. That was closed with one local null
 * guard; the CLASS stayed open, because nothing in the tree caught render errors at all.
 *
 * What the fallback is allowed to say is deliberately narrow. It knows ONE thing: this view
 * did not render. It does not know whether the data is sound, whether a review is complete,
 * or whether anything was filed — and a reassurance it cannot support ("nothing was lost",
 * "your review is saved") would be exactly the kind of claim this product does not make.
 * A3-T5 pins that: the fallback text is asserted NOT to contain filing, validity or
 * completeness language.
 *
 * Reload is offered rather than a silent in-place retry: the state that produced the throw is
 * still in memory, so re-rendering the same subtree would usually throw again. A full reload
 * is the honest remedy, and the reviewer chooses when to take it.
 *
 * Boundaries are intentionally placed at TWO depths (main.tsx around the app, ReviewScreen
 * around the finding-detail pane) so that one malformed finding leaves the queue beside it
 * usable — A3-T7.
 */

type Props = {
  /** Names the failed surface in plain words, e.g. "the review screen", "this finding". */
  label: string;
  children: ReactNode;
};

type State = { error: Error | null };

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Keep the component stack in the console for whoever is debugging; the UI stays plain.
    // eslint-disable-next-line no-console
    console.error(`[ErrorBoundary] ${this.props.label} failed to render`, error, info);
  }

  render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <div className="errorbox errorbox-boundary" role="alert">
        <strong>{this.props.label} could not be displayed.</strong>
        <p>
          Something in this part of the page failed while rendering. This is a display fault in
          the app — it says nothing about the export you uploaded or the findings themselves.
        </p>
        <button type="button" onClick={() => window.location.reload()}>
          Reload the page
        </button>
        <details>
          <summary>Technical detail</summary>
          <small className="mono">{error.message}</small>
        </details>
      </div>
    );
  }
}
