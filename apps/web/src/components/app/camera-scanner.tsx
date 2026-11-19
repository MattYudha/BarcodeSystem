"use client";

import { Camera, CameraOff, Flashlight, Loader2, SwitchCamera } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type Detector = { detect: (source: HTMLVideoElement) => Promise<{ rawValue: string }[]> };

/** Pakai BarcodeDetector bawaan browser bila mendukung Code 128; selain itu zxing-wasm lokal. */
async function createDetector(): Promise<Detector> {
  const Native = (globalThis as { BarcodeDetector?: { new (o: object): Detector; getSupportedFormats(): Promise<string[]> } }).BarcodeDetector;
  if (Native) {
    try {
      if ((await Native.getSupportedFormats()).includes("code_128")) {
        return new Native({ formats: ["code_128"] });
      }
    } catch {
      /* lanjut ke ponyfill */
    }
  }
  const mod = await import("barcode-detector/ponyfill");
  mod.prepareZXingModule({
    overrides: {
      locateFile: (path: string, prefix: string) =>
        path.endsWith(".wasm") ? `/zxing/${path}` : prefix + path,
    },
  });
  return new mod.BarcodeDetector({ formats: ["code_128"] });
}

function cameraError(err: unknown): string {
  const name = err instanceof DOMException ? err.name : "";
  if (name === "NotAllowedError") return "Izin kamera ditolak. Izinkan kamera di pengaturan browser lalu coba lagi.";
  if (name === "NotFoundError" || name === "OverconstrainedError") return "Kamera tidak ditemukan di perangkat ini.";
  if (name === "NotReadableError") return "Kamera sedang dipakai aplikasi lain.";
  return "Kamera tidak dapat dibuka.";
}

const SAME_CODE_COOLDOWN_MS = 1500;

/**
 * F-10 scan pakai kamera HP/webcam. Memanggil onScan sekali per barcode (kode yang sama
 * diabaikan selama 1,5 detik agar tidak tercatat berkali-kali saat kamera masih mengarah).
 */
export function CameraScanner({ onScan, className }: { onScan: (code: string) => void; className?: string }) {
  const video = useRef<HTMLVideoElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const onScanRef = useRef(onScan);
  const [active, setActive] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [deviceIndex, setDeviceIndex] = useState(-1); // -1 = kamera belakang (facingMode)
  const [torch, setTorch] = useState<boolean | null>(null); // null = tidak didukung

  useEffect(() => {
    onScanRef.current = onScan;
  }, [onScan]);

  const stop = useCallback(() => {
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
    setActive(false);
    setTorch(null);
  }, []);

  const start = useCallback(async () => {
    setError(null);
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      setError("Kamera hanya bisa dipakai lewat HTTPS. Buka aplikasi dengan alamat https://.");
      return;
    }
    setStarting(true);
    try {
      const deviceId = deviceIndex >= 0 ? devices[deviceIndex]?.deviceId : undefined;
      const media = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: deviceId
          ? { deviceId: { exact: deviceId } }
          : { facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 720 } },
      });
      stream.current = media;
      if (video.current) {
        video.current.srcObject = media;
        await video.current.play();
      }
      const track = media.getVideoTracks()[0];
      const caps = (track.getCapabilities?.() ?? {}) as { torch?: boolean };
      setTorch(caps.torch ? false : null);
      setDevices((await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === "videoinput"));
      setActive(true);
    } catch (err) {
      stop();
      setError(cameraError(err));
    } finally {
      setStarting(false);
    }
  }, [deviceIndex, devices, stop]);

  // Loop deteksi selama kamera aktif.
  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const lastSeen = new Map<string, number>();
    (async () => {
      let detector: Detector;
      try {
        detector = await createDetector();
      } catch {
        setError("Pembaca barcode gagal dimuat. Muat ulang halaman.");
        return;
      }
      const tick = async () => {
        if (cancelled) return;
        const v = video.current;
        if (v && v.readyState >= 2) {
          try {
            for (const { rawValue } of await detector.detect(v)) {
              const now = Date.now();
              if (now - (lastSeen.get(rawValue) ?? 0) > SAME_CODE_COOLDOWN_MS) onScanRef.current(rawValue);
              lastSeen.set(rawValue, now);
            }
          } catch {
            /* frame gagal dibaca: abaikan */
          }
        }
        timer = setTimeout(tick, 120);
      };
      void tick();
    })();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [active]);

  useEffect(() => stop, [stop]); // matikan kamera saat komponen dilepas / halaman disembunyikan

  async function toggleTorch() {
    const track = stream.current?.getVideoTracks()[0];
    if (!track || torch === null) return;
    try {
      await track.applyConstraints({ advanced: [{ torch: !torch } as MediaTrackConstraintSet] });
      setTorch(!torch);
    } catch {
      setTorch(null);
    }
  }

  async function switchCamera() {
    if (devices.length < 2) return;
    stop();
    setDeviceIndex((i) => (i + 1) % devices.length);
  }

  // Setelah ganti kamera, nyalakan lagi.
  const firstRun = useRef(true);
  useEffect(() => {
    if (firstRun.current) {
      firstRun.current = false;
      return;
    }
    void start();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deviceIndex]);

  return (
    <div className={cn("grid gap-2", className)}>
      <div className={cn("relative overflow-hidden rounded-xl bg-black", active ? "aspect-video" : "hidden")}>
        <video ref={video} className="size-full object-cover" muted playsInline aria-label="Pratinjau kamera" />
        <div className="pointer-events-none absolute inset-x-8 top-1/2 h-20 -translate-y-1/2 rounded-lg border-2 border-white/80 shadow-[0_0_0_9999px_rgba(0,0,0,0.25)]" />
        <div className="absolute top-2 right-2 flex gap-1">
          {torch !== null && (
            <Button size="icon-sm" variant="secondary" onClick={toggleTorch} aria-label="Senter">
              <Flashlight className={torch ? "text-amber-500" : undefined} />
            </Button>
          )}
          {devices.length > 1 && (
            <Button size="icon-sm" variant="secondary" onClick={switchCamera} aria-label="Ganti kamera">
              <SwitchCamera />
            </Button>
          )}
        </div>
      </div>
      {error && <p className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">{error}</p>}
      <Button type="button" variant={active ? "outline" : "secondary"} onClick={active ? stop : start} disabled={starting}>
        {starting ? <Loader2 className="animate-spin" /> : active ? <CameraOff /> : <Camera />}
        {active ? "Matikan kamera" : "Scan pakai kamera"}
      </Button>
    </div>
  );
}
