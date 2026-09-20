import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ErrorBoundary } from "../components/ErrorBoundary";

/**
 * Slice A / A3 — G-2: a render-time throw must not take the whole tree down.
 *
 * D-47 was exactly this: `FindingDetail` read `completeness.required` on a null, React
 * unmounted the tree, and the user got a white screen. That was fixed with ONE local null
 * guard — the CLASS was never closed, because the frontend has no error boundary at all
 * (grep for componentDidCatch / getDerivedStateFromError across frontend/src returned nothing
 * at eba8aeb). The next null anywhere repeats it.
 *
 * The fallback is deliberately modest about what it knows. A view failed to display; that is
 * a statement about THIS SCREEN, not about the data, the findings, or anything having been
 * filed. It must never imply a review is complete, incomplete, saved or submitted.
 */

function Boom({ message }: { message: string }): JSX.Element {
  throw new Error(message);
}

describe("Slice A / A3 — G-2 error boundary", () => {
  // React logs the caught error; silence it so a passing run stays readable.
  beforeEach(() => vi.spyOn(console, "error").mockImplementation(() => {}));
  afterEach(() => vi.restoreAllMocks());

  it("A3-T1: a throwing child renders a fallback, not an empty tree", () => {
    const { container } = render(
      <ErrorBoundary label="the review screen">
        <Boom message="completeness is null" />
      </ErrorBoundary>
    );
    expect(container).not.toBeEmptyDOMElement();
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("A3-T2: the fallback says plainly that the view failed to display", () => {
    render(
      <ErrorBoundary label="the review screen">
        <Boom message="completeness is null" />
      </ErrorBoundary>
    );
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(/could not be displayed/i);
    expect(alert).toHaveTextContent(/the review screen/i);
  });

  it("A3-T3: the fallback offers a reload", () => {
    render(
      <ErrorBoundary label="the review screen">
        <Boom message="completeness is null" />
      </ErrorBoundary>
    );
    expect(screen.getByRole("button", { name: /reload/i })).toBeInTheDocument();
  });

  it("A3-T4: the error message is available, inside a collapsed details element", () => {
    const { container } = render(
      <ErrorBoundary label="the review screen">
        <Boom message="completeness is null" />
      </ErrorBoundary>
    );
    const details = container.querySelector("details");
    expect(details).not.toBeNull();
    // Collapsed by default: the reviewer sees plain words first, the stack only on request.
    expect((details as HTMLDetailsElement).open).toBe(false);
    expect(details).toHaveTextContent("completeness is null");
  });

  it("A3-T5: the fallback makes NO claim about the data or the filing state", () => {
    render(
      <ErrorBoundary label="the review screen">
        <Boom message="completeness is null" />
      </ErrorBoundary>
    );
    const text = screen.getByRole("alert").textContent ?? "";
    for (const forbidden of [
      /\bfiled\b/i,
      /\bsubmitted\b/i,
      /\bsaved\b/i,
      /\bIRAS\b/i,
      /\bcomplete\b/i,
      /\bvalid\b/i,
      /\bno (?:errors|findings|issues)\b/i,
      /\bnothing (?:was )?lost\b/i,
    ]) {
      expect(text).not.toMatch(forbidden);
    }
  });

  it("A3-T6: children render untouched when nothing throws", () => {
    render(
      <ErrorBoundary label="the review screen">
        <p>the queue</p>
      </ErrorBoundary>
    );
    expect(screen.getByText("the queue")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("A3-T7: one bad pane cannot take down its siblings", () => {
    // The finding-detail pane is wrapped separately from the app root precisely so that one
    // malformed finding leaves the queue beside it usable.
    render(
      <div>
        <p>the queue</p>
        <ErrorBoundary label="this finding">
          <Boom message="bad row" />
        </ErrorBoundary>
      </div>
    );
    expect(screen.getByText("the queue")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/this finding/i);
  });
});
