import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "../design/tokens.css";
import "./landing.css";
import { Landing } from "./Landing";

const root = document.getElementById("root");
if (!root) throw new Error("index.html has no #root element");

createRoot(root).render(
  <StrictMode>
    <Landing />
  </StrictMode>,
);
