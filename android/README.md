<div align="center">

# 📱 DropFile Mobile (Android)

**Ultra-fast companion mobile application for Android to send photos, videos, and files directly into your [FileBrowser](https://github.com/filebrowser/filebrowser) exchange folder (`/Exchange/Mobile`) with instant PC synchronization.**

[![Platform](https://img.shields.io/badge/Platform-Android%207.0%2B%20(API%2024%2B)-green.svg)](#)
[![Kotlin](https://img.shields.io/badge/Kotlin-1.9.23-purple.svg)](https://kotlinlang.org/)
[![Release](https://img.shields.io/badge/Latest%20APK-v1.30.1-blue.svg)](https://github.com/SaidAuita/DropFile/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](../LICENSE)

<br/>

*[English](#english) &bull; [Русский](#russian)*

</div>

---

<a name="english"></a>
## 🇬🇧 English Guide

### 🌟 Overview

**DropFile Mobile** is a lightweight native Android client designed for frictionless file transfers from your smartphone into your private server storage.

```
┌─────────────────────────┐
│     Android Phone       │
│ (Gallery / Camera / UI) │
└────────────┬────────────┘
             │
             │ 1-Tap "Share" (HTTPS / HTTP)
             ▼
┌─────────────────────────────────────────────────────────┐
│              Connection Methods (No White IP Needed!)   │
│  • Keenetic KeenDNS Cloud:  https://my-nas.keenetic.link│
│  • Direct Public White IP:  http://123.45.67.89:8080    │
│  • Cloudflare Tunnel:       https://files.yourdomain.com│
│  • Tailscale Mesh VPN:      http://100.x.y.z:8080       │
└────────────────────────────┬────────────────────────────┘
                             │
                             ▼
              ┌──────────────────────────────┐
              │      FileBrowser Server      │
              │  Writes to: /Exchange/Mobile │
              └──────────────┬───────────────┘
                             │
                             │ Instant Auto-Sync
                             ▼
              ┌──────────────────────────────┐
              │     Desktop PC (DropFile)    │
              │ Downloaded to Desktop folder │
              └──────────────────────────────┘
```

---

### ✨ Features

- ⚡ **Instant Share Sheet Integration**: Select photos/files in Samsung Gallery, Google Photos, Files, Telegram, or WhatsApp &rarr; tap **"Share" &rarr; "DropFile"**. Files upload in background with a clean progress bar.
- 📥 **1-Click Configuration Import**: No manual typing of long URLs, tokens, or passwords on mobile keyboards. Simply import `dropfile_mobile_config.json`.
- 🌐 **No Static / White IP Required**: Works seamlessly over Keenetic KeenDNS Cloud proxy, Cloudflare Tunnel, Tailscale, or direct IP.
- 📋 **Built-in Diagnostic Logger**: Real-time log viewer in toolbar with one-click clipboard copying for troubleshooting.
- 📦 **Direct APK Distribution**: Pre-compiled release `.apk` downloadable directly via browser without Google Play Store dependency.
- 🕒 **Transfer History**: Keeps track of recent uploads with status (Success/Error), file size, and timestamps.

---

### 🌐 Connection Methods: Do you need a White IP?

**NO! A public (white) IP is completely optional.** You can configure DropFile Mobile using any of the following setups:

| Method | Requires White IP? | Router Configuration | Notes & Advantages |
| :--- | :---: | :---: | :--- |
| **Keenetic KeenDNS (Cloud mode)** | ❌ **No** | None (Zero ports) | **Recommended for home users**. Uses Keenetic Cloud proxy (`*.keenetic.link`). Auto Let's Encrypt HTTPS certificate. Works on 4G/CGNAT. |
| **Cloudflare Tunnel** | ❌ **No** | None (Zero ports) | **Recommended for any router**. Free `cloudflared` daemon on PC/server gives `https://files.domain.com`. |
| **Tailscale / ZeroTier** | ❌ **No** | None (Zero ports) | Private mesh VPN (`100.x.y.z`). Highly secure, server hidden from public Internet. |
| **Direct White IP** | ✅ **Yes** | Port Forwarding | Fast direct connection (`http://IP:PORT` or `https://`). Requires port forward on router. |

---

### 🚀 Installation & Setup Step-by-Step

#### Step 1: Export Configuration on PC
In your DropFile desktop folder on Windows/macOS/Linux, run:
```bash
python export_mobile_config.py --url https://YOUR_SERVER_URL --folder /Exchange/Mobile
```
*(If your desktop `config.json` already contains your external server URL, simply run `python export_mobile_config.py`)*.

This generates **`dropfile_mobile_config.json`**:
```json
{
    "server_url": "https://photo.buka3033.keenetic.link",
    "username": "said",
    "password": "your_password",
    "target_folder": "/Exchange/Mobile",
    "auto_close": true
}
```

#### Step 2: Download & Install APK on Android
1. Download **`DropFile-Mobile.apk`** from GitHub Releases:  
   👉 [Download DropFile-Mobile.apk](https://github.com/SaidAuita/DropFile/releases/latest/download/DropFile-Mobile.apk)
2. Open the downloaded file on your Android phone and confirm installation (*Allow installation from browser/files if prompted*).

#### Step 3: Import Configuration
1. Send `dropfile_mobile_config.json` to your phone (via Telegram Saved Messages, USB, email, or upload it to FileBrowser).
2. Launch **DropFile Mobile** on your phone.
3. Tap the **Settings** icon (gear in top right).
4. Tap **«📥 Import configuration (.json)»** and pick `dropfile_mobile_config.json`.
5. All fields will populate instantly, and the app will verify connectivity with your server!

---

### 📸 Daily Usage

#### Method A: 1-Tap Share from Gallery / Apps (Recommended)
1. Open **Gallery** or **Files**, select one or multiple photos/documents.
2. Tap the system **Share** button.
3. Select **DropFile**.
4. A card will pop up showing the progress:
   ```
   Uploading (1/3): IMG_20260922_124500.jpg [====>     ] 45%
   ```
5. Once completed, the window auto-closes. The files immediately land on your PC!

#### Method B: In-App File Picker
1. Open **DropFile Mobile**.
2. Tap the big card **«Pick and send files»**.
3. Select any files using Android's system document picker.

---

### 🛠️ Troubleshooting & Logs

- Tap the **Log document icon (📋)** in the top app bar of the Main screen or Settings screen.
- The log viewer shows real-time network requests, HTTP status codes, and error details.
- Tap **"Copy"** to paste logs into messages for quick support.

---

<br/>
<hr/>
<br/>

<a name="russian"></a>
## 🇷🇺 Подробное руководство на русском

### 💡 О мобильном приложении

**DropFile Mobile** — это легковесное нативное Android-приложение для мгновенной передачи фотографий, видео и файлов со смартфона в вашу личную папку обмена **FileBrowser** (`/Exchange/Mobile`) с автоматическим скачиванием на рабочий или домашний ПК через десктопный клиент **DropFile**.

---

### ✨ Главные преимущества

- ⚡ **Мгновенная отправка из системного меню «Поделиться»**: в Галерее Samsung, Google Фото, Проводнике, Telegram или WhatsApp выделите файлы &rarr; нажмите **«Поделиться» &rarr; «DropFile»**. Файлы выгружаются в фоне с наглядным прогресс-баром.
- 📥 **Импорт настроек в 1 клик**: не нужно вручную вводить сложные адреса, пароли и папки на клавиатуре смартфона. Достаточно импортировать файл `dropfile_mobile_config.json`.
- 🌐 **Белый IP НЕ требуется**: приложение отлично работает через облачный прокси Keenetic KeenDNS, Cloudflare Tunnel, Tailscale или по прямому IP.
- 📋 **Встроенный журнал логов**: иконка блокнота в шапке открывает подробный журнал работы с кнопкой копирования в буфер обмена.
- 📦 **Установка напрямую по ссылке (APK)**: без Google Play Store — свежий APK собирается автоматически в GitHub Actions.
- 🕒 **История отправок**: сохраняет последние 50 переданных файлов со статусами (Успешно / Ошибка), датой и размером.

---

### 🌐 Нужен ли белый IP для работы?

**НЕТ! Белый IP абсолютно не обязателен.** Вы можете настроить доступ любым удобным способом:

| Способ подключения | Нужен белый IP? | Настройка роутера | Преимущества |
| :--- | :---: | :---: | :--- |
| **Keenetic KeenDNS (режим «Через облако»)** | ❌ **Не нужен** | Никакой (порты закрыты) | **Идеально для дома/офиса с роутером Keenetic**. Работает через облако Keenetic (`*.keenetic.link`). Автоматический бесплатный SSL-сертификат Let's Encrypt (HTTPS). Работает даже на 4G-модемах. |
| **Cloudflare Tunnel** | ❌ **Не нужен** | Никакой (порты закрыты) | **Универсально для любых роутеров**. Бесплатная утилита `cloudflared` даёт постоянный защищенный адрес вида `https://files.вашдомен.ru`. |
| **Tailscale / ZeroTier** | ❌ **Не нужен** | Никакой (порты закрыты) | Приватная Mesh-VPN сеть. Сервер полностью изолирован от публичного интернета. |
| **Прямой белый IP** | ✅ **Нужен** | Проброс портов (Port Forward) | Прямое быстрое подключение (`http://IP:PORT` или `https://`). |

---

### 🚀 Пошаговая установка и настройка

#### Шаг 1: Экспорт файла настроек на компьютере
В папке десктопного DropFile на компьютере выполните команду:
```bash
python export_mobile_config.py --url https://ВАШ_АДРЕС_СЕРВЕРА --folder /Exchange/Mobile
```
*(Если в вашем `config.json` на ПК уже прописан внешний адрес, достаточно запустить просто `python export_mobile_config.py`)*.

Скрипт создаст готовый файл **`dropfile_mobile_config.json`**:
```json
{
    "server_url": "https://photo.buka3033.keenetic.link",
    "username": "said",
    "password": "your_password",
    "target_folder": "/Exchange/Mobile",
    "auto_close": true
}
```

#### Шаг 2: Скачивание и установка APK на смартфон
1. Скачайте актуальный **`DropFile-Mobile.apk`** по прямой ссылке:  
   👉 [Скачать DropFile-Mobile.apk](https://github.com/SaidAuita/DropFile/releases/latest/download/DropFile-Mobile.apk)
2. Откройте скачанный `.apk` на телефоне и подтвердите установку (*разрешите установку из браузера/проводника, если система запросит разрешение*).

#### Шаг 3: Быстрый импорт конфигурации
1. Передайте файл `dropfile_mobile_config.json` на телефон (через «Избранное» в Telegram, по проводу, через почту или загрузите в веб-интерфейс FileBrowser).
2. Запустите приложение **DropFile Mobile** на телефоне.
3. Нажмите на иконку **Настройки** (шестерёнка в правом верхнем углу).
4. Нажмите **«📥 Импортировать файл настроек (.json)»** и выберите переданный файл.
5. Все параметры заполнятся автоматически, и приложение сразу проверит связь с сервером!

---

### 📸 Повседневное использование

#### Вариант А: Быстрая отправка в 1 клик из любого приложения (Основной сценарий)
1. Откройте **Галерею**, выделите одно или несколько фото, видео или документов.
2. Нажмите кнопку **«Поделиться»** (Share).
3. В списке приложений выберите **DropFile**.
4. Появится окно отправки с процентами и скоростью:
   ```
   Отправка (1/3): IMG_20260922_124500.jpg [====>     ] 45%
   ```
5. По завершении окно закроется автоматически, а файлы сразу скачаются клиентом DropFile на ваш ПК!

#### Вариант Б: Выбор файлов из самого приложения
1. Откройте **DropFile Mobile**.
2. Нажмите большую кнопку **«Выбрать и отправить файлы»**.
3. Выберите любые файлы через системный файловый менеджер Android.

---

### 🛠️ Просмотр логов и диагностика

- Нажмите на иконку **документа с логами (📋)** в правом верхнем углу главного экрана или в настройках.
- Откроется окно журнала с отметками времени, HTTP-статусами и подробными деталями передачи.
- Кнопка **«Скопировать»** сохраняет весь журнал в буфер обмена для быстрой отправки в поддержку.
