# 🐧 DropFile для Linux

DropFile поддерживает работу на дистрибутивах Linux (Ubuntu, Debian, Linux Mint, Fedora, Arch Linux) в двух режимах:
1. **Desktop GUI** — с иконкой в системном трее, десктопными уведомлениями и окном настроек.
2. **Headless / Server** — фоновый демон без GUI для домашних серверов, NAS, мини-ПК и одноплатных компьютеров (Raspberry Pi), управляемый через `systemd` или командную строку.

---

## ⚡ Быстрый старт

### 1. Автоматическая установка

```bash
chmod +x install_linux.sh run_linux.sh
./install_linux.sh
```

Установщик:
- Создает изолированное виртуальное окружение `.venv`
- Устанавливает все необходимые Python-пакеты
- Создает локальную папку обмена `~/Desktop/DropFile` (или `~/DropFile`)
- Регистрирует ярлык приложения в системном меню (`~/.local/share/applications/dropfile.desktop`)
- Создает пользовательскую службу `systemd` (`~/.config/systemd/user/dropfile.service`)

---

## 🖥️ Использование на сервере (Headless Daemon)

На сервере без графической оболочки (без X11 / Wayland) DropFile автоматически переходит в консольный headless-режим.

### Запуск службы systemd (рекомендуется):

```bash
# Включить автозапуск при загрузке системы и запустить службу прямо сейчас:
systemctl --user enable --now dropfile.service

# Проверить статус службы:
systemctl --user status dropfile.service

# Просмотр логов в реальном времени:
journalctl --user -u dropfile.service -f

# Остановить службу:
systemctl --user stop dropfile.service
```

### Запуск напрямую из консоли:

```bash
./run_linux.sh --headless
```

---

## 💻 Управление из командной строки (CLI)

Вы можете отправлять команды работающему фоновому экземпляру DropFile из любого терминала или скрипта:

```bash
./run_linux.sh --status         # Запрос текущего статуса синхронизации
./run_linux.sh --sync-now       # Мгновенно запустить проверку и синхронизацию файлов
./run_linux.sh --pause          # Приостановить синхронизацию
./run_linux.sh --resume         # Возобновить синхронизацию
./run_linux.sh --stop           # Корректно завершить фоновый процесс
./run_linux.sh --help           # Список всех доступных параметров
```

---

## 🖼️ Использование на Desktop (с графическим интерфейсом)

### Запуск с треем:
```bash
./run_linux.sh
```

### Открыть окно настроек:
```bash
./run_linux.sh --settings
```

### Системные пакеты для GUI (при необходимости):
- **Окно настроек (Tkinter)**:
  - Ubuntu/Debian/Mint: `sudo apt install python3-tk`
  - Fedora: `sudo dnf install python3-tkinter`
  - Arch: `sudo pacman -S tk`
- **Иконка в трее (AppIndicator)**:
  - Ubuntu/Debian: `sudo apt install gir1.2-ayatanaappindicator3-0.1` (или `gir1.2-appindicator3-0.1`)

---

## 📦 Сборка автономного бинарного файла (PyInstaller)

Для сборки единого исполняемого файла, не требующего установленного Python у пользователей:

```bash
pip install pyinstaller
python3 build_linux.py
```

Результат: бинарник `dist/dropfile`, готовый к распространению.

---

## 🚀 Удаленный запуск доверенных приложений (Remote Control)

DropFile позволяет настроить список доверенных приложений на Linux-компьютере, которые можно удаленно запускать или перезапускать с других компьютеров через DropFile (например, при зависании программы):

### Примеры заполнения в «Настройки ➔ Удаленное управление»:

| Приложение | Название (ID) | Путь к исполняемому файлу | Параметры (необязательно) |
|---|---|---|---|
| **RustDesk** | `RustDesk` | `/usr/bin/rustdesk` *(или `rustdesk`)* | *(пусто)* или `--minimized` *(в трей)* |
| **GNOME Календарь** | `Calendar` *(или `Календарь`)* | `/usr/bin/gnome-calendar` | *(пусто)* |
| **KDE Календарь** | `Calendar` | `/usr/bin/korganizer` | *(пусто)* |
| **Telegram Desktop** | `Telegram` | `/usr/bin/telegram-desktop` | `-startintray` |
| **Flatpak-приложение** | `Calendar` | `/usr/bin/flatpak` | `run org.gnome.Calendar` |

### 💡 Как быстро найти точный путь к программе в Linux:

```bash
# 1. Поиск через which или type:
which rustdesk
# -> /usr/bin/rustdesk

which gnome-calendar
# -> /usr/bin/gnome-calendar

# 2. Узнать точную команду из системного .desktop ярлыка:
grep -E '^Exec=' /usr/share/applications/*calendar*.desktop
# -> Exec=gnome-calendar %U
```

