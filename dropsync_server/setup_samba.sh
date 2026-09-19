#!/usr/bin/env bash
# ==============================================================================
# DropSync — Samba LAN Share Setup Script for Ubuntu / Debian Linux
# Exports the sync directory to local Windows and macOS PCs over Gigabit LAN.
# ==============================================================================

set -e

# Default share path
DEFAULT_SHARE_DIR="$HOME/DropSyncShare"
SHARE_DIR="${1:-$DEFAULT_SHARE_DIR}"
CURRENT_USER="$(whoami)"

echo "=== 📁 DropSync Samba Share Configuration ==="
echo "Target directory: $SHARE_DIR"
echo "Owner user:       $CURRENT_USER"

# 1. Install Samba if missing
if ! command -v smbd &>/dev/null; then
    echo "Installing Samba package via apt..."
    sudo apt-get update -qq
    sudo apt-get install -y -qq samba
fi

# 2. Create directory with proper permissions
mkdir -p "$SHARE_DIR"
chmod 0775 "$SHARE_DIR"

# 3. Check if [DropSync] already exists in /etc/samba/smb.conf
CONF_FILE="/etc/samba/smb.conf"
BACKUP_FILE="/etc/samba/smb.conf.backup.$(date +%Y%m%d_%H%M%S)"

if grep -q "\[DropSync\]" "$CONF_FILE"; then
    echo "Notice: [DropSync] share already exists in $CONF_FILE. Updating path..."
    sudo sed -i "/\[DropSync\]/,/path =/ s|path = .*|path = $SHARE_DIR|" "$CONF_FILE"
else
    echo "Adding [DropSync] share to $CONF_FILE..."
    sudo cp "$CONF_FILE" "$BACKUP_FILE"

    sudo tee -a "$CONF_FILE" > /dev/null <<EOF

[DropSync]
   comment = DropSync Fast LAN Share
   path = $SHARE_DIR
   browseable = yes
   read only = no
   guest ok = yes
   create mask = 0664
   directory mask = 0775
   force user = $CURRENT_USER
EOF
fi

# 4. Restart Samba service
echo "Restarting Samba service (smbd)..."
sudo systemctl restart smbd
sudo systemctl enable smbd >/dev/null 2>&1 || true

# 5. Display local IP address and connection instructions
LOCAL_IP="$(hostname -I | awk '{print $1}')"

echo ""
echo "=============================================================================="
echo " ✔ Samba LAN Share successfully configured!"
echo "=============================================================================="
echo " 📂 Local Path: $SHARE_DIR"
echo ""
echo " 🖥️ How to connect from your computers on the same Wi-Fi / Local Network:"
echo ""
echo "   🪟 Windows (File Explorer):"
echo "      Press Win + R and enter: \\\\$LOCAL_IP\\DropSync"
echo "      (Or map it as a Network Drive like Z:)"
echo ""
echo "   🍏 macOS (Finder):"
echo "      Press Cmd + K and enter: smb://$LOCAL_IP/DropSync"
echo ""
echo "   🐧 Linux (Nautilus / Dolphin):"
echo "      smb://$LOCAL_IP/DropSync"
echo "=============================================================================="
