// Opmiere desktop host (Tauri). UI is WebView; craft logic stays in Python core.
// No agent chat panel (ADR_UI_AND_PREVIEW).

use serde::Serialize;
use std::fs;
use std::net::TcpStream;
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;

/// PID of a core API we started ourselves (not pre-existing servers).
static OWNED_CORE_PID: Mutex<Option<u32>> = Mutex::new(None);

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct EnsureCoreResult {
    ok: bool,
    started: bool,
    already_up: bool,
    message: String,
    pid: Option<u32>,
    python: Option<String>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct StopCoreResult {
    ok: bool,
    stopped: bool,
    message: String,
    pid: Option<u32>,
}

fn api_port_open() -> bool {
    TcpStream::connect_timeout(
        &"127.0.0.1:8787".parse().unwrap(),
        Duration::from_millis(400),
    )
    .is_ok()
}

fn read_install_python() -> Option<PathBuf> {
    let local = std::env::var_os("LOCALAPPDATA")?;
    let marker = PathBuf::from(local).join("Opmiere").join("install.json");
    let text = fs::read_to_string(marker).ok()?;
    let v: serde_json::Value = serde_json::from_str(&text).ok()?;
    let py = v.get("python")?.as_str()?;
    let path = PathBuf::from(py);
    if path.is_file() {
        Some(path)
    } else {
        None
    }
}

fn resolve_python() -> Option<PathBuf> {
    if let Some(p) = read_install_python() {
        return Some(p);
    }
    for name in ["python", "python3", "py"] {
        if let Ok(out) = Command::new("where").arg(name).output() {
            if out.status.success() {
                let stdout = String::from_utf8_lossy(&out.stdout);
                if let Some(line) = stdout.lines().next() {
                    let p = PathBuf::from(line.trim());
                    if p.is_file() {
                        return Some(p);
                    }
                }
            }
        }
    }
    None
}

fn spawn_core(python: &PathBuf) -> Result<u32, String> {
    let mut cmd = Command::new(python);
    cmd.args(["-m", "opmiere.web.app"])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    let child = cmd
        .spawn()
        .map_err(|e| format!("spawn failed: {e} (python={})", python.display()))?;
    Ok(child.id())
}

fn kill_pid(pid: u32) -> Result<(), String> {
    #[cfg(windows)]
    {
        let status = Command::new("taskkill")
            .args(["/PID", &pid.to_string(), "/T", "/F"])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .map_err(|e| format!("taskkill failed: {e}"))?;
        if status.success() {
            Ok(())
        } else {
            Err(format!("taskkill exit {:?}", status.code()))
        }
    }
    #[cfg(not(windows))]
    {
        let status = Command::new("kill")
            .args(["-TERM", &pid.to_string()])
            .status()
            .map_err(|e| format!("kill failed: {e}"))?;
        if status.success() {
            Ok(())
        } else {
            Err(format!("kill exit {:?}", status.code()))
        }
    }
}

fn stop_owned_core() -> StopCoreResult {
    let pid = {
        let mut guard = OWNED_CORE_PID.lock().unwrap_or_else(|e| e.into_inner());
        guard.take()
    };
    match pid {
        None => StopCoreResult {
            ok: true,
            stopped: false,
            message: "No owned core process".into(),
            pid: None,
        },
        Some(pid) => match kill_pid(pid) {
            Ok(()) => StopCoreResult {
                ok: true,
                stopped: true,
                message: format!("Stopped core API (pid {pid})"),
                pid: Some(pid),
            },
            Err(e) => StopCoreResult {
                ok: false,
                stopped: false,
                message: format!("Failed to stop pid {pid}: {e}"),
                pid: Some(pid),
            },
        },
    }
}

/// Ensure Opmiere Python core API is listening on 127.0.0.1:8787.
/// If down, start `python -m opmiere.web.app` from install marker or PATH.
#[tauri::command]
fn ensure_core_api() -> EnsureCoreResult {
    if api_port_open() {
        return EnsureCoreResult {
            ok: true,
            started: false,
            already_up: true,
            message: "Core API already up on :8787".into(),
            pid: None,
            python: None,
        };
    }

    let Some(python) = resolve_python() else {
        return EnsureCoreResult {
            ok: false,
            started: false,
            already_up: false,
            message: "No Python found (install Opmiere or put python on PATH)".into(),
            pid: None,
            python: None,
        };
    };

    let py_s = python.display().to_string();
    match spawn_core(&python) {
        Ok(pid) => {
            if let Ok(mut guard) = OWNED_CORE_PID.lock() {
                *guard = Some(pid);
            }
            let mut up = false;
            for _ in 0..20 {
                thread::sleep(Duration::from_millis(250));
                if api_port_open() {
                    up = true;
                    break;
                }
            }
            EnsureCoreResult {
                ok: up,
                started: true,
                already_up: false,
                message: if up {
                    format!("Started core API (pid {pid})")
                } else {
                    format!(
                        "Spawned core API (pid {pid}) but :8787 not open yet — wait and Refresh"
                    )
                },
                pid: Some(pid),
                python: Some(py_s),
            }
        }
        Err(e) => EnsureCoreResult {
            ok: false,
            started: false,
            already_up: false,
            message: e,
            pid: None,
            python: Some(py_s),
        },
    }
}

/// Stop a core API process we started (no-op if we did not own it).
#[tauri::command]
fn stop_core_api() -> StopCoreResult {
    stop_owned_core()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![ensure_core_api, stop_core_api])
        .build(tauri::generate_context!())
        .expect("error while building Opmiere desktop")
        .run(|_app, event| {
            if let tauri::RunEvent::Exit = event {
                let _ = stop_owned_core();
            }
        });
}
