import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App";
import { AuthProvider } from "./auth/AuthContext";
import { FeedbackProvider } from "./components/feedback";
import "./styles.css";
import "./interaction.css";
import "./modules.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter basename={import.meta.env.BASE_URL}>
      <AuthProvider>
        <FeedbackProvider>
          <App />
        </FeedbackProvider>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
);
