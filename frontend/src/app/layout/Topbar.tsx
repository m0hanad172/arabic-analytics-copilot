import { useAskStore } from "../../store/useAskStore";

export function Topbar({ onToggleSidebar }: { onToggleSidebar: () => void }) {
  useAskStore();

  return (
    <nav className="navbar border-bottom bg-body sticky-top" dir="ltr">
      <div className="container-fluid d-flex justify-content-between">
        {/* Left side */}
        <div className="d-flex align-items-center gap-2">
          <button
            className="btn btn-outline-secondary d-lg-none"
            onClick={onToggleSidebar}
            title="Menu"
            type="button"
          >
            <i className="bi bi-list"></i>
          </button>

          <div className="fw-semibold d-flex align-items-center gap-2">
            <span>Arabic Analytics Copilot</span>
            <span className="badge text-bg-secondary">Enterprise UI</span>
          </div>
        </div>

        {/* Right side reserved for future actions */}
        <div className="d-flex align-items-center gap-2"></div>
      </div>
    </nav>
  );
}
