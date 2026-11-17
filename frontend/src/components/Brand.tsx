import logo from "../assets/apis-logo.png";

/** The official APIS logo (bundled with the app; same artwork as in the emails and dashboards). */
export function BrandMark({ size = "md" }: { size?: "md" | "lg" }) {
  return <img className={`brand-logo brand-logo-${size}`} src={logo} alt="APIS India Limited" />;
}
