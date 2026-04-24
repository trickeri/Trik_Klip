pub mod server;

use tauri::Manager;

/// Scan a small range for a free TCP port on loopback. Lets multiple
/// instances of the app run concurrently (e.g. the installed launcher
/// build alongside a `tauri dev` session) instead of failing on bind.
fn find_free_port(start: u16, end: u16) -> Option<u16> {
    for port in start..=end {
        if std::net::TcpListener::bind(("127.0.0.1", port)).is_ok() {
            return Some(port);
        }
    }
    None
}

/// Tauri-managed wrapper so the frontend can invoke `get_api_port` and
/// learn which port this instance's backend bound to.
#[derive(Clone, Copy)]
struct ApiPort(u16);

#[tauri::command]
fn get_api_port(port: tauri::State<'_, ApiPort>) -> u16 {
    port.0
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // Initialize tracing BEFORE Tauri (which sets its own logger).
    // The guard must live for the entire process — dropping it loses buffered logs.
    let _log_guard = server::init_tracing();

    // Pick a free port up front. Falls back to 31416 if the whole range is
    // busy (will fail to bind and surface a clear error from the server).
    let port = find_free_port(31416, 31430).unwrap_or(31416);
    tracing::info!("Selected API port: {}", port);
    std::env::set_var("API_PORT", port.to_string());

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(ApiPort(port))
        .invoke_handler(tauri::generate_handler![get_api_port])
        .setup(|app| {
            // Spawn the embedded backend server
            tauri::async_runtime::spawn(async {
                if let Err(e) = server::start_server().await {
                    tracing::error!("Backend server error: {}", e);
                    eprintln!("Backend server error: {}", e);
                }
            });

            // Set window size to 860x1000 and center
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_size(tauri::Size::Logical(
                    tauri::LogicalSize { width: 860.0, height: 1000.0 },
                ));
                let _ = window.center();
                // Open devtools in debug builds
                #[cfg(debug_assertions)]
                window.open_devtools();
            }

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
