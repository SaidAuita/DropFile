# ⚡ DropSync Server — Fast Linux-to-Linux Bi-Directional File Synchronization

**DropSync Server** — это легковесный, высокоскоростной демон синхронизации файлов между двумя Linux-серверами (например, **Домашний сервер ↔ Рабочий сервер**) по защищенному WebSocket-каналу (WSS), спроектированный для работы в условиях блокировок WebDAV и корпоративных файрволов.

Локальные компьютеры (Windows / macOS / Linux) подключаются к серверу напрямую через **общую сетевую папку (Samba / SMB)** со скоростью гигабитной локальной сети без необходимости устанавливать клиентское ПО на рабочие станции.

---

## 🌟 Ключевые преимущества

1. **Мгновенный отклик (`inotify`)**: Никакого медленного REST-поллинга. Демон слушает события ядра Linux (`IN_CLOSE_WRITE`) — файл начинает передаваться сразу же в момент сохранения.
2. **Обход блокировок (WSS на порту 443 / 8443)**: Трафик передается по WebSockets поверх TLS. Для любых DPI-файрволов и прокси это выглядит как обычное веб-соединение (HTTPS). Блокировки WebDAV, SMB и P2P не влияют на работу.
3. **Потоковый стриминг чанками (Chunked Streaming)**: Файлы передаются потоком блоками по 1 МБ с проверкой SHA-256 и докачкой при обрывах. Память не расходуется даже при передаче файлов размером в сотни гигабайт.
4. **Сетевой диск по локалке (Samba)**: На рабочем ПК папка подключается как диск `\\server\DropSync`. Сохранение файлов происходит с максимальной скоростью накопителя и локальной сети (100–115 МБ/с).
5. **Безопасное удаление (Корзина)**: Удаленные файлы не стираются безвозвратно, а перемещаются в скрытую папку `.dropsync_trash` с возможностью восстановления.

---

## 🏗️ Архитектура

```
[ Рабочий ПК (Windows / Mac) ]
         │  (Гигабитный SMB-диск: \\<server-ip>\DropSync)
         ▼
[ Сервер 1 (Дом) ]  <─── WebSocket / TLS (WSS) ───>  [ Сервер 2 (Работа) ]
                             (Порт 443 или 8443)              │
                                                              ▼  (SMB-диск)
                                                [ Рабочий ПК (Windows / Mac) ]
```

---

## 🚀 Быстрый старт на Linux (Ubuntu / Debian)

### 1. Установка зависимостей

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-websockets samba
pip3 install watchdog --break-system-packages 2>/dev/null || true
```

### 2. Развертывание проекта

Клонируйте репозиторий или скопируйте папку `dropsync_server` в домашний каталог (например, `~/dropsync`):

```bash
mkdir -p ~/dropsync
cd ~/dropsync
```

---

## ⚙️ Настройка нод (Дом и Работа)

### Сервер 1: Домашний сервер (Server Mode)

1. Создайте файл конфигурации:
   ```bash
   python3 -m dropsync_server.main --init-config
   ```
   Файл будет создан по пути `~/.dropsync/dropsync.json`.

2. Отредактируйте `~/.dropsync/dropsync.json`:
   ```json
   {
       "node_name": "home-server",
       "role": "server",
       "sync_dir": "/home/said/DropSyncShare",
       "listen_host": "0.0.0.0",
       "listen_port": 8443,
       "auth_token": "ВАШ_СЕКРЕТНЫЙ_ТОКЕН_ЗДЕСЬ"
   }
   ```

3. Запустите:
   ```bash
   python3 -m dropsync_server.main
   ```

---

### Сервер 2: Рабочий сервер (Client Mode)

Рабочий сервер будет сам инициировать исходящее защищенное WebSocket-соединение к домашнему серверу (исходящий трафик на порт 443/8443 обычно открыт на любом предприятии):

1. Отредактируйте `~/.dropsync/dropsync.json` на рабочем сервере:
   ```json
   {
       "node_name": "work-server",
       "role": "client",
       "sync_dir": "/home/said/DropSyncShare",
       "remote_url": "ws://ВАШ_ДОМАШНИЙ_IP_ИЛИ_ДОМЕН:8443",
       "auth_token": "ТОТ_ЖЕ_САМЫЙ_СЕКРЕТНЫЙ_ТОКЕН"
   }
   ```

2. Запустите:
   ```bash
   python3 -m dropsync_server.main
   ```

> **Совет**: Так как WebSocket полнодуплексный (двусторонний), после установки соединения файлы автоматически мгновенно передаются в обе стороны (Дом ➔ Работа и Работа ➔ Дом)!

---

## 📁 Настройка сетевой папки (Samba LAN Share)

Чтобы папка была видна в Проводнике Windows и macOS Finder на максимальной скорости гигабитной сети:

Запустите скрипт автоматической настройки:
```bash
chmod +x setup_samba.sh
sudo ./setup_samba.sh /path/to/DropSyncShare
```

### Подключение с компьютеров:
- **Windows**: Нажмите `Win + R` и введите `\\<server-ip>\DropSync` (или правой кнопкой на «Этот компьютер» ➔ «Подключить сетевой диск»).
- **macOS**: Нажмите `Cmd + K` в Finder и введите `smb://<server-ip>/DropSync`.

---

## 🔄 Автозапуск 24/7 (systemd)

Для фоновой работы службы создайте systemd user-сервис:

```bash
mkdir -p ~/.config/systemd/user/
cp dropsync.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now dropsync.service
```

Проверка статуса:
```bash
systemctl --user status dropsync.service
journalctl --user -u dropsync.service -f
```

---

## 📊 Проверка статуса через CLI

```bash
python3 -m dropsync_server.main --status
```
Покажет общее количество активных файлов, удаленных файлов (tombstones) и журнал последних передач.
