/** Microphone level, push-to-talk, and playback for PCM, MP3, or the browser voice. */

let stopPlayback: (() => void) | null = null;

export function interruptSpeech() {
  window.speechSynthesis?.cancel();
  stopPlayback?.();
  stopPlayback = null;
}

export async function listen(
  mode: "openai" | "browser",
  onLevel: (level: number) => void,
  onPartial: (text: string) => void,
): Promise<{ stop: () => Promise<string> }> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
  const audio = new AudioContext();
  const source = audio.createMediaStreamSource(stream);
  const analyser = audio.createAnalyser();
  analyser.fftSize = 256;
  source.connect(analyser);
  const samples = new Uint8Array(analyser.fftSize);
  let running = true;
  const pump = () => {
    if (!running) return;
    analyser.getByteTimeDomainData(samples);
    let sum = 0;
    for (const value of samples) {
      const centered = (value - 128) / 128;
      sum += centered * centered;
    }
    onLevel(Math.min(1, Math.sqrt(sum / samples.length) * 5));
    requestAnimationFrame(pump);
  };
  pump();

  let recognition: SpeechRecognition | null = null;
  let heard = "";
  if (mode === "browser") {
    const Ctor = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Ctor) {
      cleanup();
      throw new Error("This browser has no speech recognizer. Use Edge or Chrome, or add an OpenAI key for Whisper.");
    }
    recognition = new Ctor();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = navigator.language || "en-US";
    recognition.onresult = (event) => {
      let text = "";
      for (let index = 0; index < event.results.length; index += 1) {
        text += event.results[index][0].transcript;
      }
      heard = text.trim();
      onPartial(heard);
    };
    recognition.start();
  }

  const recorder = mode === "openai" ? new MediaRecorder(stream) : null;
  const chunks: Blob[] = [];
  if (recorder) {
    recorder.ondataavailable = (event) => {
      if (event.data.size) chunks.push(event.data);
    };
    recorder.start();
  }

  function cleanup() {
    running = false;
    onLevel(0);
    stream.getTracks().forEach((track) => track.stop());
    void audio.close();
  }

  return {
    stop: async () => {
      recognition?.stop();
      if (recorder && recorder.state !== "inactive") {
        await new Promise<void>((resolve) => {
          recorder.onstop = () => resolve();
          recorder.stop();
        });
      }
      cleanup();
      if (mode === "browser") return heard;
      const blob = new Blob(chunks, { type: recorder?.mimeType || "audio/webm" });
      const body = new FormData();
      body.append("file", blob, "speech.webm");
      const response = await fetch("/api/voice/transcribe", { method: "POST", body });
      const payload = await response.json();
      if (response.status === 409) {
        throw new Error(payload.detail || "Whisper is not configured.");
      }
      if (!response.ok) throw new Error(payload.detail || "Transcription failed.");
      return String(payload.text || "").trim();
    },
  };
}

export async function speak(text: string, onLevel: (level: number) => void, voiceURI = ""): Promise<void> {
  const response = await fetch("/api/voice/speak", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (response.status === 409) {
    await browserSpeak(text, voiceURI, onLevel);
    return;
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(payload.detail || "Speech failed.");
  }
  const format = response.headers.get("X-Audio-Format");
  if (format === "pcm") {
    await playPcm(response, onLevel);
    return;
  }
  const blob = await response.blob();
  await playBlob(blob, onLevel);
}

function browserSpeak(text: string, voiceURI: string, onLevel: (level: number) => void): Promise<void> {
  return new Promise((resolve, reject) => {
    if (!("speechSynthesis" in window)) {
      reject(new Error("This browser cannot speak. Add an OpenAI or ElevenLabs key in Settings."));
      return;
    }
    const utterance = new SpeechSynthesisUtterance(text);
    const voice = window.speechSynthesis.getVoices().find((item) => item.voiceURI === voiceURI);
    if (voice) utterance.voice = voice;
    let timer = 0;
    utterance.onstart = () => {
      timer = window.setInterval(() => onLevel(0.2 + Math.random() * 0.55), 90);
    };
    const finish = () => {
      window.clearInterval(timer);
      onLevel(0);
      resolve();
    };
    utterance.onend = finish;
    utterance.onerror = () => {
      window.clearInterval(timer);
      onLevel(0);
      reject(new Error("The browser voice failed to speak."));
    };
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);
  });
}

async function playPcm(response: Response, onLevel: (level: number) => void): Promise<void> {
  const rate = Number(response.headers.get("X-Sample-Rate") || 24000);
  const ctx = new AudioContext({ sampleRate: rate });
  let running = true;
  stopPlayback = () => {
    running = false;
    void ctx.close();
  };
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 256;
  analyser.connect(ctx.destination);
  const reader = response.body?.getReader();
  if (!reader) {
    await ctx.close();
    return;
  }
  let next = ctx.currentTime + 0.08;
  let leftover = new Uint8Array(0);
  const samples = new Uint8Array(analyser.fftSize);
  const pump = () => {
    if (!running) return;
    analyser.getByteTimeDomainData(samples);
    let sum = 0;
    for (const value of samples) {
      const centered = (value - 128) / 128;
      sum += centered * centered;
    }
    onLevel(Math.min(1, Math.sqrt(sum / samples.length) * 4));
    requestAnimationFrame(pump);
  };
  pump();
  while (true) {
    const { done, value } = await reader.read();
    if (done || !value) break;
    const merged = concat(leftover, value);
    const even = merged.length - (merged.length % 2);
    leftover = merged.slice(even);
    if (even < 2) continue;
    const view = merged.buffer.slice(merged.byteOffset, merged.byteOffset + even);
    const pcm = new Int16Array(view);
    const floats = new Float32Array(pcm.length);
    for (let index = 0; index < pcm.length; index += 1) floats[index] = pcm[index] / 32768;
    const buffer = ctx.createBuffer(1, floats.length, rate);
    buffer.copyToChannel(floats, 0);
    const node = ctx.createBufferSource();
    node.buffer = buffer;
    node.connect(analyser);
    const start = Math.max(next, ctx.currentTime + 0.02);
    node.start(start);
    next = start + buffer.duration;
  }
  const wait = Math.max(0, next - ctx.currentTime);
  await new Promise((resolve) => window.setTimeout(resolve, wait * 1000 + 40));
  running = false;
  onLevel(0);
  await ctx.close();
}

async function playBlob(blob: Blob, onLevel: (level: number) => void): Promise<void> {
  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);
  stopPlayback = () => {
    audio.pause();
    URL.revokeObjectURL(url);
  };
  await new Promise<void>((resolve, reject) => {
    audio.onended = () => resolve();
    audio.onerror = () => reject(new Error("Could not play the voice audio."));
    void audio.play().catch(reject);
  });
  onLevel(0);
  URL.revokeObjectURL(url);
}

function concat(left: Uint8Array, right: Uint8Array): Uint8Array {
  const merged = new Uint8Array(left.length + right.length);
  merged.set(left, 0);
  merged.set(right, left.length);
  return merged;
}

interface SpeechRecognition extends EventTarget {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: SpeechRecognitionEvent) => void) | null;
  start: () => void;
  stop: () => void;
}

interface SpeechRecognitionEvent {
  results: ArrayLike<{ 0: { transcript: string }; isFinal: boolean }>;
}

declare global {
  interface Window {
    SpeechRecognition?: new () => SpeechRecognition;
    webkitSpeechRecognition?: new () => SpeechRecognition;
  }
}
