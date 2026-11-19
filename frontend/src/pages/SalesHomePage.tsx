import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { BrandMark } from "../components/Brand";
import { Icon } from "../components/icons";

const NEEDED = [
  ["Bizom daily attendance export", "Three sample days exactly as downloaded: a weekday, a Sunday and a day with leave or a holiday."],
  ["Field sales employee master", "EMP_CODE, name, designation, zone / HQ, reporting manager, regional manager and HOD with their emails."],
  ["Status codes and rules", "What each Bizom code means (P, A, WO, leave…) and what counts as late or short for field sales."],
  ["Who receives what", "Which emails go to reporting managers, regional managers, HODs, the Director and HR."],
];
const SCREENS = ["Upload", "Insights", "Approve emails", "Email log", "Employees", "Settings"];

/** Module 2 (Field Sales, Bizom) - home while the module is being set up. Module 1 is separate and unaffected. */
export function SalesHomePage() {
  const { me, logout } = useAuth();
  if (!me) return null;

  return (
    <div className="sales-shell">
      <header className="modules-top sales-top">
        <BrandMark />
        <span className="modules-product">Field Sales Attendance <span className="sales-src">Bizom · Module 2</span></span>
        <span className="modules-spacer" />
        <Link className="btn btn-ghost btn-small" to="/modules"><Icon name="switch" className="btn-icon" /> <span className="btn-label">Switch module</span></Link>
        {me.auth_mode === "local" && (
          <button type="button" className="btn btn-ghost btn-small" onClick={() => void logout()} aria-label="Sign out">
            <Icon name="logout" className="btn-icon" /> <span className="btn-label">Sign out</span>
          </button>
        )}
      </header>

      <main className="sales-main">
        <section className="sales-hero">
          <span className="module-badge-icon m2" aria-hidden="true"><Icon name="field" /></span>
          <div>
            <h1>Field Sales Attendance</h1>
            <p>Daily attendance of the field sales teams from Bizom, emailed to their managers and HODs. This module is being set up;
              Head Office attendance (Module 1) keeps running as it is.</p>
          </div>
        </section>

        <div className="sales-grid">
          <section className="card">
            <h2>To get started</h2>
            <ol className="sales-steps">
              {NEEDED.map(([title, text]) => (
                <li key={title}><strong>{title}</strong><span>{text}</span></li>
              ))}
            </ol>
          </section>
          <section className="card">
            <h2>Coming in this module</h2>
            <ul className="sales-screens">
              {SCREENS.map((s) => <li key={s}><span>{s}</span><span className="module-tag">Soon</span></li>)}
            </ul>
            <p className="muted sales-note">Same sign-in, same email look and the same approve-before-send steps as Head Office attendance.</p>
          </section>
        </div>
      </main>
    </div>
  );
}
