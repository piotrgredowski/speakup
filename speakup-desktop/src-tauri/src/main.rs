// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use chrono::{DateTime, Utc};
use rusqlite::{Connection, Row};
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use std::sync::Mutex;
use tauri::State;

#[derive(Debug, Serialize, Deserialize, Clone)]
struct NotificationEntry {
    id: i64,
    timestamp: f64,
    agent: String,
    event: String,
    message: String,
    summary: String,
    audio_path: Option<String>,
    status: String,
    backend: String,
    session_name: Option<String>,
    metadata: Option<String>,
}

#[derive(Debug, Serialize, Deserialize)]
struct Stats {
    total: i64,
    by_agent: std::collections::HashMap<String, i64>,
    by_event: std::collections::HashMap<String, i64>,
    oldest_timestamp: Option<f64>,
    newest_timestamp: Option<f64>,
}

struct AppState {
    db_path: PathBuf,
    conn: Mutex<Option<Connection>>,
}

fn get_db_path() -> PathBuf {
    std::env::temp_dir()
        .join("speakup")
        .join("history.db")
}

fn get_connection(db_path: &PathBuf) -> Result<Connection, String> {
    Connection::open(db_path).map_err(|e| format!("Failed to connect to database: {}", e))
}

fn row_to_entry(row: &Row) -> Result<NotificationEntry, rusqlite::Error> {
    Ok(NotificationEntry {
        id: row.get(0)?,
        timestamp: row.get(1)?,
        agent: row.get(2)?,
        event: row.get(3)?,
        message: row.get(4)?,
        summary: row.get(5)?,
        audio_path: row.get(6)?,
        status: row.get(7)?,
        backend: row.get(8)?,
        session_name: row.get(9)?,
        metadata: row.get(10)?,
    })
}

#[tauri::command]
fn get_notifications(
    state: State<AppState>,
    limit: Option<usize>,
    offset: Option<usize>,
    agent: Option<String>,
    event: Option<String>,
    search: Option<String>,
) -> Result<Vec<NotificationEntry>, String> {
    let limit = limit.unwrap_or(100);
    let offset = offset.unwrap_or(0);

    let mut conn = state.conn.lock().unwrap();
    if conn.is_none() {
        *conn = Some(get_connection(&state.db_path)?);
    }
    let conn = conn.as_ref().unwrap();

    let mut query = String::from(
        "SELECT id, timestamp, agent, event, message, summary, audio_path, status, backend, session_name, metadata \
         FROM notifications WHERE 1=1"
    );
    let mut params: Vec<Box<dyn rusqlite::ToSql>> = Vec::new();

    if let Some(ref a) = agent {
        query.push_str(" AND agent = ?");
        params.push(Box::new(a.clone()));
    }

    if let Some(ref e) = event {
        query.push_str(" AND event = ?");
        params.push(Box::new(e.clone()));
    }

    if let Some(ref s) = search {
        query.push_str(" AND (message LIKE ? OR summary LIKE ?)");
        let search_pattern = format!("%{}%", s);
        params.push(Box::new(search_pattern.clone()));
        params.push(Box::new(search_pattern));
    }

    query.push_str(" ORDER BY timestamp DESC LIMIT ? OFFSET ?");
    params.push(Box::new(limit as i64));
    params.push(Box::new(offset as i64));

    let params_refs: Vec<&dyn rusqlite::ToSql> = params.iter().map(|p| p.as_ref()).collect();

    let mut stmt = conn
        .prepare(&query)
        .map_err(|e| format!("Failed to prepare query: {}", e))?;

    let entries = stmt
        .query_map(params_refs.as_slice(), row_to_entry)
        .map_err(|e| format!("Failed to execute query: {}", e))?
        .collect::<Result<Vec<_>, _>>()
        .map_err(|e| format!("Failed to fetch entries: {}", e))?;

    Ok(entries)
}

