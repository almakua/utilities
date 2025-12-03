# 🛠️ Utilities

Raccolta di strumenti e utility per la gestione di infrastrutture.

---

## 📦 Progetti

### [System Monitor](./system-monitor/)

Sistema di monitoraggio distribuito per server Linux con notifiche push.

---

# 🖥️ System Monitor

Sistema di monitoraggio distribuito per server Linux. Raccoglie metriche di sistema ogni 15 minuti e invia un report giornaliero via [ntfy.sh](https://ntfy.sh).

## ✨ Features

- **Architettura Client/Server**: Un singolo container Docker può funzionare sia da server che da client
- **REST API**: Comunicazione tramite HTTP REST (FastAPI)
- **Database SQLite**: Persistenza locale con retention configurabile
- **Notifiche Push**: Via ntfy.sh (self-hosted o pubblico)
- **Alert in tempo reale**: Notifica immediata al superamento delle soglie
- **Report giornaliero**: Riepilogo completo alle 07:00 UTC
- **Report settimanale pacchetti**: Lista pacchetti da aggiornare su tutti i sistemi

## 📊 Metriche Raccolte

| Categoria | Metriche | Dettagli |
|-----------|----------|----------|
| 🔥 **CPU** | Utilizzo %, frequenza, temperatura | Temperatura max del package con timestamp |
| 💾 **RAM** | Totale, usata, disponibile | Percentuale di utilizzo |
| 🔄 **Swap** | Totale, usato | Percentuale di utilizzo |
| 💿 **Disco** | Tutte le partizioni | Totale, usato, libero, % per ogni mount point |
| 🌐 **Network** | I/O bytes e pacchetti | Inviati e ricevuti |
| ⚡ **Load Average** | 1, 5, 15 minuti | Con soglia dinamica basata su CPU count |
| 📊 **Sistema** | Uptime, processi | Secondi di uptime, numero processi attivi |
| 📦 **Pacchetti** | Aggiornamenti disponibili | Supporta apt, dnf, yum, pacman, zypper |

## 🏗️ Architettura

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Client 1      │     │   Client 2      │     │   Client N      │
│  (container)    │     │  (container)    │     │  (container)    │
│                 │     │                 │     │                 │
│  ┌───────────┐  │     │  ┌───────────┐  │     │  ┌───────────┐  │
│  │ Collector │  │     │  │ Collector │  │     │  │ Collector │  │
│  │  psutil   │  │     │  │  psutil   │  │     │  │  psutil   │  │
│  └─────┬─────┘  │     │  └─────┬─────┘  │     │  └─────┬─────┘  │
└────────┼────────┘     └────────┼────────┘     └────────┼────────┘
         │                       │                       │
         │    HTTP POST /metrics (ogni 15 min)           │
         │                       │                       │
         ▼                       ▼                       ▼
┌────────────────────────────────────────────────────────────────────┐
│                            SERVER                                   │
│                         (container)                                 │
│                                                                     │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────┐ │
│  │    REST API     │  │     SQLite      │  │     Scheduler       │ │
│  │    FastAPI      │  │    Database     │  │   APScheduler       │ │
│  │                 │  │                 │  │                     │ │
│  │  POST /metrics  │  │  - metrics      │  │  - Daily report     │ │
│  │  POST /packages │  │  - alerts       │  │    (07:00 UTC)      │ │
│  │  GET /clients   │  │  - clients      │  │  - Weekly packages  │ │
│  │  GET /alerts    │  │  - packages     │  │  - Data cleanup     │ │
│  └────────┬────────┘  └─────────────────┘  └──────────┬──────────┘ │
│           │                                           │             │
│           │         Alert immediati                   │             │
│           └───────────────────┬───────────────────────┘             │
└───────────────────────────────┼─────────────────────────────────────┘
                                │
                                │  HTTPS POST
                                │  ntfy.sh
                                ▼
                    ┌───────────────────────┐
                    │      ntfy.sh          │
                    │  (pubblico o self)    │
                    └───────────┬───────────┘
                                │
                    ┌───────────┼───────────┐
                    ▼           ▼           ▼
                   📱          💻          🖥️
                 Mobile       Web        Desktop
```

## 🚀 Quick Start

### Prerequisiti

- Docker e Docker Compose
- Accesso di rete tra client e server
- (Opzionale) `lm-sensors` sull'host per la temperatura CPU

### 1️⃣ Configurazione Server

Sul server centrale che raccoglierà i dati:

```bash
# Entra nella cartella del progetto
cd system-monitor

# Crea il file di configurazione
cp config.yaml.example config.yaml
```

Modifica `config.yaml` per il server:

```yaml
# Modalità server
mode: server

# Configurazione server
server:
  host: "0.0.0.0"
  port: 8080

# IMPORTANTE: configura un topic ntfy unico!
ntfy:
  enabled: true
  server_url: "https://ntfy.sh"
  topic: "mio-sistema-monitor-xyz789"  # Usa qualcosa di unico!
  priority: "default"

# Soglie per gli alert (opzionale)
alerts:
  cpu_percent: 90.0
  ram_percent: 90.0
  disk_percent: 85.0
  temperature_celsius: 80.0

# Report giornaliero e settimanale
notifications:
  daily_report_hour_utc: 7
  daily_report_minute_utc: 0
  send_immediate_alerts: true
  weekly_packages_enabled: true
  weekly_packages_day: "monday"
  weekly_packages_hour_utc: 8

# Database
database:
  path: "/data/system_monitor.db"
  retention_days: 30
```

Avvia il server:

```bash
docker compose --profile server up -d
```

Verifica che funzioni:

```bash
curl http://localhost:8080/health
# {"status":"healthy","timestamp":"2024-01-15T10:30:00.000000"}
```

### 2️⃣ Configurazione Client

Su ogni server Linux da monitorare:

```bash
cd system-monitor
cp config.yaml.example config.yaml
```

Modifica `config.yaml` per il client:

```yaml
# Modalità client
mode: client

# Configurazione client
client:
  # URL del server (cambia con l'IP reale)
  server_url: "http://192.168.1.100:8080"
  
  # ID univoco per questo client (opzionale)
  # Se null, usa l'hostname del sistema
  client_id: "webserver-prod"
  
  # Intervallo di raccolta in minuti
  collect_interval_minutes: 15
```

Avvia il client:

```bash
docker compose --profile client up -d
```

Verifica i log:

```bash
docker logs -f system-monitor-client
```

### 3️⃣ Sottoscrivi le Notifiche

1. Installa l'app ntfy sul telefono ([Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy) / [iOS](https://apps.apple.com/app/ntfy/id1625396347))
2. Aggiungi una sottoscrizione al topic configurato (es: `mio-sistema-monitor-xyz789`)
3. Riceverai le notifiche!

Oppure via web: `https://ntfy.sh/mio-sistema-monitor-xyz789`

## ⚙️ Configurazione Completa

### File config.yaml

```yaml
# ================================================
# System Monitor - Configuration File
# ================================================

# Modalità: "server" o "client"
mode: client

# ------------------------------------------------
# Server Configuration
# ------------------------------------------------
server:
  host: "0.0.0.0"      # Bind address
  port: 8080           # Porta di ascolto

# ------------------------------------------------
# Client Configuration
# ------------------------------------------------
client:
  server_url: "http://192.168.1.100:8080"
  client_id: null      # null = usa hostname
  collect_interval_minutes: 15

# ------------------------------------------------
# Ntfy.sh Configuration
# ------------------------------------------------
ntfy:
  enabled: true
  server_url: "https://ntfy.sh"    # O il tuo server self-hosted
  topic: "my-unique-topic"
  priority: "default"              # min, low, default, high, max

# ------------------------------------------------
# Alert Thresholds
# ------------------------------------------------
alerts:
  cpu_percent: 90.0
  ram_percent: 90.0
  disk_percent: 85.0
  temperature_celsius: 80.0
  load_avg_multiplier: 2.0    # soglia = cpu_count × multiplier

# ------------------------------------------------
# Notification Schedule
# ------------------------------------------------
notifications:
  daily_report_hour_utc: 7
  daily_report_minute_utc: 0
  send_immediate_alerts: true
  # Weekly package updates report
  weekly_packages_enabled: true
  weekly_packages_day: "monday"     # Giorno della settimana
  weekly_packages_hour_utc: 8
  weekly_packages_minute_utc: 0

# ------------------------------------------------
# Database
# ------------------------------------------------
database:
  path: "/data/system_monitor.db"
  retention_days: 30
```

### Variabili d'Ambiente

Le variabili d'ambiente hanno **priorità** sul file di configurazione. Prefisso: `SYSMON_*`

| Variabile | Descrizione | Default |
|-----------|-------------|---------|
| `SYSMON_MODE` | Modalità: `server` o `client` | `client` |
| `SYSMON_CONFIG_PATH` | Path del file config | `/config/config.yaml` |
| **Server** |
| `SYSMON_SERVER_HOST` | Bind address | `0.0.0.0` |
| `SYSMON_SERVER_PORT` | Porta | `8080` |
| **Client** |
| `SYSMON_SERVER_URL` | URL del server | `http://localhost:8080` |
| `SYSMON_CLIENT_ID` | ID del client | hostname |
| `SYSMON_COLLECT_INTERVAL` | Intervallo (minuti) | `15` |
| **Notifiche** |
| `SYSMON_NTFY_ENABLED` | Abilita notifiche | `true` |
| `SYSMON_NTFY_SERVER` | Server ntfy | `https://ntfy.sh` |
| `SYSMON_NTFY_TOPIC` | Topic ntfy | `system-monitor` |
| `SYSMON_NTFY_PRIORITY` | Priorità default | `default` |
| **Alert** |
| `SYSMON_ALERT_CPU` | Soglia CPU % | `90` |
| `SYSMON_ALERT_RAM` | Soglia RAM % | `90` |
| `SYSMON_ALERT_DISK` | Soglia Disco % | `85` |
| `SYSMON_ALERT_TEMP` | Soglia Temp °C | `80` |
| **Schedule** |
| `SYSMON_DAILY_HOUR` | Ora report giornaliero UTC | `7` |
| `SYSMON_WEEKLY_PKG_ENABLED` | Abilita report settimanale | `true` |
| `SYSMON_WEEKLY_PKG_DAY` | Giorno report (monday, etc.) | `monday` |
| `SYSMON_WEEKLY_PKG_HOUR` | Ora report settimanale UTC | `8` |
| **Database** |
| `SYSMON_DB_PATH` | Path database | `/data/system_monitor.db` |
| `SYSMON_DB_RETENTION` | Retention giorni | `30` |

### Esempio: Solo Variabili d'Ambiente

```bash
docker run -d \
  --name system-monitor-client \
  --pid host \
  -v /sys:/host/sys:ro \
  -e SYSMON_MODE=client \
  -e SYSMON_SERVER_URL=http://192.168.1.100:8080 \
  -e SYSMON_CLIENT_ID=webserver-prod \
  -e SYSMON_COLLECT_INTERVAL=15 \
  system-monitor
```

## 📡 API Endpoints

Il server espone una REST API completa:

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/metrics` | Riceve metriche dai client |
| `POST` | `/packages` | Riceve lista pacchetti aggiornabili |
| `GET` | `/clients` | Lista tutti i client registrati |
| `GET` | `/clients/{id}/summary` | Summary giornaliero per client |
| `GET` | `/packages` | Lista pacchetti aggiornabili (tutti i client) |
| `GET` | `/packages/{id}` | Pacchetti aggiornabili per client |
| `GET` | `/alerts` | Lista alert recenti |
| `POST` | `/test/daily-report` | Trigger manuale report giornaliero |
| `POST` | `/test/weekly-report` | Trigger manuale report settimanale |
| `POST` | `/test/collect` | Raccoglie metriche locali (test) |
| `POST` | `/test/collect-packages` | Raccoglie pacchetti locali (test) |

### Esempi di Utilizzo

**Health check:**
```bash
curl http://localhost:8080/health
```

**Lista client:**
```bash
curl http://localhost:8080/clients
```

**Summary di un client:**
```bash
curl "http://localhost:8080/clients/webserver-prod/summary?date=2024-01-15"
```

**Alert recenti:**
```bash
curl http://localhost:8080/alerts
```

**Trigger report manuale:**
```bash
curl -X POST http://localhost:8080/test/daily-report
```

## 🔔 Sistema di Notifiche

### Tipi di Notifiche

#### 1. Alert Immediati (Priorità Alta)

Inviati quando una metrica supera la soglia configurata:

```
⚠️ Alert: webserver-prod
🔥 CPU alto: 94.2% (soglia: 90%)
```

```
⚠️ Alert: database-server
💿 Disco pieno /data: 89.3% (soglia: 85%)
```

#### 2. Report Giornaliero (Priorità Normale)

Inviato ogni giorno all'ora configurata (default 07:00 UTC):

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

┌─ database-server (db-01)
│ CPU: avg 45.2% | max 92.1%
│ RAM: avg 78.3% | max 89.2%
│ Temp: avg 58°C | max 72°C
│ Disco: max 82.1% (/data)
│ Network: ↑0.12GB ↓0.89GB
│ Load max: 5.67 | Uptime: 1440.2h
│ ⚠️ Alert: 2
└─────────────────────────

┌─ backup-server (backup)
│ CPU: avg 12.1% | max 45.3%
│ RAM: avg 34.5% | max 45.1%
│ Disco: max 67.8% (/backup)
│ Network: ↑45.23GB ↓0.05GB
│ Load max: 1.23 | Uptime: 2160.0h
└─────────────────────────
```

#### 3. Report Settimanale Pacchetti (Priorità Variabile)

Inviato ogni settimana (default: Lunedì 08:00 UTC) con la lista dei pacchetti da aggiornare:

```
📦 Report Settimanale Pacchetti
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📅 Settimana: 2024-03
🖥️ Sistemi: 3
📊 Totale aggiornamenti: 47
🔒 Aggiornamenti sicurezza: 5

┌─ 🔴 database-server (db-01)
│ Pacchetti: 28 (apt)
│ 🔒 Sicurezza: 3
│ Top pacchetti:
│   • linux-image: 5.15.0-91 → 5.15.0-94
│   • openssl: 3.0.2-0ubuntu1.12 → 3.0.2-0ubuntu1.14
│   • curl: 7.81.0-1ubuntu1.14 → 7.81.0-1ubuntu1.15
│   • nginx: 1.18.0-6ubuntu14.3 → 1.18.0-6ubuntu14.4
│   • postgresql-14: 14.9-0ubuntu0.22.04.1 → 14.10-0ubuntu0.22.04.1
│   ... e altri 23
└────────────────────────────

┌─ 🟡 webserver-prod (webserver-prod)
│ Pacchetti: 15 (apt)
│ 🔒 Sicurezza: 2
│ Top pacchetti:
│   • linux-image: 5.15.0-91 → 5.15.0-94
│   • openssl: 3.0.2-0ubuntu1.12 → 3.0.2-0ubuntu1.14
│   • apache2: 2.4.52-1ubuntu4.6 → 2.4.52-1ubuntu4.7
│   • php8.1: 8.1.2-1ubuntu2.14 → 8.1.2-1ubuntu2.15
│   • libcurl4: 7.81.0-1ubuntu1.14 → 7.81.0-1ubuntu1.15
│   ... e altri 10
└────────────────────────────

┌─ 🟢 backup-server (backup)
│ Pacchetti: 4 (apt)
│ Top pacchetti:
│   • linux-image: 5.15.0-91 → 5.15.0-94
│   • rsync: 3.2.3-8ubuntu3.1 → 3.2.3-8ubuntu3.2
│   • tar: 1.34+dfsg-1ubuntu0.1.22.04.1 → 1.34+dfsg-1ubuntu0.1.22.04.2
│   • cron: 3.0pl1-137ubuntu3 → 3.0pl1-137ubuntu3.1
└────────────────────────────
```

**Indicatori di stato:**
- 🔴 Rosso: >50 pacchetti da aggiornare
- 🟡 Giallo: 10-50 pacchetti
- 🟢 Verde: <10 pacchetti

**Package manager supportati:**
- `apt` (Debian/Ubuntu)
- `dnf` (Fedora/RHEL 8+)
- `yum` (CentOS/RHEL 7)
- `pacman` (Arch Linux)
- `zypper` (openSUSE/SLES)

### Configurazione ntfy.sh

#### Server Pubblico (Default)

```yaml
ntfy:
  enabled: true
  server_url: "https://ntfy.sh"
  topic: "mio-topic-unico-12345"
```

⚠️ **Sicurezza**: Usa un topic difficile da indovinare! Chiunque conosca il topic può sottoscrivere le notifiche.

#### Server Self-Hosted

```yaml
ntfy:
  enabled: true
  server_url: "https://ntfy.miodominio.com"
  topic: "system-monitor"
```

Per installare ntfy self-hosted: [ntfy.sh/docs/install](https://ntfy.sh/docs/install/)

## 🐳 Docker

### Build dell'Immagine

```bash
cd system-monitor
docker build -t system-monitor .
```

### Docker Compose

Il file `docker-compose.yml` include due profili:

```bash
# Avvia come server
docker compose --profile server up -d

# Avvia come client
docker compose --profile client up -d

# Oppure specifica il servizio
docker compose up -d system-monitor-server
docker compose up -d system-monitor-client
```

### Volumi e Mount Importanti

| Mount | Descrizione | Necessario |
|-------|-------------|------------|
| `./config.yaml:/config/config.yaml:ro` | File di configurazione | ✅ Sì |
| `system-monitor-data:/data` | Database SQLite | ✅ Solo server |
| `/sys:/host/sys:ro` | Sensori temperatura | ⚠️ Opzionale |

### Opzioni Docker Importanti

```yaml
# CRITICO: Permette di leggere le metriche dell'host
pid: host

# OPZIONALE: Metriche di rete accurate dell'host
network_mode: host
```

### Run Manuale (senza Compose)

**Server:**
```bash
docker run -d \
  --name system-monitor-server \
  --pid host \
  -p 8080:8080 \
  -v $(pwd)/config.yaml:/config/config.yaml:ro \
  -v system-monitor-data:/data \
  -v /sys:/host/sys:ro \
  -e SYSMON_MODE=server \
  system-monitor
```

**Client:**
```bash
docker run -d \
  --name system-monitor-client \
  --pid host \
  -v $(pwd)/config.yaml:/config/config.yaml:ro \
  -v /sys:/host/sys:ro \
  -e SYSMON_MODE=client \
  system-monitor
```

## 🗄️ Database Schema

Il database SQLite contiene le seguenti tabelle:

### `metrics`
Storico completo delle metriche raccolte.

| Campo | Tipo | Descrizione |
|-------|------|-------------|
| `id` | INTEGER | Primary key |
| `client_id` | TEXT | ID del client |
| `hostname` | TEXT | Hostname del sistema |
| `collected_at` | TIMESTAMP | Momento della raccolta |
| `cpu_percent` | REAL | % utilizzo CPU |
| `cpu_temp_max` | REAL | Temperatura max °C |
| `ram_percent` | REAL | % utilizzo RAM |
| `disk_partitions` | TEXT | JSON array partizioni |
| ... | ... | Altri campi |

### `clients`
Registro dei client connessi.

| Campo | Tipo | Descrizione |
|-------|------|-------------|
| `client_id` | TEXT | Primary key |
| `hostname` | TEXT | Hostname |
| `first_seen` | TIMESTAMP | Prima connessione |
| `last_seen` | TIMESTAMP | Ultima connessione |
| `metrics_count` | INTEGER | Metriche totali inviate |

### `alerts`
Storico degli alert generati.

| Campo | Tipo | Descrizione |
|-------|------|-------------|
| `id` | INTEGER | Primary key |
| `client_id` | TEXT | Client che ha generato l'alert |
| `metric_name` | TEXT | Nome della metrica |
| `current_value` | REAL | Valore attuale |
| `threshold_value` | REAL | Soglia superata |
| `notified` | INTEGER | 1 se già notificato |

### `daily_reports`
Registro dei report giornalieri inviati.

| Campo | Tipo | Descrizione |
|-------|------|-------------|
| `id` | INTEGER | Primary key |
| `report_date` | DATE | Data del report |
| `sent_at` | TIMESTAMP | Momento dell'invio |
| `client_count` | INTEGER | Client inclusi |

## 🔧 Troubleshooting

### Temperatura CPU non disponibile

La lettura della temperatura richiede sensori configurati sull'host.

```bash
# Installa lm-sensors
sudo apt install lm-sensors

# Rileva i sensori
sudo sensors-detect

# Verifica
sensors
```

Se la temperatura non è disponibile, il sistema continuerà a funzionare normalmente, semplicemente non includerà questa metrica.

### Client non si connette al server

1. **Verifica che il server sia raggiungibile:**
   ```bash
   curl http://SERVER_IP:8080/health
   ```

2. **Controlla i log del client:**
   ```bash
   docker logs -f system-monitor-client
   ```

3. **Verifica il firewall:**
   ```bash
   # Sul server
   sudo ufw allow 8080/tcp
   ```

4. **Verifica la configurazione:**
   ```bash
   docker exec system-monitor-client cat /config/config.yaml
   ```

### Metriche non accurate (container vs host)

Se le metriche mostrano i valori del container invece dell'host, assicurati di usare `--pid host`:

```bash
# Corretto
docker run --pid host ...

# Nel docker-compose.yml
services:
  system-monitor-client:
    pid: host
```

### Database corrotto

Se il database SQLite si corrompe:

```bash
# Backup
docker exec system-monitor-server cp /data/system_monitor.db /data/backup.db

# Ricrea (perdi i dati)
docker exec system-monitor-server rm /data/system_monitor.db
docker restart system-monitor-server
```

### Notifiche non arrivano

1. **Verifica la configurazione ntfy:**
   ```bash
   docker exec system-monitor-server cat /config/config.yaml | grep -A5 ntfy
   ```

2. **Testa manualmente:**
   ```bash
   curl -d "Test notification" https://ntfy.sh/tuo-topic
   ```

3. **Controlla i log:**
   ```bash
   docker logs system-monitor-server | grep -i ntfy
   ```

4. **Trigger manuale del report:**
   ```bash
   curl -X POST http://localhost:8080/test/daily-report
   ```

### Log verbosi

Per debug più dettagliato, puoi modificare il logging nel codice o controllare i log esistenti:

```bash
# Server
docker logs -f system-monitor-server 2>&1 | grep -E "(ERROR|WARNING|INFO)"

# Client  
docker logs -f system-monitor-client 2>&1 | grep -E "(ERROR|WARNING|INFO)"
```

## 📁 Struttura del Progetto

```
system-monitor/
├── Dockerfile                 # Multi-stage build Python 3.12
├── docker-compose.yml         # Compose con profili server/client
├── requirements.txt           # Dipendenze Python
├── config.yaml.example        # Template configurazione
├── .dockerignore              # File da escludere dal build
├── README.md                  # Questa documentazione
│
└── src/
    ├── __init__.py            # Package init
    ├── main.py                # Entrypoint principale
    ├── config.py              # Caricamento configurazione
    ├── models.py              # Data models (Pydantic)
    ├── collector.py           # Raccolta metriche (psutil)
    ├── database.py            # Layer SQLite
    ├── server.py              # REST API (FastAPI)
    ├── client.py              # Client HTTP (httpx)
    └── notifier.py            # Notifiche (ntfy.sh)
```

## 📦 Dipendenze

| Package | Versione | Uso |
|---------|----------|-----|
| `fastapi` | 0.104.1 | REST API framework |
| `uvicorn` | 0.24.0 | ASGI server |
| `httpx` | 0.25.2 | HTTP client async |
| `psutil` | 5.9.6 | Raccolta metriche sistema |
| `pyyaml` | 6.0.1 | Parsing config YAML |
| `aiosqlite` | 0.19.0 | SQLite async |
| `apscheduler` | 3.10.4 | Job scheduling |
| `pydantic` | 2.5.2 | Data validation |

## 🔒 Sicurezza

### Raccomandazioni

1. **Topic ntfy**: Usa un topic lungo e casuale, non facilmente indovinabile
2. **Rete**: Se possibile, usa una rete privata tra server e client
3. **Firewall**: Limita l'accesso alla porta 8080 solo agli IP dei client
4. **HTTPS**: Per ambienti production, metti un reverse proxy (nginx/traefik) davanti al server

### Esempio con Traefik

```yaml
services:
  system-monitor-server:
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.sysmon.rule=Host(`monitor.miodominio.com`)"
      - "traefik.http.routers.sysmon.tls.certresolver=letsencrypt"
```

## 📝 License

MIT License

## 🤝 Contributing

Pull request benvenute! Per modifiche importanti, apri prima una issue per discutere le modifiche proposte.

