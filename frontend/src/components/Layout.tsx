import { NavLink, Outlet } from "react-router-dom";
import { useTheme } from "../hooks/useTheme";

const links = [
  { to: "/", label: "Dashboard", icon: "bi-speedometer2" },
  { to: "/inventory", label: "Inventory", icon: "bi-box-seam" },
];

export function Layout() {
  const { theme, toggle } = useTheme();

  return (
    <div style={{ display: "flex", minHeight: "100vh", background: "var(--bg-base)", color: "var(--text-primary)" }}>
      <nav style={{ width: 220, background: "var(--bg-surface)", padding: "20px 0", flexShrink: 0 }}>
        <h2 style={{ padding: "0 20px", fontSize: 16, marginBottom: 24, display: "flex", alignItems: "center", gap: 8 }}>
          <i className="bi bi-robot" style={{ fontSize: 20 }} />
          AgentOrbit
        </h2>
        {links.map((l) => (
          <NavLink
            key={l.to}
            to={l.to}
            end={l.to === "/"}
            style={({ isActive }) => ({
              display: "flex",
              alignItems: "center",
              gap: 10,
              padding: "10px 20px",
              color: isActive ? "var(--accent-text)" : "var(--text-secondary)",
              textDecoration: "none",
              fontSize: 14,
              background: isActive ? "var(--accent-bg)" : "transparent",
              borderLeft: isActive ? "3px solid var(--accent-text)" : "3px solid transparent",
            })}
          >
            <i className={`bi ${l.icon}`} style={{ fontSize: 16 }} />
            {l.label}
          </NavLink>
        ))}
      </nav>
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "auto" }}>
        <header style={{ display: "flex", justifyContent: "flex-end", padding: "16px 24px 0" }}>
          <button
            onClick={toggle}
            aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
            style={{
              display: "flex", alignItems: "center", gap: 6,
              padding: "6px 14px", borderRadius: 6, border: "1px solid var(--border)",
              background: "var(--bg-surface)", color: "var(--text-secondary)",
              cursor: "pointer", fontSize: 13,
            }}
          >
            <i className={`bi ${theme === "dark" ? "bi-sun" : "bi-moon-stars"}`} />
            {theme === "dark" ? "Light" : "Dark"}
          </button>
        </header>
        <main style={{ flex: 1, padding: "12px 24px 24px" }}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
