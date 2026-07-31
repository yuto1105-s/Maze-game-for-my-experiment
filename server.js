const express = require("express");
const http = require("http");
const { Server } = require("socket.io");
const sqlite3 = require("sqlite3").verbose();

const app = express();
const server = http.createServer(app);
const io = new Server(server);

app.use(express.static("public"));

// ========================================
// SQLite データベース初期化
// ========================================

const db = new sqlite3.Database("player_logs.db");

db.serialize(() => {
    // 1. 移動・視点ログ
    db.run(`
    CREATE TABLE IF NOT EXISTS player_logs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        player_id TEXT,
        color TEXT,
        time TEXT,
        x REAL, y REAL, z REAL,
        rx REAL, ry REAL, rz REAL
    )
    `);

    // 2. 注視ログ
    db.run(`
    CREATE TABLE IF NOT EXISTS gaze_logs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        player_id TEXT,
        object_name TEXT,
        start_time TEXT,
        end_time TEXT,
        duration_ms INTEGER,
        x REAL, y REAL, z REAL
    )
    `);

    // 3. チェックポイント・ゴールイベントログ
    db.run(`
    CREATE TABLE IF NOT EXISTS event_logs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        player_id TEXT,
        event_type TEXT,
        target_name TEXT,
        time TEXT
    )
    `);
});

// ========================================
// 移動ログのバッファリング一括挿入
// ========================================
let logBuffer = [];

function flushLogs() {
    if (logBuffer.length === 0) return;

    const currentLogs = [...logBuffer];
    logBuffer = [];

    db.serialize(() => {
        db.run("BEGIN TRANSACTION");
        const stmt = db.prepare(`
            INSERT INTO player_logs (player_id, color, time, x, y, z, rx, ry, rz)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        `);

        for (const log of currentLogs) {
            stmt.run([
                log.player_id, log.color, log.time,
                log.x, log.y, log.z,
                log.rx, log.ry, log.rz
            ]);
        }

        stmt.finalize();
        db.run("COMMIT", (err) => {
            if (err) console.error("ログ保存コミットエラー:", err);
        });
    });
}

setInterval(flushLogs, 2000);

// ========================================
// Socket.IO 通信制御
// ========================================

const players = {};

function createRandomColor() {
    return "#" + Math.floor(Math.random() * 16777215).toString(16).padStart(6, "0");
}

io.on("connection", (socket) => {
    console.log("接続 :", socket.id);

    players[socket.id] = {
        id: socket.id,
        color: createRandomColor(),
        position: { x: 0, y: 1.6, z: 0 },
        rotation: { x: 0, y: 0, z: 0 }
    };

    socket.emit("自分の情報", players[socket.id]);
    socket.emit("プレイヤー一覧", Object.values(players));
    socket.broadcast.emit("他者が入室した", players[socket.id]);

    // 移動ログ受信
    socket.on("自分が移動した", (data) => {
        const player = players[socket.id];
        if (!player || !data.position || !data.rotation) return;

        player.position = data.position;
        player.rotation = data.rotation;

        logBuffer.push({
            player_id: player.id,
            color: player.color,
            time: new Date().toISOString(),
            x: player.position.x,
            y: player.position.y,
            z: player.position.z,
            rx: player.rotation.x,
            ry: player.rotation.y,
            rz: player.rotation.z
        });

        socket.broadcast.emit("他者が移動した", player);
    });

    // 注視ログ受信
    socket.on("見た", (data) => {
        const player = players[socket.id];
        if (!player) return;

        db.run(
            `INSERT INTO gaze_logs (player_id, object_name, start_time, end_time, duration_ms, x, y, z)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
            [
                player.id, data.object_name, data.start_time,
                data.end_time, data.duration_ms,
                player.position.x, player.position.y, player.position.z
            ],
            (err) => { if (err) console.error("注視ログエラー:", err); }
        );
    });

    // チェックポイント通過ログ受信
    socket.on("チェックポイント通過", (data) => {
        const player = players[socket.id];
        if (!player) return;

        db.run(
            `INSERT INTO event_logs (player_id, event_type, target_name, time) VALUES (?, ?, ?, ?)`,
            [player.id, "CHECKPOINT", data.checkpoint_name, data.time],
            (err) => { if (err) console.error("CPログエラー:", err); }
        );
    });

    // ゴール到達ログ受信
    socket.on("ゴール到達", (data) => {
        const player = players[socket.id];
        if (!player) return;

        db.run(
            `INSERT INTO event_logs (player_id, event_type, target_name, time) VALUES (?, ?, ?, ?)`,
            [player.id, "GOAL", data.goal_name, data.time],
            (err) => { if (err) console.error("ゴールログエラー:", err); }
        );
    });

    // 切断処理
    socket.on("disconnect", () => {
        console.log("切断 :", socket.id);
        delete players[socket.id];
        io.emit("他者がいなくなった", socket.id);
    });
});

process.on("SIGINT", () => {
    flushLogs();
    db.close(() => {
        console.log("DB接続を閉じて終了します");
        process.exit(0);
    });
});

const PORT = 3000;
server.listen(PORT, () => {
    console.log(`Server running at http://localhost:${PORT}`);
});