import { createContext, useContext } from "react";

/** Presentation-only setting. Scientific frame bytes and measurement coordinates are unchanged. */
export const SmoothDisplayContext = createContext(false);
export const useSmoothDisplay = () => useContext(SmoothDisplayContext);
