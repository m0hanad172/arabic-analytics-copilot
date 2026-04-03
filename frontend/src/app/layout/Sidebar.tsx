// frontend/src/app/layout/Sidebar.tsx
import { SettingsPanel } from "../../features/ask/components/SettingsPanel";
import { HistoryPanel } from "../../features/ask/components/HistoryPanel";

export function Sidebar({ onCloseMobile }: { onCloseMobile: () => void }) {
  return (
    <aside className="p-3 h-100 d-flex flex-column" style={{ minHeight: 0 }}>
      <div className="d-flex justify-content-between align-items-center mb-3">
        <div className="fw-semibold"><i className="bi bi-sliders"></i> Controls</div>
        <button className="btn btn-outline-secondary d-lg-none btn-sm" onClick={onCloseMobile} title="Close" type="button">
          <i className="bi bi-x-lg"></i>
        </button>
      </div>

      <div className="aac-card p-3 mb-3">
        <SettingsPanel />
      </div>

      {/* take remaining height */}
      <div className="aac-card p-3 flex-grow-1 d-flex flex-column" style={{ minHeight: 0 }}>
        <HistoryPanel />
      </div>
    </aside>
  );
}
