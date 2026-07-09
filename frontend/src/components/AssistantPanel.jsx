import { useEffect, useRef, useState } from "react";
import useVoice from "../hooks/useVoice";
import { API_BASE } from "../services/api";

function MicIcon() {
  return (
    <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
    </svg>
  );
}

function SpeakerOnIcon() {
  return (
    <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M4 9v6h4l5 4V5L8 9H4z" />
      <path d="M16 8.5a4 4 0 0 1 0 7M18.5 6a7 7 0 0 1 0 12" />
    </svg>
  );
}

function SpeakerOffIcon() {
  return (
    <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M4 9v6h4l5 4V5L8 9H4z" />
      <path d="M22 9l-5 6M17 9l5 6" />
    </svg>
  );
}

// Offline TTS via the backend (Coqui XTTS-v2 on the GPU). Returns a WAV we
// play in the browser, so it sounds the same in every browser and never
// touches the cloud — matching the local Whisper STT.
let ttsAudio = null;

function stopSpeak() {
  if (ttsAudio) {
    try {
      ttsAudio.pause();
    } catch {
      /* noop */
    }
    ttsAudio = null;
  }
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();
}

async function speak(text) {
  const t = (text || "").trim();
  if (!t) return;
  try {
    stopSpeak();
    const res = await fetch(`${API_BASE}/tts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: t })
    });
    if (!res.ok) return;
    const url = URL.createObjectURL(await res.blob());
    const audio = new Audio(url);
    ttsAudio = audio;
    audio.onended = () => URL.revokeObjectURL(url);
    await audio.play();
  } catch {
    /* noop */
  }
}

export default function AssistantPanel({ streamMessage, disabled }) {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [messages, setMessages] = useState([
    {
      role: "assistant",
      text: "Hi! Ask me to turn on a layer, jump to a time, zoom to a place, or drop a pin. Tap the mic and say \"hey weather\" to use your voice."
    }
  ]);

  const [ttsOn, setTtsOn] = useState(() => {
    try {
      return localStorage.getItem("wrf-tts") !== "0";
    } catch {
      return true;
    }
  });

  const listRef = useRef(null);
  const busyRef = useRef(false);
  busyRef.current = busy;
  const ttsOnRef = useRef(ttsOn);
  ttsOnRef.current = ttsOn;

  function toggleTts() {
    setTtsOn((v) => {
      const next = !v;
      try {
        localStorage.setItem("wrf-tts", next ? "1" : "0");
      } catch {
        /* noop */
      }
      // Silence anything currently being spoken when turning it off.
      if (!next) stopSpeak();
      return next;
    });
  }

  const voice = useVoice({
    onCommand: (text) => {
      if (busyRef.current) return; // don't overlap an in-flight query
      setOpen(true);
      runQuery(text, true);
    }
  });

  useEffect(() => {
    if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [messages, open]);

  async function runQuery(text, spoken = false) {
    const q = (text || "").trim();
    if (!q || busyRef.current) return;

    setMessages((m) => [...m, { role: "user", text: q }, { role: "assistant", text: "" }]);
    setBusy(true);

    let streamed = "";
    const paint = () =>
      setMessages((m) => {
        const next = [...m];
        next[next.length - 1] = { role: "assistant", text: streamed };
        return next;
      });

    try {
      await streamMessage(
        q,
        (delta) => {
          streamed += delta;
          paint();
        },
        (replacement) => {
          streamed = replacement;
          paint();
        }
      );

      if (!streamed.trim()) {
        streamed = "Done.";
        paint();
      }
      if (spoken && ttsOnRef.current) speak(streamed);
    } catch (err) {
      streamed = err?.message || "Something went wrong talking to the assistant.";
      paint();
      if (spoken && ttsOnRef.current) speak("Sorry, something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  function submit(e) {
    e?.preventDefault();
    const text = input.trim();
    if (!text) return;
    setInput("");
    runQuery(text, false);
  }

  if (!open) {
    return (
      <button
        className={`assistant-fab ${voice.voiceOn ? "voice-on" : ""}`}
        onClick={() => setOpen(true)}
        title="Open the map assistant"
        aria-label="Open the map assistant"
      >
        <svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor" aria-hidden="true">
          <path d="M12 3a9 9 0 0 0-9 9 8.6 8.6 0 0 0 1.2 4.4L3 21l4.8-1.2A9 9 0 1 0 12 3zm-3.5 8h7a1 1 0 0 1 0 2h-7a1 1 0 0 1 0-2zm0-3h7a1 1 0 0 1 0 2h-7a1 1 0 0 1 0-2z" />
        </svg>
      </button>
    );
  }

  return (
    <div className="assistant-panel">
      <div className="assistant-head">
        <div className="assistant-title">
          <span>Map Assistant</span>
          <strong>Ask or speak</strong>
        </div>
        <div className="assistant-head-actions">
          <button
            className={`assistant-tts ${ttsOn ? "on" : ""}`}
            onClick={toggleTts}
            title={ttsOn ? "Voice replies on — click to mute" : "Voice replies off — click to enable"}
            aria-label="Toggle text to speech"
          >
            {ttsOn ? <SpeakerOnIcon /> : <SpeakerOffIcon />}
          </button>
          <button
            className={`assistant-mic ${voice.voiceOn ? "on" : ""} ${voice.armed ? "armed" : ""}`}
            onClick={voice.toggle}
            disabled={!voice.supported}
            title={
              !voice.supported
                ? "Voice not supported in this browser"
                : voice.voiceOn
                ? "Turn voice off"
                : "Turn voice on"
            }
            aria-label="Toggle voice"
          >
            <MicIcon />
          </button>
          <button
            className="assistant-close"
            onClick={() => setOpen(false)}
            title="Close"
            aria-label="Close assistant"
          >
            ✕
          </button>
        </div>
      </div>

      {voice.voiceOn && (
        <div className={`assistant-voicebar ${voice.armed ? "armed" : ""}`}>
          <span className="voice-dot" />
          {voice.status}
        </div>
      )}

      <div className="assistant-messages" ref={listRef}>
        {messages.map((m, i) => {
          const isLast = i === messages.length - 1;
          const showDots = m.role === "assistant" && !m.text && busy && isLast;
          return (
            <div
              key={i}
              className={`assistant-msg ${m.role} ${showDots ? "typing" : ""}`}
            >
              {m.text || (showDots ? "Thinking…" : "")}
            </div>
          );
        })}
      </div>

      <form className="assistant-input" onSubmit={submit}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={
            disabled ? "Load a dataset first…" : "Type, or tap the mic and say \"hey weather\""
          }
          disabled={disabled || busy}
        />
        <button type="submit" disabled={disabled || busy || !input.trim()}>
          Send
        </button>
      </form>
    </div>
  );
}
