#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::TcpListener;
use std::path::{Path, PathBuf};
use std::process::{Child, Command};
use std::collections::HashSet;
use std::sync::{Arc, Mutex};
use std::time::{SystemTime, UNIX_EPOCH};
use std::time::Duration;

use anyhow::{Context, Result};
use rand::{distributions::Alphanumeric, Rng};
use serde::Serialize;
use tauri::{Emitter, Manager};

const STARTUP_READY_TIMEOUT_SEC: u64 = 60;

struct AppRuntime {
    backend_base_url: String,
    auth_token: String,
    child: Arc<Mutex<Option<Child>>>,
}

struct MacPerfInner {
    next_token: u64,
    active_tokens: HashSet<u64>,
    caffeinate_child: Option<Child>,
}

impl Default for MacPerfInner {
    fn default() -> Self {
        Self {
            next_token: 1,
            active_tokens: HashSet::new(),
            caffeinate_child: None,
        }
    }
}

struct MacPerfState {
    inner: Arc<Mutex<MacPerfInner>>,
}

impl Default for MacPerfState {
    fn default() -> Self {
        Self {
            inner: Arc::new(Mutex::new(MacPerfInner::default())),
        }
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct RuntimeConfigPayload {
    backend_base_url: String,
    auth_token: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct PerfSessionPayload {
    token: u64,
    active: bool,
    active_tokens: usize,
    caffeinate_active: bool,
    message: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct MacRuntimeStatePayload {
    platform: String,
    thermal_level: String,
    cpu_speed_limit: Option<i32>,
    scheduler_limit: Option<i32>,
    available_cpus: Option<i32>,
    low_power_mode: Option<bool>,
    perf_active_tokens: usize,
    caffeinate_active: bool,
    source: String,
    timestamp_ms: u128,
}

#[tauri::command]
fn get_runtime_config(state: tauri::State<'_, AppRuntime>) -> RuntimeConfigPayload {
    RuntimeConfigPayload {
        backend_base_url: state.backend_base_url.clone(),
        auth_token: state.auth_token.clone(),
    }
}

fn now_unix_ms() -> u128 {
    match SystemTime::now().duration_since(UNIX_EPOCH) {
        Ok(duration) => duration.as_millis(),
        Err(_) => 0,
    }
}

fn run_command_output(program: &str, args: &[&str]) -> Option<String> {
    let output = Command::new(program).args(args).output().ok()?;
    let stdout = String::from_utf8_lossy(&output.stdout).to_string();
    if !stdout.trim().is_empty() {
        return Some(stdout);
    }
    let stderr = String::from_utf8_lossy(&output.stderr).to_string();
    if !stderr.trim().is_empty() {
        return Some(stderr);
    }
    None
}

fn extract_int_from_key(output: &str, key: &str) -> Option<i32> {
    for line in output.lines() {
        let lower = line.to_lowercase();
        if !lower.contains(&key.to_lowercase()) {
            continue;
        }
        let mut number = String::new();
        let mut seen_digit = false;
        for ch in line.chars() {
            if ch.is_ascii_digit() || (ch == '-' && !seen_digit && number.is_empty()) {
                number.push(ch);
                seen_digit = seen_digit || ch.is_ascii_digit();
            } else if seen_digit {
                break;
            }
        }
        if number.is_empty() {
            continue;
        }
        if let Ok(value) = number.parse::<i32>() {
            return Some(value);
        }
    }
    None
}

fn infer_thermal_level(
    thermal_level_raw: Option<i32>,
    cpu_speed_limit: Option<i32>,
    scheduler_limit: Option<i32>,
    therm_output: &str,
) -> String {
    if let Some(level) = thermal_level_raw {
        return match level {
            x if x >= 3 => "critical".to_string(),
            2 => "serious".to_string(),
            1 => "fair".to_string(),
            _ => "nominal".to_string(),
        };
    }

    let min_limit = match (cpu_speed_limit, scheduler_limit) {
        (Some(cpu), Some(sched)) => Some(cpu.min(sched)),
        (Some(cpu), None) => Some(cpu),
        (None, Some(sched)) => Some(sched),
        (None, None) => None,
    };
    if let Some(limit) = min_limit {
        if limit <= 50 {
            return "critical".to_string();
        }
        if limit <= 75 {
            return "serious".to_string();
        }
        if limit <= 90 {
            return "fair".to_string();
        }
        return "nominal".to_string();
    }

    if therm_output.to_lowercase().contains("no thermal warning") {
        return "nominal".to_string();
    }
    "unknown".to_string()
}

fn detect_low_power_mode() -> Option<bool> {
    let output = run_command_output("pmset", &["-g"])?;
    for line in output.lines() {
        let lowered = line.to_lowercase();
        if !lowered.contains("lowpowermode") {
            continue;
        }
        let mut maybe_value: Option<i32> = None;
        for token in lowered.split(|c: char| c.is_whitespace() || c == '=') {
            if token.is_empty() {
                continue;
            }
            if let Ok(value) = token.parse::<i32>() {
                maybe_value = Some(value);
            }
        }
        if let Some(value) = maybe_value {
            return Some(value >= 1);
        }
        if lowered.contains("=1") || lowered.contains("= 1") {
            return Some(true);
        }
        if lowered.contains("=0") || lowered.contains("= 0") {
            return Some(false);
        }
    }
    None
}

fn snapshot_macos_runtime_state(
    perf_active_tokens: usize,
    caffeinate_active: bool,
) -> MacRuntimeStatePayload {
    #[cfg(target_os = "macos")]
    {
        let therm_output = run_command_output("pmset", &["-g", "therm"]).unwrap_or_default();
        let cpu_speed_limit = extract_int_from_key(&therm_output, "cpu_speed_limit");
        let scheduler_limit = extract_int_from_key(&therm_output, "scheduler_limit");
        let available_cpus = extract_int_from_key(&therm_output, "cpu_available_cpus");
        let thermal_level_raw = extract_int_from_key(&therm_output, "thermal level");
        let thermal_level = infer_thermal_level(
            thermal_level_raw,
            cpu_speed_limit,
            scheduler_limit,
            &therm_output,
        );

        return MacRuntimeStatePayload {
            platform: "macos".to_string(),
            thermal_level,
            cpu_speed_limit,
            scheduler_limit,
            available_cpus,
            low_power_mode: detect_low_power_mode(),
            perf_active_tokens,
            caffeinate_active,
            source: "pmset".to_string(),
            timestamp_ms: now_unix_ms(),
        };
    }

    #[cfg(not(target_os = "macos"))]
    {
        MacRuntimeStatePayload {
            platform: std::env::consts::OS.to_string(),
            thermal_level: "unknown".to_string(),
            cpu_speed_limit: None,
            scheduler_limit: None,
            available_cpus: None,
            low_power_mode: None,
            perf_active_tokens,
            caffeinate_active,
            source: "unsupported".to_string(),
            timestamp_ms: now_unix_ms(),
        }
    }
}

fn ensure_caffeinate_running(inner: &mut MacPerfInner) -> Result<()> {
    #[cfg(target_os = "macos")]
    {
        if inner.caffeinate_child.is_none() {
            let child = Command::new("caffeinate")
                .args(["-dimsu"])
                .spawn()
                .context("failed to spawn caffeinate")?;
            inner.caffeinate_child = Some(child);
        }
    }
    Ok(())
}

fn stop_caffeinate(inner: &mut MacPerfInner) {
    if let Some(mut child) = inner.caffeinate_child.take() {
        let _ = child.kill();
    }
}

#[tauri::command]
fn perf_begin(
    reason: Option<String>,
    state: tauri::State<'_, MacPerfState>,
) -> PerfSessionPayload {
    let reason_text = reason.unwrap_or_else(|| "unspecified".to_string());
    let mut guard = match state.inner.lock() {
        Ok(guard) => guard,
        Err(_) => {
            return PerfSessionPayload {
                token: 0,
                active: false,
                active_tokens: 0,
                caffeinate_active: false,
                message: "perf lock poisoned".to_string(),
            }
        }
    };

    let token = guard.next_token;
    guard.next_token = guard.next_token.saturating_add(1);
    guard.active_tokens.insert(token);

    let session_active = if let Err(err) = ensure_caffeinate_running(&mut guard) {
        guard.active_tokens.remove(&token);
        return PerfSessionPayload {
            token: 0,
            active: false,
            active_tokens: guard.active_tokens.len(),
            caffeinate_active: guard.caffeinate_child.is_some(),
            message: format!("perf begin failed: {}", err),
        };
    } else {
        true
    };

    PerfSessionPayload {
        token,
        active: session_active,
        active_tokens: guard.active_tokens.len(),
        caffeinate_active: guard.caffeinate_child.is_some(),
        message: format!("perf session started ({reason_text})"),
    }
}

#[tauri::command]
fn perf_end(token: u64, state: tauri::State<'_, MacPerfState>) -> PerfSessionPayload {
    let mut guard = match state.inner.lock() {
        Ok(guard) => guard,
        Err(_) => {
            return PerfSessionPayload {
                token,
                active: false,
                active_tokens: 0,
                caffeinate_active: false,
                message: "perf lock poisoned".to_string(),
            }
        }
    };

    let removed = guard.active_tokens.remove(&token);
    if guard.active_tokens.is_empty() {
        stop_caffeinate(&mut guard);
    }

    PerfSessionPayload {
        token,
        active: !guard.active_tokens.is_empty(),
        active_tokens: guard.active_tokens.len(),
        caffeinate_active: guard.caffeinate_child.is_some(),
        message: if removed {
            "perf session ended".to_string()
        } else {
            "perf session token not found".to_string()
        },
    }
}

#[tauri::command]
fn macos_runtime_state(state: tauri::State<'_, MacPerfState>) -> MacRuntimeStatePayload {
    let (active_tokens, caffeinate_active) = match state.inner.lock() {
        Ok(guard) => (guard.active_tokens.len(), guard.caffeinate_child.is_some()),
        Err(_) => (0, false),
    };
    snapshot_macos_runtime_state(active_tokens, caffeinate_active)
}

fn choose_free_port() -> Result<u16> {
    let listener = TcpListener::bind("127.0.0.1:0").context("bind local random port failed")?;
    let port = listener
        .local_addr()
        .context("read random local address failed")?
        .port();
    drop(listener);
    Ok(port)
}

fn random_token() -> String {
    rand::thread_rng()
        .sample_iter(&Alphanumeric)
        .take(40)
        .map(char::from)
        .collect()
}

fn resolve_workspace_root() -> Result<PathBuf> {
    let cwd = std::env::current_dir().context("resolve current dir failed")?;
    let cwd_backend = cwd.join("backend");
    if cwd_backend.exists() {
        return Ok(cwd);
    }
    let parent = cwd.parent().unwrap_or(cwd.as_path()).to_path_buf();
    let parent_backend = parent.join("backend");
    if parent_backend.exists() {
        return Ok(parent);
    }
    Ok(cwd)
}

fn find_sidecar_path(app: &tauri::AppHandle) -> Result<(PathBuf, Vec<String>)> {
    if let Ok(path) = std::env::var("FILESMIND_SIDECAR_PATH") {
        let trimmed = path.trim();
        if !trimmed.is_empty() {
            return Ok((PathBuf::from(trimmed), Vec::new()));
        }
    }

    if cfg!(debug_assertions) {
        let workspace_root = resolve_workspace_root()?;
        let script = workspace_root.join("backend").join("desktop_server.py");
        return Ok((PathBuf::from("python"), vec![script.to_string_lossy().to_string()]));
    }

    let binary_name = if cfg!(target_os = "windows") {
        "filesmind-backend.exe"
    } else {
        "filesmind-backend"
    };

    let mut candidates: Vec<PathBuf> = Vec::new();
    if let Ok(current_exe) = std::env::current_exe() {
        if let Some(exe_dir) = current_exe.parent() {
            candidates.push(exe_dir.join(binary_name));
        }
    }
    if let Ok(resource_dir) = app.path().resource_dir() {
        candidates.push(resource_dir.join("binaries").join(binary_name));
        candidates.push(resource_dir.join(binary_name));
    }

    for candidate in &candidates {
        if candidate.exists() {
            return Ok((candidate.clone(), Vec::new()));
        }
    }

    anyhow::bail!(
        "backend sidecar not found; checked: {}",
        candidates
            .iter()
            .map(|path| path.display().to_string())
            .collect::<Vec<_>>()
            .join(", ")
    )
}

fn ensure_app_data_dir(app: &tauri::AppHandle) -> Result<PathBuf> {
    let app_data_dir = app.path().app_data_dir().context("resolve app data dir failed")?;
    std::fs::create_dir_all(&app_data_dir)
        .with_context(|| format!("create app data dir failed: {}", app_data_dir.display()))?;
    Ok(app_data_dir)
}

fn spawn_backend(app: &tauri::AppHandle) -> Result<(Child, String, String)> {
    let port = choose_free_port()?;
    let token = random_token();
    let base_url = format!("http://127.0.0.1:{port}");
    let app_data_dir = ensure_app_data_dir(app)?;
    let (cmd_path, cmd_args) = find_sidecar_path(app)?;

    let mut cmd = Command::new(&cmd_path);
    if !cmd_args.is_empty() {
        cmd.args(cmd_args);
    }

    cmd.env("FILESMIND_HOST", "127.0.0.1")
        .env("FILESMIND_PORT", port.to_string())
        .env("FILESMIND_AUTH_TOKEN", token.clone())
        .env("FILESMIND_DATA_DIR", app_data_dir.join("data"))
        .env("FILESMIND_LOG_DIR", app_data_dir.join("logs"))
        .env("FILESMIND_APP_VERSION", env!("CARGO_PKG_VERSION"))
        .env("PYTORCH_ENABLE_MPS_FALLBACK", "1");

    if cfg!(debug_assertions) {
        let workspace_root = resolve_workspace_root()?;
        if Path::new(&workspace_root).exists() {
            cmd.current_dir(workspace_root);
        }
    }

    let child = cmd
        .spawn()
        .with_context(|| format!("spawn backend sidecar failed: {}", cmd_path.display()))?;

    Ok((child, base_url, token))
}

async fn wait_for_backend_ready(base_url: &str, token: &str, timeout_sec: u64) -> Result<()> {
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(4))
        .build()
        .context("build readiness http client failed")?;
    let start = std::time::Instant::now();
    let mut delay = Duration::from_millis(150);

    loop {
        let url = format!("{base_url}/ready");
        let response = client
            .get(url)
            .header("X-FilesMind-Token", token)
            .send()
            .await;
        if let Ok(resp) = response {
            if resp.status().is_success() {
                return Ok(());
            }
        }

        if start.elapsed() > Duration::from_secs(timeout_sec) {
            anyhow::bail!("backend readiness timeout after {timeout_sec}s");
        }

        tokio::time::sleep(delay).await;
        delay = std::cmp::min(delay.saturating_mul(2), Duration::from_secs(2));
    }
}

fn js_escape(value: &str) -> String {
    value
        .replace('\\', "\\\\")
        .replace('"', "\\\"")
        .replace('\n', "\\n")
        .replace('\r', "")
}

fn inject_runtime_to_window(app: &tauri::AppHandle, base_url: &str, token: &str) {
    if let Some(window) = app.get_webview_window("main") {
        let js = format!(
            "window.__FILESMIND_RUNTIME__ = {{ backendBaseUrl: \"{}\", authToken: \"{}\" }};",
            js_escape(base_url),
            js_escape(token)
        );
        let _ = window.eval(&js);
    }
}

fn fallback_runtime(app: &tauri::AppHandle, error: String) {
    eprintln!("backend bootstrap failed: {error}");
    app.manage(AppRuntime {
        backend_base_url: String::new(),
        auth_token: String::new(),
        child: Arc::new(Mutex::new(None)),
    });
    inject_runtime_to_window(app, "", "");
    let _ = app.emit(
        "backend-failed",
        serde_json::json!({
            "ready": false,
            "error": error
        }),
    );
}

fn main() {
    tauri::Builder::default()
        .setup(|app| {
            app.manage(MacPerfState::default());

            match spawn_backend(&app.handle()) {
                Ok((child, base_url, token)) => {
                    app.manage(AppRuntime {
                        backend_base_url: base_url.clone(),
                        auth_token: token.clone(),
                        child: Arc::new(Mutex::new(Some(child))),
                    });

                    inject_runtime_to_window(&app.handle(), &base_url, &token);

                    let app_handle = app.handle().clone();
                    tauri::async_runtime::spawn(async move {
                        match wait_for_backend_ready(&base_url, &token, STARTUP_READY_TIMEOUT_SEC).await {
                            Ok(_) => {
                                let _ = app_handle.emit("backend-ready", serde_json::json!({"ready": true}));
                            }
                            Err(err) => {
                                let _ = app_handle.emit(
                                    "backend-failed",
                                    serde_json::json!({"ready": false, "error": err.to_string()}),
                                );
                            }
                        }
                    });
                }
                Err(err) => fallback_runtime(&app.handle(), err.to_string()),
            }

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_runtime_config,
            perf_begin,
            perf_end,
            macos_runtime_state
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            if let tauri::RunEvent::Exit = event {
                let child_handle = app_handle
                    .try_state::<AppRuntime>()
                    .map(|state| state.child.clone());
                let child_to_kill = child_handle
                    .and_then(|handle| handle.lock().ok().and_then(|mut guard| guard.take()));
                if let Some(mut child) = child_to_kill {
                    let _ = child.kill();
                }

                if let Some(perf_state) = app_handle.try_state::<MacPerfState>() {
                    if let Ok(mut guard) = perf_state.inner.lock() {
                        guard.active_tokens.clear();
                        stop_caffeinate(&mut guard);
                    }
                }
            }
        });
}
