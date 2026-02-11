// frontend/src/features/ask/components/QuestionEditor.tsx
import { useEffect, useMemo, useRef, useState } from "react";
import { useAskStore } from "../../../store/useAskStore";
import { useAudioRecorder } from "../hooks/useAudioRecorder";
import { transcribeAudio } from "../../../services/transcribeApi";

export function QuestionEditor({ busy, onRun }: { busy: boolean; onRun: () => void }) {
  const { draftQuestion, setDraftQuestion, focusTick } = useAskStore();
  const taRef = useRef<HTMLTextAreaElement | null>(null);

  const { recording, error: micError, start, stop } = useAudioRecorder();

  const [sttBusy, setSttBusy] = useState(false);
  const [sttError, setSttError] = useState<string | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  const disabled = busy || sttBusy;

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.key === "Enter") onRun();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onRun]);

  // ✅ focus textarea when user clicks history item
  useEffect(() => {
    if (!focusTick) return;
    const el = taRef.current;
    if (!el) return;
    el.focus();
    const end = (draftQuestion || "").length;
    try {
      el.setSelectionRange(end, end);
    } catch {}
  }, [focusTick, draftQuestion]);

  const canRecord = useMemo(() => {
    return typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia;
  }, []);

  async function onToggleRecord() {
    setSttError(null);

    if (!canRecord) {
      setSttError("المتصفح لا يدعم التسجيل الصوتي.");
      return;
    }

    if (recording) {
      const blob = await stop();
      if (!blob) return;

      setSttBusy(true);
      abortRef.current?.abort();
      abortRef.current = new AbortController();

      try {
        const r = await transcribeAudio(blob, "ar", { debug: false, signal: abortRef.current.signal });
        const text = (r.text || "").trim();
        if (text) {
          const merged = draftQuestion?.trim() ? `${draftQuestion.trim()}\n${text}` : text;
          setDraftQuestion(merged);
        }
      } catch (e: any) {
        setSttError(e?.message || "فشل تحويل الصوت إلى نص.");
      } finally {
        setSttBusy(false);
      }
      return;
    }

    try {
      await start();
    } catch (e: any) {
      setSttError(e?.message || "فشل بدء التسجيل.");
    }
  }

  function onCancelStt() {
    abortRef.current?.abort();
    abortRef.current = null;
    setSttBusy(false);
    setSttError("تم إلغاء التحويل.");
  }

  return (
    <>
      <textarea
        ref={taRef}
        className="form-control"
        rows={6}
        value={draftQuestion}
        onChange={(e) => setDraftQuestion(e.target.value)}
        placeholder="اكتب سؤالك... أو استخدم زر التسجيل"
        disabled={disabled}
      />

      <div className="d-flex flex-wrap gap-2 mt-3 align-items-center">
        <button className="btn btn-primary" disabled={disabled} onClick={onRun} type="button">
          {busy ? <span className="spinner-border spinner-border-sm ms-2" /> : <i className="bi bi-play-fill ms-1" />}
          تشغيل
        </button>

        <button className="btn btn-outline-secondary" onClick={() => setDraftQuestion("")} disabled={disabled} type="button">
          <i className="bi bi-x-circle ms-1" /> مسح
        </button>

        <div className="ms-auto d-flex gap-2">
          <button
            className={`btn ${recording ? "btn-danger" : "btn-outline-success"}`}
            onClick={onToggleRecord}
            disabled={busy || sttBusy}
            title="تسجيل صوتي"
            type="button"
          >
            <i className={`bi ${recording ? "bi-stop-fill" : "bi-mic-fill"} ms-1`} />
            {recording ? "إيقاف" : "تسجيل"}
          </button>

          {sttBusy && (
            <button className="btn btn-outline-warning" onClick={onCancelStt} type="button">
              <i className="bi bi-x-lg ms-1" /> إلغاء
            </button>
          )}
        </div>
      </div>

      <div className="text-secondary small mt-2">اختصار التشغيل: Ctrl + Enter</div>

      {(micError || sttError) && (
        <div className="alert alert-danger mt-3 mb-0 py-2">
          <div className="d-flex align-items-center gap-2">
            <i className="bi bi-exclamation-triangle-fill" />
            <span>{micError || sttError}</span>
          </div>
        </div>
      )}

      {sttBusy && (
        <div className="alert alert-info mt-3 mb-0 py-2">
          <span className="spinner-border spinner-border-sm ms-2" /> جارٍ تحويل الصوت إلى نص…
        </div>
      )}
    </>
  );
}
