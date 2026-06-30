import React from "react";
import ReactDOM from "react-dom/client";
import { Root } from "./Root";
import "./styles/app.css";

// Root is the source gate: the app boots to an explicit source chooser (no feeder bound),
// and only mounts the B1 review surface (<App/>) or the Xero coverage panel once the user picks.
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>
);
