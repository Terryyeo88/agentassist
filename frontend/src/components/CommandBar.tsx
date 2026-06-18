/**
 * CommandBar — INERT shell only (Lane C2 deferred).
 *
 * This is the styled command-bar surface (input + intent buttons) lifted from the target
 * aesthetic, but it has NO behaviour: it does not classify, route, or execute anything.
 * The classify+execute wiring (env-selected classifier → execute_intent → result) is Lane
 * C2, gated on Lanes A + B. Everything here is disabled and labelled deferred.
 */
const INTENT_BUTTONS = ["Run a review", "Show ledger", "Show proposals", "Prior decisions"];

export function CommandBar() {
  return (
    <section className="commandbar" aria-label="Command bar (inert — Lane C2 deferred)">
      <div className="row">
        <input
          type="text"
          placeholder="Ask the assistant…  (inert in this build)"
          disabled
          aria-disabled="true"
        />
        {INTENT_BUTTONS.map((label) => (
          <button key={label} disabled aria-disabled="true" className="ghost">
            {label}
          </button>
        ))}
      </div>
      <div className="deferred-note">
        Command bar is an inert shell in this slice — classify + execute is deferred to Lane
        C2 (gated on Lanes A + B). Review still happens in the queue below.
      </div>
    </section>
  );
}