#[tauri::command]
fn get_notification_by_id(state: State<AppState>, id: i64) -> Result<Option<NotificationEntry>, String> {
    let mut conn = state.conn.lock().unwrap();
    if conn.is_none() {
        *conn = Some(get_connection(&state.db_path)?);
    }
    let conn = conn.as_ref().unwrap();

    let mut stmt = conn
        .prepare(
            "SELECT id, timestamp, agent, event, message, summary, audio_path, status, backend, session_name, metadata \
             FROM notifications WHERE id = ?"
        )
        .map_err(|e| format!("Failed to prepare query: {}", e))?;

    let mut entries = stmt
        .query_map([id], row_to_entry)
        .map_err(|e| format!("Failed to execute query: {}", e))?;

    match entries.next() {
        Some(entry) => Ok(Some(entry.map_err(|e| format!("Failed to fetch entry: {}", e))?)),
        None => Ok(None),
    }
}

#[tauri::command]
fn get_stats(state: State<AppState>) -> Result<Stats, String> {
    let mut conn = state.conn.lock().unwrap();
    if conn.is_none() {
        *conn = Some(get_connection(&state.db_path)?);
    }
    let conn = conn.as_ref().unwrap();

    let total: i64 = conn
        .query_row("SELECT COUNT(*) FROM notifications", [], |row| row.get(0))
        .unwrap_or(0);

    let mut by_agent = std::collections::HashMap::new();
    let mut agent_stmt = conn
        .prepare("SELECT agent, COUNT(*) as count FROM notifications GROUP BY agent ORDER BY count DESC")
        .map_err(|e| format!("Failed to query by agent: {}", e))?;
    let agent_rows = agent_stmt
        .query_map([], |row| Ok((row.get::<_, String>(0)?, row.get::<_, i64>(1)?)))
        .map_err(|e| format!("Failed to query by agent: {}", e))?;

    for row in agent_rows {
        let (agent, count) = row.map_err(|e| format!("Failed to fetch agent row: {}", e))?;
        by_agent.insert(agent, count);
    }

    let mut by_event = std::collections::HashMap::new();
    let mut event_stmt = conn
        .prepare("SELECT event, COUNT(*) as count FROM notifications GROUP BY event ORDER BY count DESC")
        .map_err(|e| format!("Failed to query by event: {}", e))?;
    let event_rows = event_stmt
        .query_map([], |row| Ok((row.get::<_, String>(0)?, row.get::<_, i64>(1)?)))
        .map_err(|e| format!("Failed to query by event: {}", e))?;

    for row in event_rows {
        let (event, count) = row.map_err(|e| format!("Failed to fetch event row: {}", e))?;
        by_event.insert(event, count);
    }

    let oldest_timestamp: Option<f64> = conn
        .query_row("SELECT MIN(timestamp) FROM notifications", [], |row| row.get(0))
        .ok();

    let newest_timestamp: Option<f64> = conn
        .query_row("SELECT MAX(timestamp) FROM notifications", [], |row| row.get(0))
        .ok();

    Ok(Stats {
        total,
        by_agent,
        by_event,
        oldest_timestamp,
        newest_timestamp,
    })
}

#[tauri::command]
fn format_timestamp(timestamp: f64) -> String {
    let dt = DateTime::from_timestamp(timestamp as i64, 0)
        .unwrap_or_else(|| Utc::now());
    dt.format("%Y-%m-%d %H:%M:%S").to_string()
}

#[tauri::command]
fn get_audio_path(state: State<AppState>, notification_id: i64) -> Result<Option<String>, String> {
    let mut conn = state.conn.lock().unwrap();
    if conn.is_none() {
        *conn = Some(get_connection(&state.db_path)?);
    }
    let conn = conn.as_ref().unwrap();

    let audio_path: Option<String> = conn
        .query_row(
            "SELECT audio_path FROM notifications WHERE id = ?",
            [notification_id],
            |row| row.get(0),
        )
        .map_err(|e| format!("Failed to query audio path: {}", e))?;

    Ok(audio_path)
}

fn main() {
    let db_path = get_db_path();
    
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(AppState {
            db_path,
            conn: Mutex::new(None),
        })
        .invoke_handler(tauri::generate_handler![
            get_notifications,
            get_notification_by_id,
            get_stats,
            format_timestamp,
            get_audio_path,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
