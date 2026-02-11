import { useRef, useState } from "react";

export function useAudioRecorder() {
  const mediaRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const streamRef = useRef<MediaStream | null>(null);

  const [recording, setRecording] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const start = async () => {
    setError(null);
    chunksRef.current = [];

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      // Prefer audio/webm; fallback if needed
      const mime = MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "";
      const mr = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);

      mediaRef.current = mr;

      mr.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) chunksRef.current.push(e.data);
      };

      mr.onstart = () => setRecording(true);
      mr.onstop = () => setRecording(false);

      mr.start(250);
    } catch (e: any) {
      setError(e?.message || "mic_error");
      setRecording(false);
    }
  };

  const stop = async (): Promise<Blob | null> => {
    const mr = mediaRef.current;
    if (!mr) return null;

    return new Promise((resolve) => {
      mr.onstop = () => {
        setRecording(false);

        const blob = new Blob(chunksRef.current, { type: "audio/webm" });

        if (streamRef.current) {
          streamRef.current.getTracks().forEach((t) => t.stop());
          streamRef.current = null;
        }
        mediaRef.current = null;

        resolve(blob);
      };

      try {
        mr.stop();
      } catch {
        resolve(null);
      }
    });
  };

  return { recording, error, start, stop };
}
