use serde::{Deserialize, Serialize};
use std::{
    fs,
    path::PathBuf,
    sync::Mutex,
    time::{SystemTime, UNIX_EPOCH},
};
#[cfg(not(debug_assertions))]
use std::{
    io::{Read, Write},
    net::{SocketAddr, TcpStream},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    time::Duration,
};
use tauri::{Manager, RunEvent};
use tauri_plugin_shell::process::CommandChild;
#[cfg(not(debug_assertions))]
use tauri_plugin_shell::{process::CommandEvent, ShellExt};
use tauri_plugin_updater::UpdaterExt;

const CREDENTIAL_SERVICE: &str = "com.lorasuite.credentials";
const STABLE_UPDATE_ENDPOINT: &str =
    "https://github.com/MichaelDanCurtis/LoraSuite/releases/latest/download/latest.json";
const ROLLBACK_UPDATE_ENDPOINT: &str =
    "https://github.com/MichaelDanCurtis/LoraSuite/releases/latest/download/rollback.json";
const UPDATER_PUBLIC_KEY: Option<&str> = option_env!("LORASUITE_UPDATER_PUBLIC_KEY");
#[cfg(not(debug_assertions))]
const ENGINE_SIDECAR: &str = "lorasuite-engine";
const CREDENTIAL_IDS: &[&str] = &[
    "runcomfy_api",
    "runpod_api",
    "runpod_s3_access",
    "runpod_s3_secret",
    "huggingface_token",
    "openai_api",
    "xai_api",
    "kimi_code_api",
    "moonshot_api",
];

#[derive(Serialize)]
struct CredentialStatus {
    id: String,
    stored: bool,
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
#[serde(rename_all = "lowercase")]
enum UpdateChannel {
    Stable,
    Rollback,
}

impl UpdateChannel {
    fn endpoint(self) -> &'static str {
        match self {
            Self::Stable => STABLE_UPDATE_ENDPOINT,
            Self::Rollback => ROLLBACK_UPDATE_ENDPOINT,
        }
    }

    fn label(self) -> &'static str {
        match self {
            Self::Stable => "stable",
            Self::Rollback => "rollback",
        }
    }
}

