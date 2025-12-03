# 🖥️ System Monitor

Sistema di monitoraggio distribuito per server Linux. Raccoglie metriche di sistema ogni 15 minuti e invia un report giornaliero via [ntfy.sh](https://ntfy.sh).

## ✨ Features

- **Architettura Client/Server**: Un container può funzionare sia da server che da client
- **Metriche raccolte**:
  - 🔥 CPU: utilizzo %, frequenza, temperatura (max con timestamp)
  - 💾 RAM: totale, usata, disponibile, percentuale
  - 💿 Disco: tutte le partizioni montate (totale, usato, libero, %)
  - 🌐 Network: bytes/pacchetti inviati e ricevuti
  - ⚡ Load average: 1, 5, 15 minuti
  - 📊 Uptime e numero processi
- **Alert in tempo reale**: Notifica immediata quando una soglia viene superata
- **Report giornaliero**: Riepilogo alle 07:00 UTC con statistiche aggregate
- **Persistenza SQLite**: Storico dei dati con retention configurabile

## 🏗️ Architettura

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Client 1      │     │   Client 2      │     │   Client N      │
│  (container)    │     │  (container)    │     │  (container)    │
└────────┬────────┘     └────────┬────────┘     └────────┬────────┘
         │                       │                       │
         │  HTTP POST /metrics   │                       │
         │  ogni 15 min          │                       │
         ▼                       ▼                       ▼
┌────────────────────────────────────────────────────────────────┐
│                         SERVER                                  │
│                      (container)                                │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │  REST API   │  │   SQLite    │  │  Scheduler              │ │
│  │  FastAPI    │  │   Database  │  │  Report giornaliero     │ │
│  └─────────────┘  └─────────────┘  └───────────┬─────────────┘ │
└────────────────────────────────────────────────┬───────────────┘
                                                 │
                                                 │ ntfy.sh
                                                 ▼
                                        📱 Notifiche Push
```

## 🚀 Quick Start

### 1. Configura il Server

Sul server centrale:

```bash
# Clona o copia la cartella system-monitor
cd system-monitor

# Crea il file di configurazione
cp config.yaml.example config.yaml

# Modifica config.yaml
nano config.yaml
```

Configura come **server**:

```yaml
mode: server

server:
  host: "0.0.0.0"
  port: 8080

ntfy:
  enabled: true
  topic: "mio-topic-segreto-12345"  # Usa un topic unico!
```

Avvia:

```bash
docker compose --profile server up -d
```

### 2. Configura i Client

Su ogni server da monitorare:

```bash
cd system-monitor

cp config.yaml.example config.yaml
nano config.yaml
```

Configura come **client**:

```yaml
mode: client

client:
  server_url: "http://192.168.1.100:8080"  # IP del server
  client_id: "webserver-prod"               # Nome identificativo
  collect_interval_minutes: 15
```

Avvia:

```bash
docker compose --profile client up -d
```

## ⚙️ Configurazione

### File di Configurazione

Vedi `config.yaml.example` per tutti i parametri disponibili.

### Variabili d'Ambiente

Le variabili d'ambiente hanno priorità sul file di configurazione:

| Variabile | Descrizione | Default |
|-----------|-------------|---------|
| `SYSMON_MODE` | `server` o `client` | `client` |
| `SYSMON_SERVER_HOST` | Bind address server | `0.0.0.0` |
| `SYSMON_SERVER_PORT` | Porta server | `8080` |
| `SYSMON_SERVER_URL` | URL server (client) | `http://localhost:8080` |
| `SYSMON_CLIENT_ID` | ID del client | hostname |
| `SYSMON_COLLECT_INTERVAL` | Intervallo raccolta (minuti) | `15` |
| `SYSMON_NTFY_ENABLED` | Abilita notifiche | `true` |
| `SYSMON_NTFY_TOPIC` | Topic ntfy.sh | `system-monitor` |
| `SYSMON_ALERT_CPU` | Soglia CPU % | `90` |
| `SYSMON_ALERT_RAM` | Soglia RAM % | `90` |
| `SYSMON_ALERT_DISK` | Soglia Disco % | `85` |
| `SYSMON_ALERT_TEMP` | Soglia Temperatura °C | `80` |
| `SYSMON_DAILY_HOUR` | Ora report UTC | `7` |
| `SYSMON_DB_PATH` | Path database | `/data/system_monitor.db` |
| `SYSMON_DB_RETENTION` | Retention giorni | `30` |

### Esempio con solo ENV

```bash
docker run -d \
  --name system-monitor-client \
  --pid host \
  -v /sys:/host/sys:ro \
  -e SYSMON_MODE=client \
  -e SYSMON_SERVER_URL=http://192.168.1.100:8080 \
  -e SYSMON_CLIENT_ID=my-server \
  system-monitor
```

## 📡 API Endpoints

Il server espone i seguenti endpoint:

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/metrics` | Riceve metriche dai client |
| `GET` | `/clients` | Lista client registrati |
| `GET` | `/clients/{id}/summary?date=YYYY-MM-DD` | Summary giornaliero |
| `GET` | `/alerts` | Lista alert recenti |
| `POST` | `/test/daily-report` | Trigger manuale report |
| `POST` | `/test/collect` | Raccogli metriche locali |

## 🔔 Notifiche ntfy.sh

### Setup

1. Vai su [ntfy.sh](https://ntfy.sh)
2. Scegli un topic unico (es: `my-system-abc123`)
3. Sottoscrivi il topic dall'app mobile o web
4. Configura lo stesso topic in `config.yaml`

### Tipi di Notifiche

- **Alert immediati** (priorità alta): Quando una soglia viene superata
- **Report giornaliero** (priorità normale): Ogni giorno alle 07:00 UTC

### Self-hosted ntfy

Puoi usare il tuo server ntfy:

```yaml
ntfy:
  server_url: "https://ntfy.mydomain.com"
  topic: "system-monitor"
```

## 🐳 Docker

### Build manuale

```bash
docker build -t system-monitor .
```

### Run Server

```bash
docker run -d \
  --name system-monitor-server \
  --pid host \
  -p 8080:8080 \
  -v $(pwd)/config.yaml:/config/config.yaml:ro \
  -v system-monitor-data:/data \
  -v /sys:/host/sys:ro \
  system-monitor
```

### Run Client

```bash
docker run -d \
  --name system-monitor-client \
  --pid host \
  -v $(pwd)/config.yaml:/config/config.yaml:ro \
  -v /sys:/host/sys:ro \
  system-monitor
```

## 📊 Esempio Report Giornaliero

```
📊 Report Giornaliero - 2024-01-15
━━━━━━━━━━━━━━━━━━━━━━━━━━
🖥️ Sistemi monitorati: 3

┌─ webserver-prod (webserver-prod)
│ CPU: avg 23.4% | max 87.2%
│ RAM: avg 62.1% | max 78.5%
│ Temp: avg 52°C | max 68°C
│ Disco: max 73.2% (/)
│ Network: ↑2.34GB ↓15.67GB
│ Load max: 3.21 | Uptime: 720.5h
└─────────────────────────

┌─ db-server (database)
│ CPU: avg 45.2% | max 92.1%
│ RAM: avg 78.3% | max 89.2%
│ Temp: avg 58°C | max 72°C
│ Disco: max 82.1% (/data)
│ Network: ↑0.12GB ↓0.89GB
│ Load max: 5.67 | Uptime: 1440.2h
│ ⚠️ Alert: 2
└─────────────────────────
```

## 🔧 Troubleshooting

### Temperatura non disponibile

La lettura della temperatura richiede `lm-sensors`. Nel container è già installato, ma l'host deve avere i sensori configurati:

```bash
# Sull'host
sudo apt install lm-sensors
sudo sensors-detect
```

### Client non si connette al server

1. Verifica che il server sia raggiungibile:
   ```bash
   curl http://SERVER_IP:8080/health
   ```

2. Controlla i log del client:
   ```bash
   docker logs system-monitor-client
   ```

### Metriche non accurate

Assicurati di usare `--pid host` per leggere le metriche dell'host e non del container.

## 📝 License

MIT

## 🤝 Contributing

Pull request benvenute! Per modifiche importanti, apri prima una issue.

