import { useState } from "react";

// Official logo: set VITE_BRAND_LOGO to a file under frontend/public (e.g. /brand/apis-logo.png)
// once APIS supplies the approved artwork. Until then a typographic wordmark is shown.
const LOGO = (import.meta.env.VITE_BRAND_LOGO as string | undefined) || "";

export function BrandMark({ size = "md" }: { size?: "md" | "lg" }) {
  const [failed, setFailed] = useState(false);
  if (LOGO && !failed) {
    return <img className={`brand-logo brand-logo-${size}`} src={LOGO} alt="APIS India Limited" onError={() => setFailed(true)} />;
  }
  return (
    <span className={`brand-oval brand-oval-${size}`} role="img" aria-label="APIS India Limited">
      <span className="brand-oval-text">apis</span>
    </span>
  );
}
