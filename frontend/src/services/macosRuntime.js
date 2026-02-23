const resolveDesktopInvoke = () => {
  if (typeof window === 'undefined') return null;
  const directInvoke = window.__TAURI__?.core?.invoke;
  if (typeof directInvoke === 'function') return directInvoke;
  const internalInvoke = window.__TAURI_INTERNALS__?.invoke;
  if (typeof internalInvoke === 'function') return internalInvoke;
  return null;
};

const invokeDesktopCommand = async (command, payload = {}) => {
  const invoke = resolveDesktopInvoke();
  if (!invoke) return null;
  try {
    return await invoke(command, payload);
  } catch (error) {
    console.warn(`Desktop command failed: ${command}`, error);
    return null;
  }
};

export const canUseDesktopPerfBridge = () => Boolean(resolveDesktopInvoke());

export const perfBegin = async (reason = 'workspace-task') => {
  return invokeDesktopCommand('perf_begin', { reason });
};

export const perfEnd = async (token) => {
  const numericToken = Number(token);
  if (!Number.isFinite(numericToken) || numericToken <= 0) return null;
  return invokeDesktopCommand('perf_end', { token: Math.trunc(numericToken) });
};

export const fetchMacosRuntimeState = async () => {
  return invokeDesktopCommand('macos_runtime_state');
};
