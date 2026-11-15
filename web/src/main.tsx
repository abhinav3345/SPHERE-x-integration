import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// The stylesheets in this order: tokens, then the design system's components, then the page.
import "./design/tokens.css";
import "./design/components.css";
import "./comparator/comparator.css";
import { Comparator } from "./comparator/Comparator";

const root = document.getElementById("root");
if (!root) throw new Error("index.html has no #root element");

createRoot(root).render(
  <StrictMode>
    <Comparator />
  </StrictMode>,
);
