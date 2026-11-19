"use client";

/** F-12: tanda bunyi + getar saat scan berhasil / gagal. */
let ctx: AudioContext | null = null;

function audio(): AudioContext | null {
  if (typeof window === "undefined") return null;
  try {
    ctx ??= new AudioContext();
    if (ctx.state === "suspended") void ctx.resume();
    return ctx;
  } catch {
    return null;
  }
}

function tone(freq: number, start: number, duration: number, type: OscillatorType = "sine") {
  const a = audio();
  if (!a) return;
  const osc = a.createOscillator();
  const gain = a.createGain();
  osc.type = type;
  osc.frequency.value = freq;
  const t0 = a.currentTime + start;
  gain.gain.setValueAtTime(0.0001, t0);
  gain.gain.exponentialRampToValueAtTime(0.25, t0 + 0.01);
  gain.gain.exponentialRampToValueAtTime(0.0001, t0 + duration);
  osc.connect(gain).connect(a.destination);
  osc.start(t0);
  osc.stop(t0 + duration + 0.02);
}

export function beepSuccess() {
  tone(1320, 0, 0.09);
  navigator.vibrate?.(40);
}

export function beepError() {
  tone(220, 0, 0.16, "square");
  tone(180, 0.2, 0.22, "square");
  navigator.vibrate?.([90, 60, 90]);
}

/** Panggil dari event user (klik) agar browser mengizinkan audio. */
export function unlockAudio() {
  audio();
}
