# DropFile Project Rules & Architecture

Родительский контекст: C:\_CODE\AGENTS.md  
Проект: DropFile & DropSync (High-Performance Bi-Directional File Synchronization & Telemetry)

---

## 1. Строгое правило версионирования (VERSION BUMP POLICY)
- **ОБЯЗАТЕЛЬНОЕ поднятие версии**: При любых изменениях в кодовой базе (клиент DropFile, GUI, модули dropsync_server, скрипты сборки) **СТРОГО ОБЯЗАТЕЛЬНО** поднимать номер версии:
  - `version.py`: `__version__` (SemVer: `major.minor.patch`) и `__build__` (номер инкремента).
- **Git релизы и теги**:
  - После завершения задачи обязательно создавать аннотированный тег: `git tag -a v<VERSION> -m "Release v<VERSION>: <описание>"`
  - Отправлять ветку и тег в GitHub: `git push origin main && git push origin v<VERSION>`.
  - Тег автоматически запускает сборку GitHub Actions для Windows (`DropFile.exe`) и macOS (`DropFile-macOS.zip`).
- **Локальная компиляция**:
  - При каждом релизе запускать `python build_exe.py`.
  - Скомпилированный бинарник копировать в `D:\DropFile_exe\DropFile.exe`.

## 2. Архитектура папок: Exchange vs Output
- **Exchange**:
  - Папка высокоскоростной межсерверной синхронизации по WebSocket через DropSync daemon.
  - Сетевая шара Samba: `\\<HOST>\Exchange` (на рабочем сервере `192.168.0.22`, на домашнем сервере `192.168.1.4`).
  - DropFile SyncEngine (WebDAV FileBrowser) **строго изолирован** от папки `Exchange` и не синхронизирует её через медленный HTTP API.
- **Output**:
  - Папка публикации для внешних пользователей через File Browser WebDAV/HTTP.
  - На серверах права на каталог `Output` всегда должны быть полными: `chmod -R 777 Output`, чтобы исключить ошибку 403 Forbidden.

## 3. Графический интерфейс и телеметрия (Zero-Freeze GUI)
- **Запрет на блокировку GUI-потока**:
  - Сетевые вызовы к серверным API телеметрии (`http://<host>:19877/traffic`) и SMB-проверки **КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО** выполнять синхронно в главном потоке Tkinter.
  - Опрос серверов должен всегда работать в асинхронном фоновом потоке-демоне (`threading.Thread`), отдавая в GUI кэшированные данные за 0 мс.
- **Приоритет HTTP API**:
  - Первым всегда опрашивать легковесный HTTP API на порту 19877 с коротким таймаутом (0.5–0.6 сек).
  - SMB-проверки выполнять только в том случае, если TCP-порт 445 отвечает быстрее 100 мс, чтобы избежать системных блокировок Windows (25–45 сек).
