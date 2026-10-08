import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { APIResponse } from '@/lib/types';

/** Generic GET hook with TanStack Query. */
export function useApiQuery<T>(key: string[], url: string, options?: { enabled?: boolean }) {
  return useQuery<APIResponse<T>>({
    queryKey: key,
    queryFn: () => api.get<T>(url),
    enabled: options?.enabled,
  });
}

/** Generic POST mutation hook. */
export function useApiMutation<TReq, TRes>(
  url: string,
  options?: {
    invalidateKeys?: string[][];
    onSuccess?: (data: APIResponse<TRes>) => void;
  },
) {
  const queryClient = useQueryClient();
  return useMutation<APIResponse<TRes>, Error, TReq>({
    mutationFn: (body: TReq) => api.post<TRes>(url, body),
    onSuccess: (data) => {
      options?.invalidateKeys?.forEach((key) => queryClient.invalidateQueries({ queryKey: key }));
      options?.onSuccess?.(data);
    },
  });
}

/** File upload mutation. */
export function useUploadMutation<T>(
  url: string,
  options?: { invalidateKeys?: string[][] },
) {
  const queryClient = useQueryClient();
  return useMutation<APIResponse<T>, Error, File>({
    mutationFn: (file: File) => api.upload<T>(url, file),
    onSuccess: () => {
      options?.invalidateKeys?.forEach((key) => queryClient.invalidateQueries({ queryKey: key }));
    },
  });
}
