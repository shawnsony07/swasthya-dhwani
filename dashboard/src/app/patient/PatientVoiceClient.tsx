"use client";

import React, { useState, useEffect, useRef } from "react";
import Image from "next/image";
import Link from "next/link";
import {
  Room,
  RoomEvent,
  Track,
  RemoteTrack,
} from "livekit-client";

type CallStatus = "idle" | "requesting" | "connecting" | "connected" | "ended" | "error";

interface ChatMessage {
  id: string;
  sender: "agent" | "patient";
  text: string;
  time: string;
}

const KERALA_DISTRICTS = [
  "Ernakulam",
  "Thiruvananthapuram",
  "Kozhikode",
  "Thrissur",
  "Malappuram",
  "Kollam",
  "Kannur",
  "Alappuzha",
  "Kottayam",
  "Palakkad",
  "Wayanad",
  "Idukki",
  "Pathanamthitta",
  "Kasaragod",
];

export default function PatientVoiceClient() {
  const [callStatus, setCallStatus] = useState<CallStatus>("idle");
  const [statusMessage, setStatusMessage] = useState<string>(
    "സംഭാഷണം ആരംഭിക്കാൻ താഴെ മൈക്രോഫോൺ ബട്ടൺ അമർത്തുക (Tap mic button to start)"
  );
  const [district, setDistrict] = useState<string>("Ernakulam");
  const [isMuted, setIsMuted] = useState<boolean>(false);
  const [isAgentSpeaking, setIsAgentSpeaking] = useState<boolean>(false);
  const [callDuration, setCallDuration] = useState<number>(0);
  const [messages, setMessages] = useState<ChatMessage[]>([]);

  const roomRef = useRef<Room | null>(null);
  const audioContainerRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const timerRef = useRef<NodeJS.Timeout | null>(null);
  const animFrameRef = useRef<number | null>(null);
  const speechRecRef = useRef<any>(null);

  // Call duration counter
  useEffect(() => {
    if (callStatus === "connected") {
      timerRef.current = setInterval(() => {
        setCallDuration((prev) => prev + 1);
      }, 1000);
    } else {
      if (timerRef.current) clearInterval(timerRef.current);
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [callStatus]);

  // Audio wave visualizer canvas loop
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let phase = 0;
    const render = () => {
      const width = canvas.width;
      const height = canvas.height;
      ctx.clearRect(0, 0, width, height);

      const isActive = callStatus === "connected";
      const isSpeaking = isAgentSpeaking;

      // Draw subtle background baseline
      ctx.beginPath();
      ctx.strokeStyle = "rgba(255, 255, 255, 0.08)";
      ctx.lineWidth = 1;
      ctx.moveTo(0, height / 2);
      ctx.lineTo(width, height / 2);
      ctx.stroke();

      if (isActive) {
        // Multi-frequency wave when active
        const bars = 28;
        const barWidth = 4;
        const spacing = (width - bars * barWidth) / (bars - 1);

        for (let i = 0; i < bars; i++) {
          const x = i * (barWidth + spacing);
          const baseHeight = isSpeaking
            ? Math.sin(phase + i * 0.45) * 16 + 18
            : Math.sin(phase + i * 0.3) * 6 + 8;
          const y = (height - baseHeight) / 2;

          ctx.fillStyle = isSpeaking
            ? `rgba(230, 167, 60, ${0.4 + (i / bars) * 0.6})`
            : `rgba(19, 194, 194, ${0.3 + (i / bars) * 0.7})`;

          ctx.beginPath();
          ctx.roundRect(x, y, barWidth, Math.max(4, baseHeight), 2);
          ctx.fill();
        }
        phase += isSpeaking ? 0.12 : 0.05;
      }

      animFrameRef.current = requestAnimationFrame(render);
    };

    render();

    return () => {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    };
  }, [callStatus, isAgentSpeaking]);

  // Hardware microphone gating: mute mic when agent is speaking, unmute when listening
  const setMicActive = (active: boolean) => {
    if (roomRef.current?.localParticipant) {
      roomRef.current.localParticipant.setMicrophoneEnabled(active).catch((err) => {
        console.warn("Could not toggle mic:", err);
      });
    }
  };

  // Attach and play remote audio track
  const attachAudioTrack = (track: RemoteTrack) => {
    if (track.kind === Track.Kind.Audio) {
      const audioElement = track.attach();
      audioElement.autoplay = true;
      audioElement.muted = false;
      audioElement.volume = 1.0;
      (audioElement as any).playsInline = true;

      // Strict half-duplex: while agent audio plays from speakers, mute local microphone to avoid acoustic feedback
      audioElement.addEventListener("play", () => {
        setIsAgentSpeaking(true);
        setStatusMessage("സ്വാസ്ഥ്യ സംസാരിക്കുന്നു... (മൈക്ക് നിശബ്ദമാക്കി)");
        setMicActive(false);
      });
      audioElement.addEventListener("ended", () => {
        setIsAgentSpeaking(false);
        setStatusMessage("ഇപ്പോൾ സംസാരിക്കാം (Your turn to speak)");
        setMicActive(true);
      });
      audioElement.addEventListener("pause", () => {
        setIsAgentSpeaking(false);
        setMicActive(true);
      });

      if (audioContainerRef.current) {
        audioContainerRef.current.appendChild(audioElement);
      }

      audioElement.play().catch((err) => {
        console.warn("Audio playback gesture notice:", err);
      });

      setStatusMessage("സ്വാസ്ഥ്യ അസിസ്റ്റന്റ് ബന്ധിപ്പിച്ചു (Live Assistant Connected)");
    }
  };

  // Start Voice Call
  const handleStartCall = async () => {
    try {
      setCallStatus("requesting");
      setMessages([]);
      setStatusMessage("മൈക്രോഫോൺ ബന്ധിപ്പിക്കുന്നു (Requesting audio permission)...");

      // 1. Immediately request microphone access within the user gesture context (crucial for iOS Safari & Android)
      try {
        if (typeof navigator !== "undefined" && navigator.mediaDevices?.getUserMedia) {
          const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
          // Close temporary probe stream so LiveKit can cleanly bind the audio device
          stream.getTracks().forEach((t) => t.stop());
        }
      } catch (permErr: any) {
        if (permErr?.name === "NotAllowedError" || permErr?.name === "PermissionDeniedError") {
          throw new Error("മൈക്രോഫോൺ അനുമതി നിഷേധിച്ചു. ബ്രൗസറിൽ മൈക്ക് അനുവദിക്കുക (Microphone permission denied in browser)");
        }
      }

      setStatusMessage("ലൈവ് ടോക്കൺ തയ്യാറാക്കുന്നു (Requesting emergency token)...");

      // 2. Fetch public patient token from our Next.js proxy route
      const tokenRes = await fetch(
        `/api/patient/token?district=${encodeURIComponent(district)}`
      );
      if (!tokenRes.ok) {
        throw new Error(`Token request failed with status ${tokenRes.status}`);
      }
      const tokenData = await tokenRes.json();
      const { token, server_url } = tokenData;

      setCallStatus("connecting");
      setStatusMessage("വോയ്‌സ് ഏജന്റിലേക്ക് ബന്ധിപ്പിക്കുന്നു (Connecting WebRTC audio)...");

      // 3. Initialize LiveKit Room & unlock audio for mobile autoplay policy
      const room = new Room({
        adaptiveStream: true,
        dynacast: true,
        audioCaptureDefaults: {
          autoGainControl: true,
          echoCancellation: true,
          noiseSuppression: true,
        },
      });
      roomRef.current = room;

      // Unlock browser audio context for mobile speakers
      try {
        await room.startAudio();
      } catch {
        // Ignored; will retry on connect
      }

      // Handle mobile browser autoplay gating
      room.on(RoomEvent.AudioPlaybackStatusChanged, () => {
        if (!room.canPlayAudio) {
          setStatusMessage("ശബ്ദം കേൾക്കാൻ സ്ക്രീനിൽ സ്പർശിക്കുക (Tap screen to enable audio)");
        }
      });

      // Listen for remote audio track from Swasthya Triage Agent
      room.on(RoomEvent.TrackSubscribed, (track: RemoteTrack) => {
        attachAudioTrack(track);
      });

      room.on(RoomEvent.TrackUnsubscribed, (track: RemoteTrack) => {
        track.detach();
      });

      // Listen for real data packets sent by the voice agent
      room.on(RoomEvent.DataReceived, (payload: Uint8Array) => {
        try {
          const decoded = new TextDecoder().decode(payload);
          const data = JSON.parse(decoded);

          // Handle server-side agent speaking state
          if (data.type === "agent_state") {
            if (data.state === "speaking") {
              setIsAgentSpeaking(true);
              setStatusMessage("സ്വാസ്ഥ്യ സംസാരിക്കുന്നു... (മൈക്ക് നിശബ്ദമാക്കി)");
              setMicActive(false);
            } else if (data.state === "listening") {
              setIsAgentSpeaking(false);
              setStatusMessage("ഇപ്പോൾ സംസാരിക്കാം (Your turn to speak)");
              setMicActive(true);
            }
            return;
          }

          if (data.type === "transcript" && data.text) {
            setMessages((prev) => [
              ...prev,
              {
                id: `${data.sender}-${Date.now()}-${Math.random()}`,
                sender: data.sender as "agent" | "patient",
                text: data.text,
                time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }),
              },
            ]);
            if (data.sender === "agent") {
              setIsAgentSpeaking(true);
              setStatusMessage("സ്വാസ്ഥ്യ സംസാരിക്കുന്നു... (മൈക്ക് നിശബ്ദമാക്കി)");
              setMicActive(false);
            }
          }
        } catch (err) {
          console.warn("Failed to parse data payload:", err);
        }
      });

      // Listen for native LiveKit STT transcription segments
      room.on(RoomEvent.TranscriptionReceived, (segments, participant) => {
        for (const seg of segments) {
          if (seg.text && seg.text.trim()) {
            const isLocal = participant?.identity === room.localParticipant?.identity;
            setMessages((prev) => {
              const existingIdx = prev.findIndex((m) => m.id === seg.id);
              const item: ChatMessage = {
                id: seg.id || `seg-${Date.now()}`,
                sender: isLocal ? "patient" : "agent",
                text: seg.text.trim(),
                time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
              };
              if (existingIdx >= 0) {
                const next = [...prev];
                next[existingIdx] = item;
                return next;
              }
              return [...prev, item];
            });
          }
        }
      });

      room.on(RoomEvent.ActiveSpeakersChanged, (speakers) => {
        const agentSpeaking = speakers.some(
          (s) => s.identity !== room.localParticipant?.identity
        );
        setIsAgentSpeaking(agentSpeaking);
      });

      room.on(RoomEvent.Disconnected, () => {
        setCallStatus("ended");
        setStatusMessage("സംഭാഷണം അവസാനിച്ചു (Call Completed)");
      });

      // 4. Connect to LiveKit Room
      await room.connect(server_url, token);

      // Start audio playback explicitly post-connection
      await room.startAudio();

      // Check existing participants in case track was published immediately
      room.remoteParticipants.forEach((p) => {
        p.trackPublications.forEach((pub) => {
          if (pub.track) attachAudioTrack(pub.track);
        });
      });

      // 5. Publish Microphone
      await room.localParticipant.setMicrophoneEnabled(true);

      setCallStatus("connected");
      setStatusMessage("ബന്ധിപ്പിച്ചു · സംസാരിക്കാം (Connected · Speak now)");
    } catch (err: unknown) {
      console.error("Call connection failed:", err);
      const errMsg = err instanceof Error ? err.message : String(err);
      setCallStatus("error");
      setStatusMessage(`കണക്ഷൻ പരാജയപ്പെട്ടു: ${errMsg}`);
    }
  };

  // Hang Up Call
  const handleEndCall = async () => {
    if (roomRef.current) {
      try {
        await roomRef.current.disconnect();
      } catch (err) {
        console.warn("Disconnect error:", err);
      }
      roomRef.current = null;
    }
    setCallStatus("ended");
    setStatusMessage("സംഭാഷണം അവസാനിച്ചു (Call Terminated)");
  };

  // Toggle Mute
  const handleToggleMute = async () => {
    if (!roomRef.current?.localParticipant) return;
    const nextMute = !isMuted;
    await roomRef.current.localParticipant.setMicrophoneEnabled(!nextMute);
    setIsMuted(nextMute);
  };

  // Format call duration MM:SS
  const formatTime = (secs: number) => {
    const m = Math.floor(secs / 60)
      .toString()
      .padStart(2, "0");
    const s = (secs % 60).toString().padStart(2, "0");
    return `${m}:${s}`;
  };

  return (
    <div className="patient-view-root">
      {/* Off-screen audio container ensuring browser doesn't throttle or suspend audio */}
      <div
        ref={audioContainerRef}
        style={{
          position: "fixed",
          top: -9999,
          left: -9999,
          width: 1,
          height: 1,
          opacity: 0,
          pointerEvents: "none",
        }}
        aria-hidden="true"
      />

      <main className="patient-phone-frame">
        {/* Top Status Bar (Emulates Phone OS) */}
        <div className="patient-status-bar">
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span
              style={{
                width: 7,
                height: 7,
                borderRadius: "50%",
                background: callStatus === "connected" ? "var(--ok)" : "var(--muted)",
                boxShadow: callStatus === "connected" ? "0 0 8px var(--ok)" : "none",
              }}
            />
            <span>{callStatus === "connected" ? "WebRTC HD Audio" : "Kerala Emergency Triage"}</span>
          </div>

          <div className="patient-notch">
            <div className="patient-notch-speaker" />
            <div className="patient-notch-dot" />
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span>LiveKit</span>
            <span>100%</span>
          </div>
        </div>

        {/* App Header with Brand Logo & Clinician Navigation */}
        <header className="patient-header">
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div
              style={{
                width: 36,
                height: 36,
                borderRadius: 10,
                overflow: "hidden",
                border: "1.5px solid rgba(19, 194, 194, 0.4)",
                background: "#000",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <Image
                src="/logo.png"
                alt="Swasthya Dhwani Emblem"
                width={36}
                height={36}
                priority
                style={{ width: "100%", height: "100%", objectFit: "cover" }}
              />
            </div>
            <div>
              <div
                style={{
                  fontSize: "0.95rem",
                  fontWeight: 700,
                  letterSpacing: "-0.01em",
                  color: "var(--text)",
                }}
              >
                സ്വാസ്ഥ്യ ധ്വനി
              </div>
              <div style={{ fontSize: "0.7rem", color: "var(--brass)", fontWeight: 600 }}>
                Swasthya-Dhwani Triage
              </div>
            </div>
          </div>

          <Link
            href="/login"
            style={{
              fontSize: "0.72rem",
              fontWeight: 600,
              padding: "0.3rem 0.65rem",
              borderRadius: "999px",
              background: "rgba(255, 255, 255, 0.05)",
              border: "1px solid rgba(255, 255, 255, 0.12)",
              color: "var(--text-dim)",
              textDecoration: "none",
              display: "flex",
              alignItems: "center",
              gap: 4,
            }}
          >
            🏥 Clinician Portal
          </Link>
        </header>

        {/* District Selector & Location Badge */}
        <div
          style={{
            padding: "0.6rem 1.25rem 0.25rem",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: "0.78rem" }}>
            <span style={{ color: "var(--tb)" }}>📍</span>
            <span style={{ color: "var(--muted)" }}>ജില്ല (District):</span>
            <select
              value={district}
              disabled={callStatus === "connected" || callStatus === "connecting"}
              onChange={(e) => setDistrict(e.target.value)}
              style={{
                background: "rgba(0, 0, 0, 0.4)",
                color: "var(--text)",
                border: "1px solid rgba(255, 255, 255, 0.15)",
                borderRadius: 8,
                padding: "2px 8px",
                fontSize: "0.78rem",
                outline: "none",
                cursor: "pointer",
              }}
            >
              {KERALA_DISTRICTS.map((d) => (
                <option key={d} value={d} style={{ background: "#0d1318", color: "#fff" }}>
                  {d}
                </option>
              ))}
            </select>
          </div>

          {callStatus === "connected" && (
            <div
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: "0.8rem",
                fontWeight: 700,
                color: "var(--ok)",
                padding: "2px 8px",
                borderRadius: 6,
                background: "rgba(52, 211, 153, 0.12)",
                border: "1px solid rgba(52, 211, 153, 0.3)",
              }}
            >
              ⏱️ {formatTime(callDuration)}
            </div>
          )}
        </div>

        {/* Primary Interactive Orb & Acoustic Center */}
        <div className="patient-orb-wrapper">
          {callStatus === "connected" && (
            <>
              <div className="patient-orb-pulse-ring" />
              <div className="patient-orb-pulse-ring" />
              <div className="patient-orb-pulse-ring" />
            </>
          )}

          <button
            type="button"
            onClick={async () => {
              if (callStatus === "connected") {
                // Clicking while in call unblocks any mobile autoplay restrictions & ensures mic is active
                if (roomRef.current) {
                  try {
                    await roomRef.current.startAudio();
                  } catch {
                    // Ignore
                  }
                }
                setMicActive(true);
                setIsMuted(false);
                setStatusMessage("ഇപ്പോൾ സംസാരിക്കാം (Hands-free live · Just speak into mic)");
              } else if (callStatus === "idle" || callStatus === "ended" || callStatus === "error") {
                handleStartCall();
              }
            }}
            disabled={callStatus === "requesting" || callStatus === "connecting"}
            className={`patient-voice-orb ${callStatus === "connected" ? "connected" : ""} ${
              isAgentSpeaking ? "speaking" : ""
            } ${callStatus === "connecting" ? "connecting" : ""}`}
            aria-label="Toggle voice triage call"
            style={{ border: "none", outline: "none" }}
          >
            {callStatus === "requesting" || callStatus === "connecting" ? (
              <svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ animation: "spin 1s linear infinite" }}>
                <path d="M21 12a9 9 0 1 1-6.219-8.56" />
              </svg>
            ) : callStatus === "connected" ? (
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
                <svg width="38" height="38" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
                  <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                  <line x1="12" x2="12" y1="19" y2="22" />
                </svg>
                <span style={{ fontSize: "0.68rem", fontWeight: 700, letterSpacing: "0.03em", textTransform: "uppercase" }}>
                  {isAgentSpeaking ? "ശ്രദ്ധിക്കുക (Listening)" : "സംസാരിക്കാം (Speak Now)"}
                </span>
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
                <svg width="42" height="42" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
                  <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                  <line x1="12" x2="12" y1="19" y2="22" />
                </svg>
                <span style={{ fontSize: "0.74rem", fontWeight: 700 }}>കോൾ ആരംഭിക്കുക</span>
                <span style={{ fontSize: "0.62rem", opacity: 0.85 }}>Tap to Start</span>
              </div>
            )}
          </button>

          {/* Dynamic Frequency Equalizer Canvas */}
          <canvas ref={canvasRef} width={280} height={48} className="patient-waveform-canvas" />

          {/* Calming Status Text */}
          <div
            style={{
              marginTop: "0.85rem",
              textAlign: "center",
              padding: "0 1.25rem",
              fontSize: "0.82rem",
              color: callStatus === "error" ? "var(--c1)" : "var(--text-dim)",
              fontWeight: 500,
              minHeight: "2.4rem",
              lineHeight: 1.4,
            }}
          >
            {statusMessage}
          </div>

          {/* In-Call Controls (Hang Up & Mute) */}
          {callStatus === "connected" && (
            <div style={{ display: "flex", alignItems: "center", gap: "1.5rem", marginTop: "1rem" }}>
              <button
                type="button"
                onClick={handleToggleMute}
                style={{
                  width: 48,
                  height: 48,
                  borderRadius: "50%",
                  background: isMuted ? "rgba(250, 140, 22, 0.2)" : "rgba(255, 255, 255, 0.08)",
                  border: isMuted ? "1.5px solid var(--c2)" : "1px solid rgba(255, 255, 255, 0.15)",
                  color: isMuted ? "var(--c2)" : "var(--text)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  cursor: "pointer",
                }}
                title={isMuted ? "Unmute microphone" : "Mute microphone"}
              >
                {isMuted ? (
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <line x1="2" y1="2" x2="22" y2="22" />
                    <path d="M18.89 13.23A7.12 7.12 0 0 0 19 12v-2" />
                    <path d="M5 10v2a7 7 0 0 0 12 5" />
                    <path d="M15 9.34V5a3 3 0 0 0-5.68-1.33" />
                    <path d="M9 9v3a3 3 0 0 0 5.12 2.12" />
                    <line x1="12" y1="19" x2="12" y2="22" />
                  </svg>
                ) : (
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
                    <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                    <line x1="12" y1="19" x2="12" y2="22" />
                  </svg>
                )}
              </button>

              <button
                type="button"
                onClick={handleEndCall}
                style={{
                  width: 56,
                  height: 56,
                  borderRadius: "50%",
                  background: "linear-gradient(135deg, #ef4444 0%, #b91c1c 100%)",
                  border: "2px solid rgba(255, 255, 255, 0.3)",
                  boxShadow: "0 6px 20px rgba(239, 68, 68, 0.4)",
                  color: "#fff",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  cursor: "pointer",
                }}
                title="End triage call"
              >
                <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M10.68 13.31a16 16 0 0 0 3.41 2.6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7 2 2 0 0 1 1.72 2v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.42 19.42 0 0 1-6-6 19.8 19.8 0 0 1-3.11-8.69A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91" />
                  <line x1="22" y1="2" x2="2" y2="22" />
                </svg>
              </button>
            </div>
          )}
        </div>

        {/* Live Conversation Transcript Feed */}
        <div className="patient-transcript-area">
          <div
            style={{
              fontSize: "0.7rem",
              fontWeight: 700,
              color: "var(--muted)",
              letterSpacing: "0.06em",
              textTransform: "uppercase",
              display: "flex",
              justifyContent: "space-between",
              marginBottom: 4,
            }}
          >
            <span>തത്സമയ സംഭാഷണം (Live Transcript)</span>
            <span style={{ color: callStatus === "connected" ? "var(--ok)" : "var(--muted)" }}>
              {callStatus === "connected" ? "● Live Audio Active" : "Sarvam · ml-IN"}
            </span>
          </div>

          {messages.length === 0 ? (
            <div
              style={{
                padding: "1.25rem 0.5rem",
                textAlign: "center",
                color: "var(--muted)",
                fontSize: "0.78rem",
                lineHeight: 1.5,
              }}
            >
              {callStatus === "connected"
                ? "🎙️ അസിസ്റ്റന്റ് സംസാരിക്കുന്നു, ദയവായി ശ്രദ്ധിക്കുക... (Assistant speaking, please listen...)"
                : "സംഭാഷണം തുടങ്ങുമ്പോൾ തത്സമയ സംഭാഷണ വിവരങ്ങൾ ഇവിടെ കാണാം (Live conversation will appear here once connected)"}
            </div>
          ) : (
            messages.map((m) => (
              <div
                key={m.id}
                className={m.sender === "patient" ? "patient-bubble-user" : "patient-bubble-agent"}
              >
                <div style={{ fontSize: "0.68rem", opacity: 0.7, marginBottom: 2 }}>
                  {m.sender === "patient" ? "നിങ്ങൾ (Patient)" : "സ്വാസ്ഥ്യ അസിസ്റ്റന്റ് (Voice AI)"} · {m.time}
                </div>
                <div>{m.text}</div>
              </div>
            ))
          )}
        </div>

        {/* Direct Emergency 108 Action (Always accessible) */}
        <a href="tel:108" className="patient-108-banner">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
            <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z" />
          </svg>
          🚨 108 ആംബുലൻസ് അടിയന്തര കോൾ (Dial 108 Ambulance)
        </a>

        {/* Footer Disclaimer */}
        <div
          style={{
            padding: "0 1.25rem 0.85rem",
            fontSize: "0.68rem",
            color: "var(--muted)",
            textAlign: "center",
            lineHeight: 1.35,
          }}
        >
          കേരള അടിയന്തര ആരോഗ്യ മാർഗ്ഗനിർദ്ദേശങ്ങൾ പ്രകാരം പ്രവർത്തിക്കുന്നു.
          ജീവൻ രക്ഷാ അടിയന്തര ഘട്ടങ്ങളിൽ ഉടൻ 108 വിളിക്കുക.
        </div>
      </main>
    </div>
  );
}
