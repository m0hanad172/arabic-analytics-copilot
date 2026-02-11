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
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });

      streamRef.current = stream;

      const mr = new MediaRecorder(stream, {
        mimeType: "audio/webm;codecs=opus",
        audioBitsPerSecond: 24000,
      });

      mediaRef.current = mr;

      mr.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) chunksRef.current.push(e.data);
      };

      mr.onstart = () => setRecording(true);
      mr.onstop = () => setRecording(false);

      mr.start(250); // ✅ start مرة واحدة فقط
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

        // stop tracks (no lingering mic)
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
