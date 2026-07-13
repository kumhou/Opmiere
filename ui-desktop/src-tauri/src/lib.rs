// Opmiere desktop host (Tauri). UI is WebView; craft logic stays in Python core.
// No agent chat panel (ADR_UI_AND_PREVIEW).

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .run(tauri::generate_context!())
        .expect("error while running Opmiere desktop");
}
