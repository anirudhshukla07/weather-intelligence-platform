import { useEffect, useRef, useState } from "react";
import { API_BASE } from "../services/api";

// A few phonetic variants so the wake word triggers reliably.
const DEFAULT_WAKE = [
  "hey weather",
  "hey whether",
  "hey wether",
  "hi weather",
  "okay weather",
  "hey wrf",
  "hey assistant"
];

// VAD tuning (energy-based, on the mic's time-domain signal).
const SPEAK_RMS = 0.035; // above this = speech
const SILENCE_MS = 550; // trailing silence that ends an utterance
const MIN_CLIP_MS = 300; // ignore blips shorter than this

function pickMime() {
  const types = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/ogg;codecs=opus"
  ];
  for (const t of types) {
    if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(t))
      return t;
  }
  return "";
}

/**
 * Always-listening, fully-offline wake-word voice control.
 * A client-side VAD slices each spoken utterance, ships it to the backend
 * /transcribe (local Whisper on the GPU), then the same wake-word gating runs
 * on the returned text. The public API matches the old Web Speech version.
 */
export default function useVoice({ onCommand, wakeWords = DEFAULT_WAKE }) {
  const supported =
    typeof navigator !== "undefined" &&
    !!navigator.mediaDevices?.getUserMedia &&
    typeof MediaRecorder !== "undefined" &&
    typeof (window.AudioContext || window.webkitAudioContext) !== "undefined";

  const [voiceOn, setVoiceOn] = useState(false);
  const [armed, setArmed] = useState(false);
  const [status, setStatus] = useState("");

  const onCommandRef = useRef(onCommand);
  onCommandRef.current = onCommand;

  const voiceOnRef = useRef(false);
  const armedRef = useRef(false);
  const streamRef = useRef(null);
  const ctxRef = useRef(null);
  const analyserRef = useRef(null);
  const recRef = useRef(null);
  const chunksRef = useRef([]);
  const rafRef = useRef(null);
  const speakingRef = useRef(false);
  const speechStartRef = useRef(0);
  const lastVoiceRef = useRef(0);
  const processingRef = useRef(false);

  function idleStatus() {
    setStatus(armedRef.current ? "Listening… say your command" : `Say "${wakeWords[0]}"…`);
  }

  // Wake-word gating — identical behaviour to the previous implementation.
  function handleText(raw) {
    const text = (raw || "").toLowerCase().trim();
    if (!text) {
      idleStatus();
      return;
    }

    const wk = wakeWords.find((w) => text.includes(w));
    if (wk) {
      const after = text
        .slice(text.indexOf(wk) + wk.length)
        .replace(/^[\s,.:;!?-]+/, "")
        .trim();
      if (after) {
        armedRef.current = false;
        setArmed(false);
        setStatus(`Say "${wakeWords[0]}"…`);
        onCommandRef.current && onCommandRef.current(after);
      } else {
        armedRef.current = true;
        setArmed(true);
        setStatus("Listening… say your command");
      }
      return;
    }

    if (armedRef.current) {
      armedRef.current = false;
      setArmed(false);
      setStatus(`Say "${wakeWords[0]}"…`);
      onCommandRef.current && onCommandRef.current(text);
      return;
    }

    idleStatus();
  }

  async function transcribe(blob) {
    processingRef.current = true;
    setStatus("Transcribing…");
    try {
      const fd = new FormData();
      fd.append("file", blob, "clip.webm");
      const res = await fetch(`${API_BASE}/transcribe`, { method: "POST", body: fd });
      const data = await res.json();
      handleText(data?.text || "");
    } catch {
      setStatus("Transcription failed");
    } finally {
      processingRef.current = false;
      if (voiceOnRef.current && status !== "Listening… say your command") idleStatus();
    }
  }

  function startRec() {
    try {
      chunksRef.current = [];
      const mime = pickMime();
      const rec = new MediaRecorder(streamRef.current, mime ? { mimeType: mime } : undefined);
      rec.ondataavailable = (e) => {
        if (e.data && e.data.size) chunksRef.current.push(e.data);
      };
      rec.onstop = () => {
        const dur = performance.now() - speechStartRef.current;
        const blob = new Blob(chunksRef.current, {
          type: chunksRef.current[0]?.type || "audio/webm"
        });
        if (dur >= MIN_CLIP_MS && blob.size > 1200) transcribe(blob);
        else if (voiceOnRef.current) idleStatus();
      };
      rec.start();
      recRef.current = rec;
    } catch {
      /* recorder failed to start */
    }
  }

  function stopRec() {
    if (recRef.current && recRef.current.state !== "inactive") {
      try {
        recRef.current.stop();
      } catch {
        /* noop */
      }
    }
    recRef.current = null;
  }

  function monitor() {
    const analyser = analyserRef.current;
    if (!analyser) return;

    const buf = new Uint8Array(analyser.fftSize);
    analyser.getByteTimeDomainData(buf);
    let sum = 0;
    for (let i = 0; i < buf.length; i++) {
      const v = (buf[i] - 128) / 128;
      sum += v * v;
    }
    const rms = Math.sqrt(sum / buf.length);
    const now = performance.now();

    if (rms > SPEAK_RMS) {
      lastVoiceRef.current = now;
      // Don't start a new clip while the previous one is still transcribing.
      if (!speakingRef.current && !processingRef.current) {
        speakingRef.current = true;
        speechStartRef.current = now;
        if (!armedRef.current) setStatus("Listening…");
        startRec();
      }
    } else if (speakingRef.current && now - lastVoiceRef.current > SILENCE_MS) {
      speakingRef.current = false;
      stopRec();
    }

    rafRef.current = requestAnimationFrame(monitor);
  }

  async function start() {
    if (!supported) {
      setStatus("Voice not supported in this browser");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }
      });
      streamRef.current = stream;

      const Ctx = window.AudioContext || window.webkitAudioContext;
      const ctx = new Ctx();
      ctxRef.current = ctx;
      const src = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 1024;
      src.connect(analyser);
      analyserRef.current = analyser;

      voiceOnRef.current = true;
      setVoiceOn(true);
      armedRef.current = false;
      setArmed(false);
      lastVoiceRef.current = performance.now();
      setStatus(`Say "${wakeWords[0]}"…`);
      rafRef.current = requestAnimationFrame(monitor);
    } catch {
      setStatus("Microphone permission denied");
    }
  }

  function stop() {
    voiceOnRef.current = false;
    armedRef.current = false;
    speakingRef.current = false;
    processingRef.current = false;
    setVoiceOn(false);
    setArmed(false);
    setStatus("");

    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    rafRef.current = null;
    stopRec();
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
    }
    if (ctxRef.current) {
      try {
        ctxRef.current.close();
      } catch {
        /* noop */
      }
    }
    streamRef.current = null;
    ctxRef.current = null;
    analyserRef.current = null;
  }

  function toggle() {
    if (voiceOnRef.current) stop();
    else start();
  }

  useEffect(() => {
    return () => stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { supported, voiceOn, armed, status, toggle, wakeWord: wakeWords[0] };
}
