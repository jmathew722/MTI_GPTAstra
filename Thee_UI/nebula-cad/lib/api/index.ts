import type { ApiAdapter } from "./adapter";
import { httpAdapter } from "./http";
import { mockAdapter } from "./mock";

/** One env var switches the data source: NEXT_PUBLIC_API_MODE=mock (default) | http */
export const API_MODE: "mock" | "http" = process.env.NEXT_PUBLIC_API_MODE === "http" ? "http" : "mock";
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";
export const api: ApiAdapter = API_MODE === "http" ? httpAdapter : mockAdapter;
export const IS_MOCK = API_MODE === "mock";

export { ApiError } from "./adapter";
export type { ApiAdapter, ItemReviewInput, SignOffInput } from "./adapter";
