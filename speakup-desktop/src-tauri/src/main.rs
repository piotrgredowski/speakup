// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    App, Runtime,
};

#[derive(Debug, Clone, Serialize, Deserialize)]
struct PlaybackState {
    session_name: Option<String>,
    current_text: Option<String>,
    history: Vec<String>,
    state: String,
}

fn get_state_file() -> PathBuf {
    dirs::cache_dir()
        .unwrap_or_else(|| PathBuf::from("/tmp"))
        .join("speakup")
        .join("now_playing.json")
}

fn read_state(path: &PathBuf) -> Option<PlaybackState> {
    if !path.exists() {
        return None;
    }
    let content = fs::read_to_string(path).ok()?;
    serde_json::from_str(&content).ok()
}

fn create_default_state() -> PlaybackState {
    PlaybackState {
        session_name: None,
        current_text: None,
        history: Vec::new(),
        state: "idle".to_string(),
    }
}

fn main() {
    let state_file = get_state_file();
    let initial_state = read_state(&state_file).unwrap_or_else(create_default_state);

    let current_state = Arc::new(Mutex::new(initial_state));
    let state_file_clone = state_file.clone();
    let current_state_clone = Arc::clone(&current_state);

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(move |app| {
            setup_tray(app, current_state_clone, state_file_clone)?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

fn setup_tray<R: Runtime>(
    app: &App<R>,
    current_state: Arc<Mutex<PlaybackState>>,
    state_file: PathBuf,
) -> Result<(), Box<dyn std::error::Error>> {
    // Create menu items
    let session_item = MenuItem::with_id(app, "session", "No Session", true, None::<&str>)?;
    let current_text_item = MenuItem::with_id(app, "current", "Not playing", true, None::<&str>)?;
    let history_0 = MenuItem::with_id(app, "history_0", "", true, None::<&str>)?;
    let history_1 = MenuItem::with_id(app, "history_1", "", true, None::<&str>)?;
    let history_2 = MenuItem::with_id(app, "history_2", "", true, None::<&str>)?;
    let quit_item = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;

    // Build menu
    let menu = Menu::with_items(app, &[
        &session_item,
        &current_text_item,
        &history_0,
        &history_1,
        &history_2,
        &quit_item,
    ])?;

    // Create tray
    let _tray = TrayIconBuilder::with_id("main")
        .menu(&menu)
        .on_menu_event(|app, event| {
            if event.id() == "quit" {
                app.exit(0);
            }
        })
        .build(app)?;

    // Clone handles for the background thread
    let session_handle = session_item.clone();
    let current_handle = current_text_item.clone();
    let h0 = history_0.clone();
    let h1 = history_1.clone();
    let h2 = history_2.clone();

    // Spawn background thread to poll state file
    std::thread::spawn(move || {
        loop {
            if let Some(new_state) = read_state(&state_file) {
                let mut state = current_state.lock().unwrap();
                
                let changed = state.session_name != new_state.session_name
                    || state.current_text != new_state.current_text
                    || state.history != new_state.history
                    || state.state != new_state.state;

                if changed {
                    *state = new_state;
                    let snapshot = state.clone();

                    // Update menu items
                    if let Some(name) = &snapshot.session_name {
                        let _ = session_handle.set_text(format!("Session: {}", name));
                    } else {
                        let _ = session_handle.set_text("No Session");
                    }

                    if let Some(text) = &snapshot.current_text {
                        let display = if text.len() > 100 {
                            format!("Now: {}...", &text[..97])
                        } else {
                            format!("Now: {}", text)
                        };
                        let _ = current_handle.set_text(display);
                    } else {
                        let _ = current_handle.set_text("Not playing");
                    }

                    // Update history
                    let history_items = [&h0, &h1, &h2];
                    for (i, item) in history_items.iter().enumerate() {
                        if let Some(text) = snapshot.history.get(i) {
                            let display = if text.len() > 80 {
                                format!("{}...", &text[..77])
                            } else {
                                text.clone()
                            };
                            let _ = item.set_text(display);
                        } else {
                            let _ = item.set_text("");
                        }
                    }
                }
            }

            std::thread::sleep(Duration::from_millis(500));
        }
    });

    Ok(())
}
