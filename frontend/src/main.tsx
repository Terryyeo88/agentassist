import React from "react";
import ReactDOM from "react-dom/client";
import { Root } from "./Root";
import { ErrorBoundary } from "./components/ErrorBoundary";
import "./styles/app.css";

// Root is the source gate: the app boots to an explicit source chooser (no feeder bound),
// and only mounts the B1 review surface (<App/>) or the Xero coverage panel once the user picks.
ReactDOM.createRoot(document.getElementById("root")!).render(
  // G-2: the outermost boundary. A throw anywhere that no inner boundary caught lands here
  // and becomes a stated failure instead of a blank page (the D-47 outcome).
  <React.StrictMode>
    <ErrorBoundary label="This page">
      <Root />
    </ErrorBoundary>
  </React.StrictMode>
);
