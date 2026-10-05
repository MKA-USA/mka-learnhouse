/** Typed errors. Messages never contain tokens or response bodies. */
export class LhError extends Error {
  constructor(message: string, readonly method: string, readonly path: string) {
    super(message);
    this.name = "LhError";
  }
}

export class LhHttpError extends LhError {
  constructor(
    method: string, path: string, readonly status: number,
    /** LearnHouse `detail` string, kept off `message` because it may contain PII (emails). */
    readonly detail?: string,
  ) {
    super(`LearnHouse ${method} ${path} -> HTTP ${status}`, method, path);
    this.name = "LhHttpError";
  }
  get isAuth() { return this.status === 401; }
  get isForbidden() { return this.status === 403; }
  get isNotFound() { return this.status === 404; }
}

export class LhNetworkError extends LhError {
  constructor(method: string, path: string, readonly attempts: number, cause?: unknown) {
    super(`LearnHouse ${method} ${path} -> network error after ${attempts} attempt(s)`, method, path);
    this.name = "LhNetworkError";
    if (cause !== undefined) (this as { cause?: unknown }).cause = cause;
  }
}

export class LhConfigError extends Error {
  constructor(message: string) { super(message); this.name = "LhConfigError"; }
}

/** Strip PII-bearing path segments (emails) before they reach errors/logs. */
export function redactPath(path: string): string {
  return path
    .replace(/(\/users\/by-email\/)[^/?]+/, "$1:email")
    .replace(/\/\/+/g, "/");
}
