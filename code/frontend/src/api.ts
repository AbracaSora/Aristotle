export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

export function createApiClient(
  token = "",
  base = import.meta.env.VITE_API_BASE_URL || "/api/v1",
) {
  return {
    async request<T>(path: string, method = "GET", body?: unknown): Promise<T> {
      let response: Response;
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 15000);
      try {
        response = await fetch(base + path, {
          method,
          headers: {
            ...(body === undefined
              ? {}
              : { "Content-Type": "application/json" }),
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          ...(body === undefined ? {} : { body: JSON.stringify(body) }),
          signal: controller.signal,
        });
      } catch (reason) {
        if (reason instanceof DOMException && reason.name === "AbortError") {
          throw new ApiError(408, "学习服务响应超时，请稍后重试。");
        }
        throw new ApiError(0, "无法连接学习服务，请检查连接后重试。");
      } finally {
        clearTimeout(timeout);
      }
      if (response.status === 204) return undefined as T;
      let data: any;
      try {
        data = await response.json();
      } catch {
        throw new ApiError(
          response.status || 502,
          "服务返回了无法读取的响应，请稍后重试。",
        );
      }
      if (!response.ok) {
        const fields = data?.error?.fields
          ?.map((field: { message: string }) => field.message)
          .join("；");
        throw new ApiError(
          response.status,
          [data?.error?.message || `请求失败（${response.status}）`, fields]
            .filter(Boolean)
            .join("："),
        );
      }
      return data as T;
    },
  };
}
