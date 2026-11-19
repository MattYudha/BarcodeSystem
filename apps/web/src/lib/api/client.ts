import createClient, { type Middleware } from "openapi-fetch";

import type { components, paths } from "./schema";

export type Schemas = components["schemas"];
export type Me = Schemas["MeOut"];
export type Product = Schemas["ProductOut"];
export type Variant = Schemas["VariantOut"];
export type Category = Schemas["CategoryOut"];
export type Movement = Schemas["MovementOut"];

/** Error dari API: {code, message (Bahasa Indonesia), details}. */
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const NETWORK_ERROR = "Tidak dapat terhubung ke server. Periksa koneksi internet.";

function toApiError(status: number, body: unknown): ApiError {
  if (body && typeof body === "object" && "code" in body && "message" in body) {
    const b = body as { code: string; message: string; details?: Record<string, unknown> };
    // Pesan validasi pertama yang lebih spesifik (mis. "Baris 2: alasan keluar wajib diisi").
    const first = (b.details?.errors as { msg?: string }[] | undefined)?.[0]?.msg;
    const message =
      b.code === "VALIDATION_ERROR" && first ? first.replace(/^Value error, /, "") : b.message;
    return new ApiError(status, b.code, message, b.details ?? {});
  }
  // Respons non-JSON (mis. 500/502 dari proxy saat API mati) -> pesan yang menjelaskan keadaannya.
  if (status >= 500) {
    return new ApiError(status, "API_UNAVAILABLE", "Server sedang tidak dapat dihubungi. Coba beberapa saat lagi.");
  }
  return new ApiError(status, "INTERNAL_ERROR", "Terjadi kesalahan pada server.");
}

/** UUID v4 yang tetap jalan di konteks non-HTTPS (crypto.randomUUID butuh secure context). */
export function uuid(): string {
  if (typeof crypto.randomUUID === "function" && globalThis.isSecureContext) {
    return crypto.randomUUID();
  }
  const b = crypto.getRandomValues(new Uint8Array(16));
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

const DEVICE_KEY = "bhv.device_id";

/** ID perangkat permanen per browser (dicatat pada sesi -> jejak perangkat transaksi, F-17). */
export function deviceId(): string {
  let id = localStorage.getItem(DEVICE_KEY);
  if (!id) {
    id = uuid();
    localStorage.setItem(DEVICE_KEY, id);
  }
  return id;
}

export const UNAUTHENTICATED_EVENT = "bhv:unauthenticated";

const middleware: Middleware = {
  onRequest({ request }) {
    if (typeof window !== "undefined") request.headers.set("X-Device-Id", deviceId());
    return request;
  },
  onResponse({ response, request }) {
    if (
      response.status === 401 &&
      typeof window !== "undefined" &&
      !new URL(request.url).pathname.endsWith("/auth/login")
    ) {
      window.dispatchEvent(new Event(UNAUTHENTICATED_EVENT));
    }
    return response;
  },
};

export const api = createClient<paths>({ baseUrl: "" });
api.use(middleware);

type Result<T> = { data?: T; error?: unknown; response: Response };

/** Jalankan panggilan openapi-fetch; lempar ApiError bila gagal. */
export async function unwrap<T>(call: Promise<Result<T>>): Promise<T> {
  let res: Result<T>;
  try {
    res = await call;
  } catch {
    throw new ApiError(0, "NETWORK_ERROR", NETWORK_ERROR);
  }
  if (!res.response.ok) throw toApiError(res.response.status, res.error);
  return res.data as T;
}

/** Untuk respons biner (PDF label, CSV). */
export async function fetchBlob(
  path: string,
  init: RequestInit = {},
): Promise<{ blob: Blob; filename: string | null }> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: { "X-Device-Id": deviceId(), ...(init.headers ?? {}) },
    });
  } catch {
    throw new ApiError(0, "NETWORK_ERROR", NETWORK_ERROR);
  }
  if (!response.ok) {
    if (response.status === 401) window.dispatchEvent(new Event(UNAUTHENTICATED_EVENT));
    throw toApiError(response.status, await response.json().catch(() => null));
  }
  const cd = response.headers.get("content-disposition") ?? "";
  const filename = /filename="([^"]+)"/.exec(cd)?.[1] ?? null;
  return { blob: await response.blob(), filename };
}

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  return "Terjadi kesalahan yang tidak terduga.";
}
