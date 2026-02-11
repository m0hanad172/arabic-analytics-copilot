import { useAskStore } from "../../../store/useAskStore";

export function SettingsPanel() {
  const { settings, setSetting } = useAskStore();

  return (
    <div className="vstack gap-2">
      <div className="fw-semibold mb-1">Settings</div>

      <div className="form-check form-switch">
        <input
          className="form-check-input"
          type="checkbox"
          checked={settings.use_llm}
          onChange={(e) => setSetting("use_llm", e.target.checked)}
        />
        <label className="form-check-label">Use LLM (Gemini)</label>
      </div>

      <div className="form-check form-switch">
        <input
          className="form-check-input"
          type="checkbox"
          checked={settings.use_cache}
          onChange={(e) => setSetting("use_cache", e.target.checked)}
        />
        <label className="form-check-label">Use Cache</label>
      </div>

      <div className="form-check form-switch">
        <input
          className="form-check-input"
          type="checkbox"
          checked={settings.explain}
          onChange={(e) => setSetting("explain", e.target.checked)}
        />
        <label className="form-check-label">Explain (bilingual)</label>
      </div>
    </div>
  );
}