#[derive(Clone, Debug, Serialize)]
struct DesktopUpdateStatus {
    configured: bool,
    channel: UpdateChannel,
    current_version: String,
    available: bool,
    version: Option<String>,
    body: Option<String>,
    date: Option<String>,
    target: Option<String>,
    download_url: Option<String>,
    message: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
struct UpdateJournal {
    channel: UpdateChannel,
    from_version: String,
    to_version: String,
    state: String,
    message: String,
    updated_at_unix: u64,
}

struct EngineProcess(Mutex<Option<CommandChild>>);

#[tauri::command]
fn credential_status(id: String) -> Result<CredentialStatus, String> {
    let entry = credential_entry(&id)?;
    let stored = match entry.get_password() {
        Ok(_) => true,
        Err(keyring::Error::NoEntry) => false,
        Err(error) => return Err(credential_error("inspect", error)),
    };
    Ok(CredentialStatus { id, stored })
}

#[tauri::command]
fn credential_get(id: String) -> Result<Option<String>, String> {
    let entry = credential_entry(&id)?;
    match entry.get_password() {
        Ok(secret) => Ok(Some(secret)),
        Err(keyring::Error::NoEntry) => Ok(None),
        Err(error) => Err(credential_error("read", error)),
    }
}

#[tauri::command]
fn credential_set(id: String, secret: String) -> Result<CredentialStatus, String> {
    let value = secret.trim();
    if value.is_empty() {
        return Err("Credential value cannot be empty.".to_string());
    }
    if value.len() > 65_536 {
        return Err("Credential value is too large.".to_string());
    }
    let entry = credential_entry(&id)?;
    entry
        .set_password(value)
        .map_err(|error| credential_error("save", error))?;
    Ok(CredentialStatus { id, stored: true })
}

#[tauri::command]
fn credential_delete(id: String) -> Result<CredentialStatus, String> {
    let entry = credential_entry(&id)?;
    match entry.delete_credential() {
        Ok(()) | Err(keyring::Error::NoEntry) => Ok(CredentialStatus { id, stored: false }),
        Err(error) => Err(credential_error("delete", error)),
    }
}

fn credential_entry(id: &str) -> Result<keyring::Entry, String> {
    if !CREDENTIAL_IDS.contains(&id) {
        return Err("Unknown LoraSuite credential identifier.".to_string());
    }
    keyring::Entry::new(CREDENTIAL_SERVICE, id).map_err(|error| credential_error("open", error))
}

fn credential_error(action: &str, error: keyring::Error) -> String {
    format!("Unable to {action} the system credential store: {error}")
}

#[tauri::command]
async fn check_desktop_update(
    app: tauri::AppHandle,
    channel: UpdateChannel,
) -> Result<DesktopUpdateStatus, String> {
    let current_version = app.package_info().version.to_string();
    if !updater_is_configured() {
        return Ok(DesktopUpdateStatus {
            configured: false,
            channel,
            current_version,
            available: false,
            version: None,
            body: None,
            date: None,
            target: None,
            download_url: None,
            message: "Desktop updates are not configured in this build.".to_string(),
        });
    }

    let update = build_updater(&app, channel)?
        .check()
        .await
        .map_err(|error| {
            format!(
                "Unable to check the {} update channel: {error}",
                channel.label()
            )
        })?;
    let Some(update) = update else {
        return Ok(DesktopUpdateStatus {
            configured: true,
            channel,
            current_version,
            available: false,
            version: None,
            body: None,
            date: None,
            target: None,
            download_url: None,
            message: match channel {
                UpdateChannel::Stable => "LoraSuite is up to date.".to_string(),
                UpdateChannel::Rollback => "No signed rollback is available.".to_string(),
            },
        });
    };

    Ok(DesktopUpdateStatus {
        configured: true,
        channel,
        current_version,
        available: true,
        version: Some(update.version),
        body: update.body,
        date: update.date.map(|date| date.to_string()),
        target: Some(update.target),
        download_url: Some(update.download_url.to_string()),
        message: match channel {
            UpdateChannel::Stable => "A signed update is available.".to_string(),
            UpdateChannel::Rollback => "A signed previous release is available.".to_string(),
        },
    })
}

#[tauri::command]
async fn install_desktop_update(
    app: tauri::AppHandle,
    channel: UpdateChannel,
    version: String,
) -> Result<UpdateJournal, String> {
    if !updater_is_configured() {
        return Err("Desktop updates are not configured in this build.".to_string());
    }
    let expected_version = version.trim();
    if expected_version.is_empty() {
        return Err("An update version is required.".to_string());
    }

    let update = build_updater(&app, channel)?
        .check()
        .await
        .map_err(|error| {
            format!(
                "Unable to recheck the {} update channel: {error}",
                channel.label()
            )
        })?
        .ok_or_else(|| format!("The {} update is no longer available.", channel.label()))?;
    if update.version != expected_version {
        return Err(format!(
            "The signed update changed from {expected_version} to {}. Check again before installing.",
            update.version
        ));
    }

    let current_version = app.package_info().version.to_string();
    let mut journal = UpdateJournal {
        channel,
        from_version: current_version,
        to_version: update.version.clone(),
        state: "installing".to_string(),
        message: format!("Installing signed {} release.", channel.label()),
        updated_at_unix: unix_timestamp(),
    };
    write_update_journal(&app, &journal)?;

    if let Err(error) = update.download_and_install(|_, _| {}, || {}).await {
        journal.state = "failed".to_string();
        journal.message = format!("Signed update installation failed: {error}");
        journal.updated_at_unix = unix_timestamp();
        let _ = write_update_journal(&app, &journal);
        return Err(journal.message);
    }

    journal.state = "installed_pending_restart".to_string();
    journal.message = "Update installed and awaiting a verified restart.".to_string();
    journal.updated_at_unix = unix_timestamp();
    write_update_journal(&app, &journal)?;
    Ok(journal)
}

#[tauri::command]
fn desktop_update_journal(app: tauri::AppHandle) -> Result<Option<UpdateJournal>, String> {
    read_update_journal(&app)
}

fn updater_is_configured() -> bool {
    UPDATER_PUBLIC_KEY.is_some_and(|key| !key.trim().is_empty())
}

fn build_updater(
    app: &tauri::AppHandle,
    channel: UpdateChannel,
) -> Result<tauri_plugin_updater::Updater, String> {
    let endpoint = channel
        .endpoint()
        .parse()
        .map_err(|error| format!("Invalid {} update endpoint: {error}", channel.label()))?;
    let mut builder = app
        .updater_builder()
        .endpoints(vec![endpoint])
        .map_err(|error| {
            format!(
                "Unable to configure the {} update channel: {error}",
                channel.label()
            )
        })?;
    if matches!(channel, UpdateChannel::Rollback) {
        builder = builder.version_comparator(|current, release| {
            rollback_release_is_older(&current, &release.version)
        });
    }
    builder.build().map_err(|error| {
        format!(
            "Unable to initialize the {} updater: {error}",
            channel.label()
        )
    })
}

fn rollback_release_is_older(current: &semver::Version, release: &semver::Version) -> bool {
    release < current
}

fn update_journal_path(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    app.path()
        .app_data_dir()
        .map(|directory| directory.join("update-journal.json"))
        .map_err(|error| format!("Unable to locate the LoraSuite update journal: {error}"))
}

fn read_update_journal(app: &tauri::AppHandle) -> Result<Option<UpdateJournal>, String> {
    let path = update_journal_path(app)?;
    if !path.exists() {
        return Ok(None);
    }
    let data = fs::read(&path)
        .map_err(|error| format!("Unable to read the LoraSuite update journal: {error}"))?;
    serde_json::from_slice(&data)
        .map(Some)
        .map_err(|error| format!("Unable to parse the LoraSuite update journal: {error}"))
}

fn write_update_journal(app: &tauri::AppHandle, journal: &UpdateJournal) -> Result<(), String> {
    let path = update_journal_path(app)?;
    let directory = path
        .parent()
        .ok_or_else(|| "The LoraSuite update journal path has no parent directory.".to_string())?;
    fs::create_dir_all(directory).map_err(|error| {
        format!("Unable to create the LoraSuite update journal directory: {error}")
    })?;
    let temporary_path = path.with_extension("json.tmp");
    let data = serde_json::to_vec_pretty(journal)
        .map_err(|error| format!("Unable to encode the LoraSuite update journal: {error}"))?;
    fs::write(&temporary_path, data)
        .map_err(|error| format!("Unable to stage the LoraSuite update journal: {error}"))?;
    #[cfg(target_os = "windows")]
    if path.exists() {
        fs::remove_file(&path)
            .map_err(|error| format!("Unable to replace the LoraSuite update journal: {error}"))?;
    }
    fs::rename(&temporary_path, &path)
        .map_err(|error| format!("Unable to commit the LoraSuite update journal: {error}"))
}

#[cfg(not(debug_assertions))]
fn mark_update_launch_verified(app: &tauri::AppHandle) -> Result<(), String> {
    let Some(mut journal) = read_update_journal(app)? else {
        return Ok(());
    };
    if journal.state != "installed_pending_restart" {
        return Ok(());
    }
    journal.state = "launch_verified".to_string();
    journal.message = format!(
        "LoraSuite {} and its embedded engine started successfully.",
        app.package_info().version
    );
    journal.updated_at_unix = unix_timestamp();
    write_update_journal(app, &journal)
}

fn unix_timestamp() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |duration| duration.as_secs())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let mut updater_plugin = tauri_plugin_updater::Builder::new();
    if let Some(public_key) = UPDATER_PUBLIC_KEY.filter(|key| !key.trim().is_empty()) {
        updater_plugin = updater_plugin.pubkey(public_key);
    }
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_process::init())
        .plugin(updater_plugin.build())
        .plugin(
            tauri_plugin_log::Builder::default()
                .level(log::LevelFilter::Info)
                .build(),
        )
        .invoke_handler(tauri::generate_handler![
            credential_status,
            credential_get,
            credential_set,
            credential_delete,
            check_desktop_update,
            install_desktop_update,
            desktop_update_journal,
        ])
        .setup(|app| {
            #[cfg(not(debug_assertions))]
            let child = match start_packaged_engine(app.handle()) {
                Ok(child) => child,
                Err(error) => {
                    log::error!("Unable to start the packaged LoraSuite engine: {error}");
                    None
                }
            };
            #[cfg(debug_assertions)]
            let child = None;
            app.manage(EngineProcess(Mutex::new(child)));
            #[cfg(not(debug_assertions))]
            if let Err(error) = mark_update_launch_verified(app.handle()) {
                log::warn!("Unable to verify the desktop update journal: {error}");
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application");
    app.run(|app_handle, event| {
        if matches!(event, RunEvent::Exit) {
            stop_packaged_engine(app_handle);
        }
    });
}

#[cfg(not(debug_assertions))]
fn start_packaged_engine(
    app: &tauri::AppHandle,
) -> Result<Option<CommandChild>, Box<dyn std::error::Error>> {
    // Match the frontend's existing build-time address setting. Do not start
    // a second engine on 8765 when the compiled UI talks to a different port.
    let port = engine_port_from_url(option_env!("VITE_LORASUITE_ENGINE_URL").unwrap_or(""))?;
    if engine_is_ready(port) {
        log::info!("Using the existing LoraSuite engine at 127.0.0.1:{port}");
        return Ok(None);
    }
    let (mut events, child) = app
        .shell()
        .sidecar(ENGINE_SIDECAR)?
        .args(packaged_engine_args(std::process::id(), port))
        .spawn()?;
    let pid = child.pid();
    let sidecar_exited = Arc::new(AtomicBool::new(false));
    let event_sidecar_exited = Arc::clone(&sidecar_exited);
    tauri::async_runtime::spawn(async move {
        while let Some(event) = events.recv().await {
            match event {
                CommandEvent::Stdout(line) => {
                    log::info!("engine[{pid}]: {}", String::from_utf8_lossy(&line).trim())
                }
                CommandEvent::Stderr(line) => {
                    log::info!("engine[{pid}]: {}", String::from_utf8_lossy(&line).trim())
                }
                CommandEvent::Error(error) => log::error!("engine[{pid}]: {error}"),
                CommandEvent::Terminated(status) => {
                    event_sidecar_exited.store(true, Ordering::Release);
                    log::info!("engine[{pid}] terminated: {status:?}")
                }
                _ => {}
            }
        }
    });
    for _ in 0..120 {
        if sidecar_exited.load(Ordering::Acquire) {
            return Err(format!(
                "Packaged LoraSuite engine process {pid} exited before becoming ready"
            )
            .into());
        }
        if engine_is_ready(port) {
            log::info!("Started packaged LoraSuite engine with pid {pid}");
            return Ok(Some(child));
        }
        std::thread::sleep(Duration::from_millis(250));
    }
    let _ = child.kill();
    Err("Packaged LoraSuite engine did not become ready within 30 seconds".into())
}

#[cfg(any(not(debug_assertions), test))]
fn engine_port_from_url(value: &str) -> Result<u16, String> {
    if value.is_empty() {
        return Ok(8765);
    }
    let port = value.strip_prefix("http://127.0.0.1:")
        .or_else(|| value.strip_prefix("http://localhost:"))
        .ok_or("Desktop engine URL must be a loopback HTTP address with an explicit port")?;
    let port: u16 = port.strip_suffix('/').unwrap_or(port).parse()
        .map_err(|_| "Desktop engine URL must not contain credentials, paths or query parameters")?;
    if port < 1024 {
        return Err("Desktop engine port must be between 1024 and 65535".into());
    }
    Ok(port)
}

#[cfg(any(not(debug_assertions), test))]
fn packaged_engine_args(parent_process_id: u32, port: u16) -> Vec<String> {
    vec![
        "--host".to_string(),
        "127.0.0.1".to_string(),
        "--port".to_string(),
        port.to_string(),
        "--log-level".to_string(),
        "info".to_string(),
        "--parent-pid".to_string(),
        parent_process_id.to_string(),
    ]
}

fn stop_packaged_engine(app: &tauri::AppHandle) {
    let state = app.state::<EngineProcess>();
    let child = {
        match state.0.lock() {
            Ok(mut guard) => guard.take(),
            Err(error) => {
                log::warn!("Unable to lock packaged engine state: {error}");
                None
            }
        }
    };
    if let Some(child) = child {
        let pid = child.pid();
        if let Err(error) = child.kill() {
            log::warn!("Unable to stop packaged engine {pid}: {error}");
        } else {
            log::info!("Stopped packaged LoraSuite engine {pid}");
        }
    }
}

#[cfg(not(debug_assertions))]
fn engine_is_ready(port: u16) -> bool {
    let address = SocketAddr::from(([127, 0, 0, 1], port));
    let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_millis(250)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(500)));
    let _ = stream.set_write_timeout(Some(Duration::from_millis(500)));
    if stream
        .write_all(b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        .is_err()
    {
        return false;
    }
    let mut response = String::new();
    stream.read_to_string(&mut response).is_ok() && valid_engine_health_response(&response)
}

#[cfg(any(not(debug_assertions), test))]
fn valid_engine_health_response(response: &str) -> bool {
    response.starts_with("HTTP/1.1 200")
        && response.contains("\"status\":\"ok\"")
        && response.contains("\"service\":\"lorasuite-engine\"")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn credential_ids_are_explicitly_allowlisted() {
        assert!(CREDENTIAL_IDS.contains(&"runcomfy_api"));
        assert!(CREDENTIAL_IDS.contains(&"moonshot_api"));
        assert!(!CREDENTIAL_IDS.contains(&"arbitrary_keychain_entry"));
    }

    #[test]
    fn packaged_engine_health_requires_the_lorasuite_service_marker() {
        assert!(valid_engine_health_response(
      "HTTP/1.1 200 OK\r\ncontent-type: application/json\r\n\r\n{\"status\":\"ok\",\"service\":\"lorasuite-engine\"}"
    ));
        assert!(!valid_engine_health_response(
            "HTTP/1.1 200 OK\r\n\r\n{\"status\":\"ok\",\"service\":\"other\"}"
        ));
    }

    #[test]
    fn packaged_engine_receives_the_desktop_parent_pid() {
        let arguments = packaged_engine_args(42, 8765);
        assert_eq!(
            arguments,
            vec![
                "--host",
                "127.0.0.1",
                "--port",
                "8765",
                "--log-level",
                "info",
                "--parent-pid",
                "42",
            ]
        );
    }

    #[test]
    fn packaged_engine_matches_the_frontend_local_address() {
        assert_eq!(engine_port_from_url("").unwrap(), 8765);
        assert_eq!(engine_port_from_url("http://127.0.0.1:8767").unwrap(), 8767);
        assert_eq!(engine_port_from_url("http://localhost:8767/").unwrap(), 8767);
        assert_eq!(packaged_engine_args(42, 8767)[3], "8767");
        for value in ["https://example.org:8767", "http://127.0.0.1.evil:8767", "http://127.0.0.1:80", "http://127.0.0.1:8767/path", "http://user@127.0.0.1:8767", "http://127.0.0.1:8767?token=x"] {
            assert!(engine_port_from_url(value).is_err(), "{value}");
        }
    }

    #[test]
    fn update_channels_have_separate_signed_manifests() {
        assert!(UpdateChannel::Stable.endpoint().ends_with("/latest.json"));
        assert!(UpdateChannel::Rollback
            .endpoint()
            .ends_with("/rollback.json"));
        assert_ne!(
            UpdateChannel::Stable.endpoint(),
            UpdateChannel::Rollback.endpoint()
        );
    }

    #[test]
    fn base_config_always_supplies_an_updater_object() {
        let config: serde_json::Value =
            serde_json::from_str(include_str!("../tauri.conf.json")).unwrap();
        let updater = config
            .pointer("/plugins/updater")
            .expect("the updater plugin requires an object even for local builds");

        assert!(updater.is_object());
        assert_eq!(
            updater.get("pubkey").and_then(|value| value.as_str()),
            Some("")
        );
    }

    #[test]
    fn update_journal_round_trips() {
        let journal = UpdateJournal {
            channel: UpdateChannel::Rollback,
            from_version: "2.0.0".to_string(),
            to_version: "1.9.0".to_string(),
            state: "installed_pending_restart".to_string(),
            message: "Ready".to_string(),
            updated_at_unix: 42,
        };
        let encoded = serde_json::to_string(&journal).expect("journal should serialize");
        let decoded: UpdateJournal = serde_json::from_str(&encoded).expect("journal should parse");
        assert!(matches!(decoded.channel, UpdateChannel::Rollback));
        assert_eq!(decoded.from_version, "2.0.0");
        assert_eq!(decoded.to_version, "1.9.0");
    }

    #[test]
    fn rollback_only_accepts_an_older_signed_release() {
        let current = semver::Version::parse("2.0.0").expect("current version should parse");
        assert!(rollback_release_is_older(
            &current,
            &semver::Version::parse("1.9.0").expect("older version should parse")
        ));
        assert!(!rollback_release_is_older(
            &current,
            &semver::Version::parse("2.0.0").expect("same version should parse")
        ));
        assert!(!rollback_release_is_older(
            &current,
            &semver::Version::parse("2.1.0").expect("newer version should parse")
        ));
    }

    #[test]
    fn published_manifest_shape_is_accepted_by_tauri() {
        let manifest = serde_json::json!({
            "version": "1.2.3",
            "notes": "Qualified release",
            "pub_date": "2026-07-16T20:00:00Z",
            "platforms": {
                "darwin-aarch64": {
                    "signature": "trusted-signature",
                    "url": "https://example.test/LoraSuite.app.tar.gz"
                }
            }
        });
        let release: tauri_plugin_updater::RemoteRelease =
            serde_json::from_value(manifest).expect("Tauri should parse the static manifest");
        assert_eq!(release.version.to_string(), "1.2.3");
        assert_eq!(
            release
                .download_url("darwin-aarch64")
                .expect("platform should have a URL")
                .as_str(),
            "https://example.test/LoraSuite.app.tar.gz"
        );
    }
}
