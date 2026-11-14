import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App";
import { AuthProvider } from "./auth/AuthContext";
import "@fontsource/literata/500.css";
import "@fontsource/literata/700.css";
import "@fontsource/jost/400.css";
import "@fontsource/jost/500.css";
import "@fontsource/jost/600.css";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter basename={import.meta.env.BASE_URL}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
);
