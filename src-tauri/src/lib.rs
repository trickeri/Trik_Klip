pub mod server;

use tauri::Manager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // Initialize tracing BEFORE Tauri (which sets its own logger).
    // The guard must live for the entire process — dropping it loses buffered logs.
    let _log_guard = server::init_tracing();

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
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
