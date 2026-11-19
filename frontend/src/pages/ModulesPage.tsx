import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { BrandMark } from "../components/Brand";
import { Icon } from "../components/icons";

/** Shown after sign-in: choose Head Office attendance (Pocket HRMS, module 1) or Field Sales attendance (Bizom, module 2). */
export function ModulesPage({ headOfficeHome }: { headOfficeHome: string | undefined }) {
  const { me, logout } = useAuth();
  if (!me) return null;
  const first = me.display_name.split(/\s+/)[0];

  return (
    <div className="modules">
      <header className="modules-top">
        <BrandMark />
        <span className="modules-product">Attendance Automation</span>
        <span className="modules-spacer" />
        <span className="modules-user">{me.display_name}</span>
        {me.auth_mode === "local" && (
          <button type="button" className="btn btn-ghost btn-small modules-signout" onClick={() => void logout()}>
            <Icon name="logout" className="btn-icon" /> Sign out
          </button>
        )}
      </header>

      <main className="modules-main">
        <h1>Welcome, {first}</h1>
        <p className="modules-lead">Choose the attendance you want to work on.</p>

        <div className="modules-grid">
          <section className="module-card" aria-labelledby="m1-title">
            <span className="module-badge-icon m1" aria-hidden="true"><Icon name="office" /></span>
            <h2 id="m1-title">Head Office Attendance</h2>
            <p className="module-source">Pocket HRMS · Module 1</p>
            <p className="module-desc">Daily and month-end attendance reports for Head Office and plant staff, emailed to every HOD.</p>
            {headOfficeHome ? (
              <Link className="btn module-btn m1" to={`/${headOfficeHome}`}>
                Open Head Office <Icon name="arrow" className="btn-icon" />
              </Link>
            ) : (
              <span className="module-note">You do not have access to this module.</span>
            )}
          </section>

          <section className="module-card" aria-labelledby="m2-title">
            <span className="module-badge-icon m2" aria-hidden="true"><Icon name="field" /></span>
            <h2 id="m2-title">Field Sales Attendance</h2>
            <p className="module-source">Bizom · Module 2 <span className="module-tag">Setting up</span></p>
            <p className="module-desc">Daily attendance of the field sales teams from Bizom, emailed to their managers and HODs.</p>
            <Link className="btn module-btn m2" to="/sales">
              Open Field Sales <Icon name="arrow" className="btn-icon" />
            </Link>
          </section>
        </div>
      </main>
      <footer className="modules-foot">APIS India Limited · For APIS staff only</footer>
    </div>
  );
}
